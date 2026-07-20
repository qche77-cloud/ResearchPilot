"""Focused v1.1.2 Reader Reliability unit tests (A–E).

Run:
  python scripts/test_v112_reader_reliability.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.domain_penalty import (
    DEFAULT_DOMAIN_PENALTIES,
    apply_relevance_penalty,
    load_domain_penalties,
)
from src.models import (
    EvidenceDocument,
    EvaluatedEvidence,
    ResearchDepth,
    ResearchPlan,
    ResearchPlanStep,
    Source,
)
from src.pipeline import _MAX_REPLACEMENTS_PER_TASK, _apply_reader_replacements
from src.reader import Reader, REPLACEABLE_EXTRACTION_STATUSES
from src.searcher import Searcher, _balance_sources_across_tasks, _source_rank_key
from src.synthesizer import _build_supporting_excerpts, _find_verbatim_excerpt


def _make_text_pdf(text: str) -> bytes:
    """Build a minimal one-page text PDF for extraction tests."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 50 700 Td ({safe}) Tj ET".encode("latin-1", errors="replace")
    objects = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("ascii")
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n"
    )
    xref_positions = []
    out = bytearray(b"%PDF-1.4\n")
    for obj in objects:
        xref_positions.append(len(out))
        out.extend(obj)
    xref_start = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for pos in xref_positions:
        out.extend(f"{pos:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer<< /Size {len(objects)+1} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def test_a_text_pdf_extraction() -> None:
    reader = Reader()
    payload = _make_text_pdf("Satellite communications market outlook 2026 A-share")
    text = reader._extract_pdf_text(payload)
    assert "Satellite" in text or "communications" in text or "market" in text, text
    assert len(text) >= 20
    print("PASS A: text-based PDF extraction")


def test_b_failed_html_replacement_search() -> None:
    plan = ResearchPlan(
        topic="PCB",
        depth=ResearchDepth.QUICK,
        steps=[ResearchPlanStep(1, "产业链", "desc", ["PCB 产业链"])],
    )
    failed = Source(
        title="Blocked page",
        url="https://zhuanlan.zhihu.com/p/123",
        snippet="snippet about PCB",
        source_type="web",
        relevance=0.9,
        research_task="产业链",
        source_id="S1",
    )
    docs = [
        EvidenceDocument(
            source=failed,
            extracted_text=failed.snippet,
            word_count=3,
            read_status="fallback",
            error_message="403",
            extraction_status="HTTP_403",
            snippet_fallback=True,
        )
    ]
    replacement = Source(
        title="Good PCB article",
        url="https://finance.sina.com.cn/pcb-good",
        snippet="readable pcb content " * 20,
        source_type="web",
        relevance=0.8,
        research_task="产业链",
        source_id="S2",
    )

    class FakeSearcher(Searcher):
        def find_replacement_source(self, **kwargs):  # type: ignore[no-untyped-def]
            return replacement, "PCB 产业链 Blocked page"

    class FakeReader(Reader):
        def _read_one(self, source: Source) -> EvidenceDocument:
            return EvidenceDocument(
                source=source,
                extracted_text=("PCB industry chain analysis. " * 40).strip(),
                word_count=80,
                read_status="success",
                extraction_status="FULL_TEXT",
                snippet_fallback=False,
                extracted_char_count=400,
            )

    new_docs, new_sources, diag = _apply_reader_replacements(
        plan=plan,
        searcher=FakeSearcher(),
        reader=FakeReader(),
        sources=[failed],
        documents=docs,
    )
    assert diag["success_count"] == 1
    assert new_docs[0].extraction_status == "FULL_TEXT"
    assert "sina.com.cn" in new_sources[0].url
    print("PASS B: failed HTML → replacement search")


def test_c_replacement_recursion_blocked() -> None:
    plan = ResearchPlan(
        topic="PCB",
        depth=ResearchDepth.QUICK,
        steps=[ResearchPlanStep(1, "产业链", "desc", ["PCB"])],
    )
    # Two failures in same task — only 2 replacements max; a third would be skipped.
    # Also: replacement that itself fails must not trigger another replacement.
    sources = []
    docs = []
    for i in range(3):
        s = Source(
            title=f"Fail {i}",
            url=f"https://zhuanlan.zhihu.com/p/{i}",
            snippet="x",
            source_type="web",
            relevance=0.5,
            research_task="产业链",
            source_id=f"S{i+1}",
        )
        sources.append(s)
        docs.append(
            EvidenceDocument(
                source=s,
                extracted_text="x",
                word_count=1,
                read_status="fallback",
                extraction_status="HTTP_403",
                error_message="403",
                snippet_fallback=True,
            )
        )

    calls = {"n": 0}

    class CountingSearcher(Searcher):
        def find_replacement_source(self, **kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            n = calls["n"]
            return (
                Source(
                    title=f"Rep {n}",
                    url=f"https://example.org/r{n}",
                    snippet="y",
                    source_type="web",
                    relevance=0.5,
                    research_task="产业链",
                    source_id=f"R{n}",
                ),
                f"q{n}",
            )

    class AlwaysFailReader(Reader):
        def _read_one(self, source: Source) -> EvidenceDocument:
            return EvidenceDocument(
                source=source,
                extracted_text="y",
                word_count=1,
                read_status="fallback",
                extraction_status="EMPTY_CONTENT",
                error_message="empty",
                snippet_fallback=True,
            )

    _, _, diag = _apply_reader_replacements(
        plan=plan,
        searcher=CountingSearcher(),
        reader=AlwaysFailReader(),
        sources=list(sources),
        documents=list(docs),
    )
    # Max 2 replacements per task; third original skipped by limit.
    assert calls["n"] == _MAX_REPLACEMENTS_PER_TASK
    assert diag["attempt_count"] == 3  # 2 attempts + 1 skipped
    skipped = [a for a in diag["attempts"] if a.get("skipped_reason") == "per_task_limit"]
    assert len(skipped) == 1
    # No recursive second pass: failed replacements are not re-queued.
    assert diag["success_count"] == 0
    print("PASS C: replacement recursion / per-task limit blocked")


def test_d_domain_penalty_not_ban() -> None:
    penalties = dict(DEFAULT_DOMAIN_PENALTIES)
    good = Source(
        title="good",
        url="https://finance.sina.com.cn/a",
        snippet="s",
        source_type="web",
        relevance=0.70,
        research_task="t1",
    )
    bad = Source(
        title="zhihu",
        url="https://zhuanlan.zhihu.com/p/1",
        snippet="s",
        source_type="web",
        relevance=0.95,
        research_task="t1",
    )
    adj, matched, applied = apply_relevance_penalty(bad.relevance, bad.url, penalties=penalties)
    assert applied and matched == "zhuanlan.zhihu.com"
    assert adj < bad.relevance

    # Without penalty, zhihu would rank first; with penalty, sina can win.
    ranked = sorted(
        [good, bad],
        key=lambda s: _source_rank_key(s, penalties=penalties),
        reverse=True,
    )
    assert ranked[0].url == good.url

    # Soft penalty never drops the domain from the candidate pool entirely when
    # it is the only source for a task.
    only_bad = _balance_sources_across_tasks(
        [bad],
        limit=2,
        per_task_target=2,
        penalties=penalties,
    )
    assert len(only_bad) == 1
    assert "zhihu" in only_bad[0].url
    assert load_domain_penalties()  # defaults present
    print("PASS D: hard-fail domain penalized but not banned")


def test_e_grounding_validation_still_passes() -> None:
    source_text = "卫星通信产业链包括上游制造与下游运营环节，2026年需求持续增长。"
    excerpt = "卫星通信产业链包括上游制造与下游运营环节"
    found = _find_verbatim_excerpt(source_text, excerpt)
    assert found is not None
    compact_src = "".join(source_text.split())
    compact_ex = "".join(found.split())
    assert compact_ex in compact_src

    from src.synthesizer import _build_supporting_excerpts

    doc = EvidenceDocument(
        source=Source(
            title="t",
            url="https://example.com/x",
            snippet=source_text,
            source_type="web",
            relevance=0.9,
        ),
        extracted_text=source_text,
        word_count=10,
        read_status="success",
        extraction_status="FULL_TEXT",
    )
    item = EvaluatedEvidence(
        document=doc,
        credibility_score=80,
        relevance_score=80,
        recency_score=70,
        final_score=80,
        evaluation_reason="ok",
        keep=True,
    )
    evidence_map = {"E1": item}
    excerpts = _build_supporting_excerpts(
        finding_text="卫星通信产业链包括上游制造",
        evidence_ids=["E1"],
        evidence_index=evidence_map,
        candidate_excerpts=[{"evidence_id": "E1", "excerpt": excerpt}],
    )
    assert excerpts, "grounding must still produce verified excerpts"
    assert REPLACEABLE_EXTRACTION_STATUSES  # module import smoke
    print("PASS E: existing grounding validation still passes")


def main() -> int:
    test_a_text_pdf_extraction()
    test_b_failed_html_replacement_search()
    test_c_replacement_recursion_blocked()
    test_d_domain_penalty_not_ban()
    test_e_grounding_validation_still_passes()
    print("\nAll focused v1.1.2 Reader Reliability tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
