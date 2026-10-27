"""#8 Async HITL approval gate — serialize pending decisions and resume later."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from data_plane.config import WAREHOUSE_DIR, ensure_dirs


class PendingApproval(BaseModel):
    approval_id: str
    kind: str = "invoice_post"
    amount: float
    currency: str = "USD"
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "approved", "rejected", "expired"] = "pending"
    created_at: str
    expires_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    resume_token: str


class ApprovalStore:
    def __init__(self, root: Path | None = None) -> None:
        ensure_dirs()
        self.root = root or (WAREHOUSE_DIR / "hitl")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, approval_id: str) -> Path:
        return self.root / f"{approval_id}.json"

    def create(
        self,
        *,
        kind: str,
        amount: float,
        summary: str,
        payload: dict[str, Any] | None = None,
        currency: str = "USD",
        wait_days: float = 3.0,
    ) -> PendingApproval:
        now = datetime.now(timezone.utc)
        approval = PendingApproval(
            approval_id=f"APPR-{uuid.uuid4().hex[:10]}",
            kind=kind,
            amount=amount,
            currency=currency,
            summary=summary,
            payload=payload or {},
            created_at=now.isoformat(),
            expires_at=(now + timedelta(days=wait_days)).isoformat(),
            resume_token=uuid.uuid4().hex,
        )
        self._path(approval.approval_id).write_text(
            approval.model_dump_json(indent=2), encoding="utf-8"
        )
        return approval

    def get(self, approval_id: str) -> PendingApproval | None:
        path = self._path(approval_id)
        if not path.exists():
            return None
        return PendingApproval.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self, status: str | None = "pending") -> list[PendingApproval]:
        items: list[PendingApproval] = []
        for path in sorted(self.root.glob("APPR-*.json")):
            item = PendingApproval.model_validate_json(path.read_text(encoding="utf-8"))
            if status is None or item.status == status:
                items.append(item)
        return items

    def decide(
        self,
        approval_id: str,
        *,
        decision: Literal["approved", "rejected"],
        actor: str = "human",
        resume_token: str | None = None,
    ) -> PendingApproval:
        item = self.get(approval_id)
        if item is None:
            raise KeyError(approval_id)
        if resume_token and resume_token != item.resume_token:
            raise PermissionError("invalid resume_token")
        expires = datetime.fromisoformat(item.expires_at)
        if datetime.now(timezone.utc) > expires and item.status == "pending":
            item.status = "expired"
            self._save(item)
            raise TimeoutError("approval expired")
        if item.status != "pending":
            raise RuntimeError(f"approval not pending: {item.status}")
        item.status = decision
        item.decided_at = datetime.now(timezone.utc).isoformat()
        item.decided_by = actor
        self._save(item)
        return item

    def _save(self, item: PendingApproval) -> None:
        self._path(item.approval_id).write_text(
            item.model_dump_json(indent=2), encoding="utf-8"
        )


DEFAULT_STORE = ApprovalStore()
