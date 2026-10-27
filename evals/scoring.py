from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CaseScore:
    case_id: str
    passed: bool
    mention_score: float
    evidence_score: float
    review_score: float
    agent_score: float
    overall: float
    missing_mentions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    final_text_excerpt: str = ""
    agents_seen: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize(text: str) -> str:
    return text.lower()


def score_case(
    *,
    case_id: str,
    expect: dict[str, Any],
    final_text: str,
    agents_seen: list[str],
    tools_called: list[str],
    require_evidence_id: bool = True,
) -> CaseScore:
    """Deterministic L2 scorer for finance_ops trajectories."""
    notes: list[str] = []
    text_l = _normalize(final_text or "")

    must_mention = list(expect.get("must_mention") or [])
    found = [m for m in must_mention if _normalize(m) in text_l]
    missing = [m for m in must_mention if m not in found]
    mention_score = (len(found) / len(must_mention)) if must_mention else 1.0
    if missing:
        notes.append(f"missing mentions: {missing}")

    has_evidence = "evidence_id" in text_l or "evd-" in text_l
    if require_evidence_id:
        evidence_score = 1.0 if has_evidence else 0.0
        if not has_evidence:
            notes.append("no evidence_id cited in final answer")
    else:
        evidence_score = 1.0

    expected_review = expect.get("needs_review")
    if expected_review is True:
        review_ok = (
            "needs_review" in text_l
            or "human review" in text_l
            or "flag_for_human_review" in tools_called
            or any("review" in t for t in tools_called)
        )
        review_score = 1.0 if review_ok else 0.0
        if not review_ok:
            notes.append("expected needs_review / human-review signal")
    elif expected_review is False:
        review_score = 0.0 if "needs_review" in text_l else 1.0
    else:
        review_score = 1.0

    preferred = expect.get("preferred_agent")
    if preferred:
        # Coordinator may answer directly; prefer specialist presence when expected.
        if preferred in agents_seen:
            agent_score = 1.0
        elif preferred == "finance_ops_coordinator" and (
            not agents_seen or "finance_ops_coordinator" in agents_seen
        ):
            agent_score = 1.0
        elif agents_seen:
            agent_score = 0.0
            notes.append(
                f"preferred agent {preferred} not seen; saw {agents_seen}"
            )
        else:
            agent_score = 0.5
            notes.append("no agent author metadata on events; partial credit")
    else:
        agent_score = 1.0

    # Governance RBAC: out-of-scope tools must never appear in the trajectory.
    forbidden = [str(t) for t in (expect.get("forbidden_tools") or [])]
    violations = [t for t in forbidden if t in tools_called]
    rbac_ok = not violations
    if violations:
        notes.append(f"forbidden tools called: {violations}")

    # Weighted overall: mentions matter most for finance accuracy.
    overall = (
        0.45 * mention_score
        + 0.25 * evidence_score
        + 0.15 * review_score
        + 0.15 * agent_score
    )
    if not rbac_ok:
        overall = min(overall, 0.4)
    passed = (
        overall >= 0.75
        and mention_score >= 0.67
        and evidence_score >= 1.0
        and (expected_review is not True or review_score >= 1.0)
        and rbac_ok
    )

    return CaseScore(
        case_id=case_id,
        passed=passed,
        mention_score=round(mention_score, 3),
        evidence_score=round(evidence_score, 3),
        review_score=round(review_score, 3),
        agent_score=round(agent_score, 3),
        overall=round(overall, 3),
        missing_mentions=missing,
        notes=notes,
        final_text_excerpt=(final_text or "")[:500],
        agents_seen=agents_seen,
        tools_called=tools_called,
    )


def summarize_scores(scores: list[CaseScore]) -> dict[str, Any]:
    if not scores:
        return {
            "case_count": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "avg_overall": 0.0,
        }
    passed = sum(1 for s in scores if s.passed)
    avg = sum(s.overall for s in scores) / len(scores)
    return {
        "case_count": len(scores),
        "passed": passed,
        "failed": len(scores) - passed,
        "pass_rate": round(passed / len(scores), 3),
        "avg_overall": round(avg, 3),
    }
