# ResearchPilot

**ResearchPilot** is an AI research agent for China A-share industry and company analysis.

Enter a topic — such as `PCB产业链`, `卫星通信`, or `宁德时代` — and ResearchPilot plans the research, searches the web, reads sources, evaluates evidence, synthesizes grounded findings, and writes a cited Chinese research report.

**Version:** 1.0.0

## Key features

- Query classification: industry / company / technology-theme
- LLM research planning with A-share methodology (产业链、供需、催化、标的映射)
- Multi-query web search via Tavily, with per-task coverage
- Live page reading with snippet fallback
- Rule-based evidence scoring + coverage-aware retention
- Evidence-grounded synthesis with verbatim excerpts and `[E#]` citations
- LLM report writing that uses only the SynthesisBrief (no invented facts)
- Streamlit progressive agent UI

## Architecture

```
Query → Analyze → Plan → Search → Read → Evaluate → Synthesize → Write
```

| Component | Module | Role |
| --- | --- | --- |
| QueryAnalyzer | `src/query_analyzer.py` | Classify and normalize the user query |
| Planner | `src/planner.py` | OpenAI A-share research plan + search queries |
| Searcher | `src/searcher.py` | Tavily multi-query search (mock fallback) |
| Reader | `src/reader.py` | Fetch/extract page text (snippet fallback) |
| EvidenceEvaluator | `src/evaluator.py` | Score evidence; retain coverage across tasks |
| Synthesizer | `src/synthesizer.py` | Grounded findings + supporting excerpts |
| Writer | `src/writer.py` | Chinese A-share report from the brief only |
| Pipeline | `src/pipeline.py` | End-to-end orchestration |

Shared types live in `src/models.py`. See [docs/architecture.md](docs/architecture.md).

## Research workflow

1. **Analyze** — detect industry vs company vs theme
2. **Plan** — build objective, strategy, and per-task search queries
3. **Search** — execute Planner queries; balance candidates across tasks
4. **Read** — extract page content where possible
5. **Evaluate** — score credibility / relevance / recency; keep 1–2 sources per task
6. **Synthesize** — emit structured findings with evidence IDs and verbatim excerpts
7. **Write** — compose the final Chinese report with inline citations and Sources

## Tech stack

- Python 3.10+
- Streamlit
- OpenAI Chat Completions API (`gpt-4o-mini` by default)
- Tavily Search API
- requests + BeautifulSoup4
- python-dotenv

## Installation and setup

```bash
python -m venv .venv
```

**Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add your keys (never commit `.env`).

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Yes (for LLM stages) | Planner, Synthesizer, Writer |
| `TAVILY_API_KEY` | Yes (for live search) | Searcher |
| `LLM_MODEL` | No | Defaults to `gpt-4o-mini` |

Without keys, stages fall back safely (rules / mock / brief formatting) and **do not invent research facts**.

## How to run

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501), enter a topic, choose depth (Quick / Standard / Deep), and start research.

Programmatic entry point:

```python
from src.models import ResearchDepth
from src.pipeline import run_research

result = run_research("卫星通信", ResearchDepth.QUICK)
print(result.report.sections[0].title)
```

## Example use cases

| Query | Type | Focus |
| --- | --- | --- |
| `PCB产业链` | Industry | 上中下游、供需、A股标的 |
| `卫星通信` | Industry / theme | 产业链、技术、催化、风险 |
| `宁德时代` | Company | 公司基本面、竞争、催化、风险 |
| `液冷服务器` | Technology / theme | 技术路径、产业链映射 |

## Evidence-grounding design

ResearchPilot separates **finding** from **writing**:

1. Synthesizer may only claim facts supported by retrieved evidence.
2. Each finding carries `finding_type` (`supported_fact` | `inference`), `evidence_ids`, and `supporting_excerpts`.
3. Excerpts must be **verbatim** substrings of evidence text (validated in code).
4. Insufficient sections stay empty; gaps go to `evidence_gaps` (no fake “insufficient” facts).
5. Writer may only reorganize the SynthesisBrief — it must not add companies, figures, dates, or catalysts absent from the brief.
6. Final reports cite sources inline as `[E1]` and list them under **Sources**.

## Current V1 limitations

- QueryAnalyzer is rule-based (not LLM).
- EvidenceEvaluator scoring is heuristic (not LLM).
- Some sites block scraping (403/JS/PDF); Reader may fall back to snippets.
- Synthesis quality depends on search/read coverage; thin evidence → more gaps.
- Offline/mock search uses generic templates only when Tavily is unavailable.
- No authentication, persistence, or multi-user collaboration yet.
- Chinese A-share focus; global-market framing is intentionally secondary.

## Project structure

```
app.py                  # Streamlit UI
requirements.txt
.env.example            # Placeholder env vars only
src/
  __init__.py
  models.py             # Shared dataclasses
  env.py                # dotenv loading
  query_analyzer.py
  planner.py
  searcher.py
  reader.py
  evaluator.py
  evidence_coverage.py  # Per-task retention targets
  synthesizer.py
  writer.py
  pipeline.py
scripts/                # Dev / smoke helpers (optional)
docs/
  architecture.md
  query_analyzer.md
data/                   # Local storage (gitignored contents)
```

## License

Private — all rights reserved.
