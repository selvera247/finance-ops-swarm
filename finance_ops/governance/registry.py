"""Agent registry with lifecycle (active | deprecated | retired)."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from data_plane.config import WAREHOUSE_DIR, ensure_dirs
from finance_ops.governance.audit import append_audit

Status = Literal["active", "deprecated", "retired"]

_SEED_PATH = Path(__file__).resolve().parent / "registry.yaml"
_LOCK = threading.RLock()


class RegistryLoadError(RuntimeError):
    """Fail closed when registry cannot be loaded."""


@dataclass
class AgentRecord:
    name: str
    owner: str = "unassigned"
    created_at: str = ""
    last_run_at: str | None = None
    ttl_days: int = 90
    status: Status = "active"
    latest_eval_score: float | None = None
    eval_threshold: float = 0.8
    credentials_revoked: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def seed_path() -> Path:
    override = os.getenv("FINANCE_OPS_REGISTRY_PATH", "").strip()
    return Path(override) if override else _SEED_PATH


def state_path() -> Path:
    ensure_dirs()
    root = WAREHOUSE_DIR / "governance"
    root.mkdir(parents=True, exist_ok=True)
    return root / "registry.json"


def _parse_status(raw: str | None) -> Status:
    val = (raw or "active").strip().lower()
    if val not in {"active", "deprecated", "retired"}:
        return "active"
    return val  # type: ignore[return-value]


def _from_dict(data: dict[str, Any]) -> AgentRecord:
    return AgentRecord(
        name=str(data.get("name") or "").strip(),
        owner=str(data.get("owner") or "unassigned"),
        created_at=str(data.get("created_at") or _iso()),
        last_run_at=data.get("last_run_at"),
        ttl_days=int(data.get("ttl_days") or 90),
        status=_parse_status(str(data.get("status") or "active")),
        latest_eval_score=(
            float(data["latest_eval_score"])
            if data.get("latest_eval_score") is not None
            else None
        ),
        eval_threshold=float(data.get("eval_threshold") or 0.8),
        credentials_revoked=bool(data.get("credentials_revoked", False)),
        notes=list(data.get("notes") or []),
    )


def _load_seed() -> dict[str, AgentRecord]:
    path = seed_path()
    if not path.is_file():
        raise RegistryLoadError(f"registry seed not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryLoadError(f"registry seed load failed: {exc}") from exc
    default_ttl = int(raw.get("default_ttl_days") or 90)
    default_thresh = float(raw.get("default_eval_threshold") or 0.8)
    agents: dict[str, AgentRecord] = {}
    for row in raw.get("agents") or []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        row = {
            "ttl_days": default_ttl,
            "eval_threshold": default_thresh,
            "created_at": _iso(),
            **row,
        }
        rec = _from_dict(row)
        if rec.name:
            agents[rec.name] = rec
    if not agents:
        raise RegistryLoadError("registry seed has no agents")
    return agents


def _read_state() -> dict[str, AgentRecord] | None:
    path = state_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryLoadError(f"registry state corrupt: {exc}") from exc
    agents: dict[str, AgentRecord] = {}
    for row in payload.get("agents") or []:
        if isinstance(row, dict) and row.get("name"):
            agents[str(row["name"])] = _from_dict(row)
    return agents or None


def _write_state(agents: dict[str, AgentRecord]) -> None:
    path = state_path()
    payload = {
        "updated_at": _iso(),
        "agents": [a.to_dict() for a in sorted(agents.values(), key=lambda r: r.name)],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_registry(*, refresh: bool = False) -> dict[str, AgentRecord]:
    """Merge seed + durable state. Fail closed on errors."""
    with _LOCK:
        seed = _load_seed()
        try:
            state = None if refresh else _read_state()
        except RegistryLoadError:
            raise
        if state is None:
            _write_state(seed)
            return deepcopy(seed)
        # Seed wins for static fields if new agents appear; state wins for runtime fields
        merged: dict[str, AgentRecord] = deepcopy(seed)
        for name, rec in state.items():
            if name in merged:
                base = merged[name]
                base.last_run_at = rec.last_run_at or base.last_run_at
                base.status = rec.status
                base.latest_eval_score = (
                    rec.latest_eval_score
                    if rec.latest_eval_score is not None
                    else base.latest_eval_score
                )
                base.credentials_revoked = rec.credentials_revoked
                base.notes = list(rec.notes or base.notes)
                base.created_at = rec.created_at or base.created_at
                # Prefer seed ttl/threshold/owner unless state explicitly set notes
                base.ttl_days = seed[name].ttl_days
                base.eval_threshold = seed[name].eval_threshold
                base.owner = seed[name].owner
            else:
                merged[name] = rec
        return merged


def save_registry(agents: dict[str, AgentRecord]) -> None:
    with _LOCK:
        _write_state(agents)


def get_agent(name: str) -> AgentRecord | None:
    name = (name or "").strip()
    if not name:
        return None
    try:
        return load_registry().get(name)
    except RegistryLoadError:
        return None


def is_invocation_allowed(agent_name: str) -> tuple[bool, str]:
    """Fail closed: missing registry / unknown / retired → deny."""
    try:
        agents = load_registry()
    except RegistryLoadError as exc:
        return False, f"registry_unavailable:{exc}"
    rec = agents.get((agent_name or "").strip())
    if rec is None:
        return False, "unknown_agent"
    if rec.status == "retired" or rec.credentials_revoked:
        return False, "agent_retired"
    return True, rec.status


def touch_last_run(agent_name: str) -> AgentRecord | None:
    """Update last_run_at after a successful agent invocation."""
    name = (agent_name or "").strip()
    if not name:
        return None
    with _LOCK:
        try:
            agents = load_registry()
        except RegistryLoadError:
            return None
        rec = agents.get(name)
        if rec is None or rec.status == "retired":
            return rec
        rec.last_run_at = _iso()
        agents[name] = rec
        _write_state(agents)
        append_audit(
            event="agent_run",
            agent=name,
            decision="touch",
            reason="last_run_at",
            extra={"last_run_at": rec.last_run_at},
        )
        return rec


def revoke_grants(agent_name: str, *, reason: str) -> None:
    """Clear RBAC allowlist and mark credentials revoked."""
    from finance_ops.governance import rbac

    name = (agent_name or "").strip()
    with _LOCK:
        rbac.AGENT_TOOL_POLICY[name] = frozenset()
        agents = load_registry()
        rec = agents.get(name)
        if rec is None:
            return
        rec.credentials_revoked = True
        rec.notes = list(rec.notes or []) + [reason]
        agents[name] = rec
        _write_state(agents)
        append_audit(
            event="lifecycle",
            agent=name,
            decision="revoke_grants",
            reason=reason,
        )


def set_status(agent_name: str, status: Status, *, reason: str) -> AgentRecord | None:
    name = (agent_name or "").strip()
    with _LOCK:
        agents = load_registry()
        rec = agents.get(name)
        if rec is None:
            return None
        prev = rec.status
        rec.status = status
        rec.notes = list(rec.notes or []) + [f"{prev}->{status}:{reason}"]
        agents[name] = rec
        _write_state(agents)
        append_audit(
            event="lifecycle",
            agent=name,
            decision=status,
            reason=reason,
            extra={"from": prev},
        )
        if status == "retired":
            revoke_grants(name, reason=f"retired:{reason}")
        return rec


def set_eval_score(agent_name: str, score: float) -> AgentRecord | None:
    name = (agent_name or "").strip()
    with _LOCK:
        agents = load_registry()
        rec = agents.get(name)
        if rec is None:
            return None
        rec.latest_eval_score = float(score)
        agents[name] = rec
        _write_state(agents)
        return rec


def evaluate_lifecycle(rec: AgentRecord, *, now: datetime | None = None) -> Status:
    """Pure lifecycle check — does not mutate. Retire > deprecate > keep."""
    now = now or _now()
    # Eval-based deprecation (retired wins if also stale)
    eval_hit = (
        rec.latest_eval_score is not None
        and float(rec.latest_eval_score) < float(rec.eval_threshold)
    )
    # TTL based on last_run_at (or created_at if never run)
    anchor_raw = rec.last_run_at or rec.created_at
    stale = False
    if anchor_raw:
        try:
            anchor = datetime.fromisoformat(anchor_raw)
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)
            stale = now - anchor > timedelta(days=int(rec.ttl_days))
        except ValueError:
            stale = True
    if rec.status == "retired":
        return "retired"
    if stale:
        return "retired"
    if eval_hit:
        return "deprecated"
    return rec.status if rec.status in {"active", "deprecated"} else "active"


def sweep_lifecycle(*, now: datetime | None = None) -> dict[str, Any]:
    """Apply TTL/eval rules; retire + revoke as needed. Safe for Cloud Scheduler."""
    now = now or _now()
    transitions: list[dict[str, Any]] = []
    with _LOCK:
        try:
            agents = load_registry()
        except RegistryLoadError as exc:
            append_audit(
                event="lifecycle_sweep",
                agent="registry",
                decision="deny",
                reason=f"registry_unavailable:{exc}",
            )
            return {
                "status": "error",
                "error": str(exc),
                "transitions": [],
                "needs_review": True,
            }
        for name, rec in list(agents.items()):
            target = evaluate_lifecycle(rec, now=now)
            if target == rec.status:
                continue
            prev = rec.status
            rec.status = target
            rec.notes = list(rec.notes or []) + [f"sweep:{prev}->{target}"]
            agents[name] = rec
            transitions.append(
                {"agent": name, "from": prev, "to": target, "ttl_days": rec.ttl_days}
            )
            append_audit(
                event="lifecycle",
                agent=name,
                decision=target,
                reason="sweep",
                extra={"from": prev},
            )
            if target == "retired":
                # revoke inside lock without re-entering load
                from finance_ops.governance import rbac

                rbac.AGENT_TOOL_POLICY[name] = frozenset()
                rec.credentials_revoked = True
                agents[name] = rec
        _write_state(agents)
    append_audit(
        event="lifecycle_sweep",
        agent="registry",
        decision="ok",
        reason=f"transitions:{len(transitions)}",
        extra={"count": len(transitions)},
    )
    return {
        "status": "success",
        "transitions": transitions,
        "count": len(transitions),
        "agents": [a.to_dict() for a in load_registry().values()],
        "needs_review": False,
    }


def list_agents() -> list[dict[str, Any]]:
    return [a.to_dict() for a in sorted(load_registry().values(), key=lambda r: r.name)]
