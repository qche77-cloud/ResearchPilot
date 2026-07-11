"""Test LLM Writer on 卫星通信 — grounded brief → Chinese A-share report."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.env import load_env
from src.models import ResearchDepth
from src.pipeline import run_research

BANNED = ("Alpha Corp", "NovaTech", "Beta Industries", "Example Corp")


def main() -> None:
    load_env(override=True)
    result = run_research("卫星通信", ResearchDepth.QUICK)
    report = result.report
    synthesis = result.synthesis
    diag = result.writer_diagnostics or {}

    print("writer_source:", diag.get("writer_source") or report.writer_source)
    print("warning:", result.writer_warning)
    print("grounded_findings_received:", diag.get("grounded_findings_received"))
    print("evidence_sources_cited:", diag.get("evidence_sources_cited"))
    print("sections:", [s.title for s in report.sections])
    print("=" * 60)

    full_text = "\n\n".join(f"## {s.title}\n{s.content}" for s in report.sections)
    print(full_text[:4000])
    if len(full_text) > 4000:
        print("\n...[truncated]...\n")

    # Acceptance checks
    assert report.sections, "report must have sections"
    assert any(s.title == "Sources" for s in report.sections), "Sources required"
    for banned in BANNED:
        assert banned not in full_text, f"fictional company leaked: {banned}"

    valid_ids = set((synthesis.evidence_index or {}).keys()) if synthesis else set()
    cited = set(re.findall(r"\[(E\d+)\]", full_text, flags=re.IGNORECASE))
    cited = {c.upper() for c in cited}
    for eid in cited:
        assert eid in valid_ids, f"citation {eid} not in evidence index"

    sources = next(s for s in report.sections if s.title == "Sources")
    for eid in sorted(valid_ids):
        assert f"[{eid}]" in sources.content, f"Sources missing {eid}"
        item = synthesis.evidence_index[eid]
        assert item.source.url in sources.content
        # Title may be truncated in rare cases; at least URL must map.
        assert "http" in sources.content

    # No empty forced English mock sections / gap placeholders in content sections
    content_titles = {
        "核心结论",
        "行业/主题概览",
        "产业链拆解",
        "供需驱动",
        "技术趋势",
        "近期催化",
        "A股相关公司",
        "风险与不确定性",
    }
    gap_markers = ("缺少可核验", "缺少可用于", "缺少供需", "证据不足", "Evidence is insufficient")
    for s in report.sections:
        assert s.title != "Executive Summary"
        assert s.content.strip(), f"empty section: {s.title}"
        if s.title in content_titles:
            for marker in gap_markers:
                assert marker not in s.content, f"gap placeholder in {s.title}: {marker}"

    assert diag.get("writer_source") in {"llm", "fallback"}
    assert "grounded_findings_received" in diag
    assert "evidence_sources_cited" in diag

    out = Path(__file__).with_name("_writer_satcom.json")
    payload = {
        "diagnostics": diag,
        "writer_warning": result.writer_warning,
        "sections": [{"title": s.title, "content": s.content} for s in report.sections],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)
    print("OK")


if __name__ == "__main__":
    main()
