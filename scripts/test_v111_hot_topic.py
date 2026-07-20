"""v1.1.1 hot-topic allocation checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.env import load_env
from src.models import ResearchDepth
from src.pipeline import run_research


def _summary(topic: str) -> dict:
    result = run_research(topic, ResearchDepth.QUICK)
    eval_diag = result.evaluator_diagnostics or {}
    profiles = eval_diag.get("retained_freshness_profiles") or {}
    total = max(int(eval_diag.get("retained_total") or 0), 1)
    gaps = [
        g.finding for g in (result.synthesis.evidence_gaps if result.synthesis else [])
    ]
    alloc = eval_diag.get("allocation_counts") or profiles
    structural = int(
        eval_diag.get("structural_background")
        if eval_diag.get("structural_background") is not None
        else alloc.get("STRUCTURAL", 0)
    )
    br_total = int(
        eval_diag.get("breaking_recent_total")
        if eval_diag.get("breaking_recent_total") is not None
        else (int(alloc.get("BREAKING", 0)) + int(alloc.get("RECENT", 0)))
    )
    br_pct = float(
        eval_diag.get("breaking_recent_pct")
        if eval_diag.get("breaking_recent_pct") is not None
        else round(100.0 * br_total / total, 1)
    )
    return {
        "topic": topic,
        "time_sensitive": bool(getattr(result.plan, "time_sensitive", False)),
        "retention_mode": eval_diag.get("retention_mode"),
        "profiles": profiles,
        "planner_profiles": eval_diag.get("retained_planner_profiles"),
        "allocation_counts": eval_diag.get("allocation_counts"),
        "allocation_roles": eval_diag.get("allocation_roles"),
        "breaking_recent_total": br_total,
        "breaking_recent_pct": br_pct,
        "structural_background": structural,
        "current": int(alloc.get("CURRENT", 0)),
        "age_buckets": eval_diag.get("retained_age_buckets"),
        "recent_catalyst_insufficient": eval_diag.get("recent_catalyst_insufficient"),
        "evidence_gaps": gaps,
        "retained_total": eval_diag.get("retained_total"),
    }


def main() -> int:
    load_env(override=True)
    hot = _summary("今天商业航天为什么涨")
    normal = _summary("商业航天产业链")

    print("=" * 60)
    print("HOT:", json.dumps(hot, ensure_ascii=False, indent=2))
    print("=" * 60)
    print("NORMAL:", json.dumps(normal, ensure_ascii=False, indent=2))

    assert hot["time_sensitive"] is True
    assert hot["retention_mode"] == "time_sensitive"
    assert hot["structural_background"] <= 2
    assert hot["breaking_recent_pct"] >= 50 or hot["recent_catalyst_insufficient"]

    assert normal["time_sensitive"] is False
    assert normal["retention_mode"] == "balanced"

    out = Path(__file__).with_name("_v111_hot_topic.json")
    out.write_text(
        json.dumps({"hot": hot, "normal": normal}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote", out)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
