# ResearchPilot Architecture

ResearchPilot is an **AI research agent workflow** for China A-share industry and company research — not a one-shot report generator.

## Core philosophy

```
Query → Analyze → Plan → Search → Read → Evaluate → Synthesize → Write
```

Each stage has a single owner. UI entry points are `studio_app.py` (the custom
research workspace), `agent_app.py` (the original conversational workbench) and
`app.py` (the sequential pipeline). Research logic lives under `src/`.

Studio embeds a local HTML/CSS/JavaScript component and translates explicit user
intents through `src/studio_bridge.py`. Read-only packets contain existing report
versions, their own evidence snapshots, messages and task status. Commands reuse
the existing Runner; financial screening reuses the deterministic calculation
modules. Full stock/import/review tools remain in the native Workbench UI. See
[Studio implementation and verification](STUDIO_INTERFACE_2026-10-14.md).

## Components

| Component | Module | Responsibility |
| --- | --- | --- |
| **QueryAnalyzer** | `src/query_analyzer.py` | Classify query as industry / company / technology-theme |
| **Planner** | `src/planner.py` | Build an A-share `ResearchPlan` with per-task search queries |
| **Searcher** | `src/searcher.py` | Discover candidate `Source` metadata (coverage-aware) |
| **Reader** | `src/reader.py` | Extract `EvidenceDocument` content from sources |
| **EvidenceEvaluator** | `src/evaluator.py` | Score evidence; retain coverage across research tasks |
| **Synthesizer** | `src/synthesizer.py` | Produce a grounded `SynthesisBrief` with excerpts |
| **Writer** | `src/writer.py` | Format the brief into a Chinese `ResearchReport` |
| **Pipeline** | `src/pipeline.py` | Orchestrate stages end-to-end |

Shared types live in `src/models.py`. See also [query_analyzer.md](query_analyzer.md).

## Data flow

```
user query + depth
    → QueryAnalyzer  → AnalyzedQuery
    → Planner        → ResearchPlan
    → Searcher       → list[Source]
    → Reader         → list[EvidenceDocument]
    → Evaluator      → list[EvaluatedEvidence]  (keep flags = coverage retention)
    → Synthesizer    → SynthesisBrief
    → Writer         → ResearchReport
    → ResearchResult
```

Internal diagnostics (`*_diagnostics` on `ResearchResult`) remain available for debugging; they are not shown in the normal Streamlit UI.

## V1 status

| Stage | Status |
| --- | --- |
| QueryAnalyzer | Rule-based |
| Planner | OpenAI (`OPENAI_API_KEY`, `LLM_MODEL`) with rule fallback |
| Searcher | Tavily (`TAVILY_API_KEY`) with mock fallback |
| Reader | Live HTML via requests + BeautifulSoup (snippet fallback) |
| EvidenceEvaluator | Rule-based scores + coverage-aware retention |
| Synthesizer | OpenAI grounded findings (safe empty/gap fallback) |
| Writer | OpenAI report from SynthesisBrief only (deterministic fallback) |

## Environment variables

See `.env.example`:

- `TAVILY_API_KEY` — Searcher
- `OPENAI_API_KEY` — Planner, Synthesizer, Writer
- `LLM_MODEL` — optional (default `gpt-4o-mini`)

## Design rules

1. One responsibility per module — Writer must not search; Searcher must not write.
2. Pipeline is the only place that knows stage order.
3. Prefer typed dataclasses over ad-hoc dicts between stages.
4. Fallbacks must not invent companies, figures, or market events.
5. Citations (`[E#]`) must map to real retained evidence URLs.
