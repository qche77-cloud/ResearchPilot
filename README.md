# ResearchPilot

## v2.0 core capabilities — development build

New usable features are integrated into the existing application:

- **Financial tools**: multi-period revenue/profit/cash-flow data, deterministic
  YoY, cumulative-to-quarter conversion, QoQ, gross margin, expense/net margin,
  TTM and basic PE/PB. Explicit reporting scope, currency, units, periods and
  sources are required. Missing/ambiguous inputs are blocked, never guessed.
- **Traceable charts**: each financial point exposes record IDs, exact values,
  source links and update times; calculations export their formulas and inputs.
- **Hypotheses and reflection**: record supporting data, opposing data, unresolved
  questions, judgments and uncertainty. Revenue/profit or profit/cash-flow
  divergence appends targeted research tasks without increasing search budget.
- **Evidence relations**: explore and export conclusion → hypothesis → evidence →
  source associations, including calculation lineage. Existing SQLite JSON
  snapshots persist this lightweight graph without a graph database.
- **Continuous research**: carry historical hypotheses into a new stock-scoped
  run, revalidate them, compare report versions and financial revisions, detect
  changed text at the same URL, and export a structured/Markdown difference report.
- **Monitoring**: explicit on/off, configurable 1–168-hour minimum interval,
  daily/financial source-change tracking and durable success/partial/failure logs.
  Monitoring remains local, defaults off, and does not automatically spend model
  or search budget or perform trades.

Restart the existing Streamlit service to load the new modules and additive tables:

```powershell
.\.venv\Scripts\python.exe -m streamlit run agent_app.py --server.address 127.0.0.1 --server.port 8502
```

In **个股与自选 → 多期财务分析**, use existing snapshots after explicitly verifying
their accounting metadata, or import sourced financial JSON. Original raw values
are retained; financial imports are versioned separately from market snapshots.
The same panel offers **查看离线合成演示**, which never saves fictional data as real
research. In a research conversation, inspect the new hypothesis, plan revision,
evidence relationship, critic and version-difference panels.

Run an API-free capability demonstration and the complete offline regression:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_v2
.\.venv\Scripts\python.exe -m scripts.run_offline_tests --output artifacts/v2-final-regression.json
```

Optional `RESEARCHPILOT_MODEL_ROUTES_JSON` maps roles such as `planner`, `agent`,
`synthesizer`, `writer`, `chat`, `judgments`, or exact operation IDs to explicit
model IDs. Unspecified routes retain `LLM_MODEL`. `RESEARCHPILOT_STRICT_OUTPUTS=1`
enables a strict JSON Schema for the research controller only; the selected model
must support it. Both switches default to existing behavior and have offline
contract tests, not live model/account certification.

See [core implementation and limitations](docs/V2_CORE_DELIVERY.md),
[architecture](docs/V2_ARCHITECTURE.md), and
[official-source technology assessment](docs/V2_TECH_EVALUATION.md).
This is a tested development build. General semantic verification and live API
quality are not certified; `unknown` must not be interpreted as verified truth.

## v2.0 engineering upgrade — phase 1

The first upgrade increment adds offline agent evaluation and request traces while
retaining both Streamlit entry points and existing SQLite snapshots. This is a
phase-1 implementation, not completion of the full v2.0 roadmap.

- Live search configuration/errors/empty results never substitute synthetic sources.
- Unknown references reject generated report output instead of silently removing
  citation markers. Chat and final reports check narrow same-metric directional
  and percentage conflicts. General semantic support remains **unknown**.
- Rejected evidence is no longer reintroduced during synthesis. The pipeline
  fails without usable evidence; existing historical snapshots remain readable.
- Model requests and tools record run/stage/call IDs, start/end times, latency,
  failure types and available provider token usage in ResearchState diagnostics.
  Prompts, response bodies and credentials are excluded from traces.
- Model token costs require explicit, dated rates; missing usage/rates remain
  unknown. Search and other tool fees are not inferred from model token costs.
- Background workers handle repeated persistence failures without acknowledging
  uncommitted commands, and show a process-local failure message if saving fails.

Run the explicit offline suite and the 16 synthetic evaluation cases:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_offline_tests
.\.venv\Scripts\python.exe -m scripts.evaluate_agent
```

The regression runner blocks network connections and access to production SQLite
files under `data/`. It runs both unittest and legacy main/assert scripts, rejects
zero-test unittest runs, and writes results to `artifacts/offline-tests.json`.
Evaluation writes `artifacts/agent-evaluation.json`, including the dataset hash,
fixture expectation matches, citation/typed-number decisions, coverage and
conflict precision/recall. Fixtures use fictional entities, fixed dates and
`example.invalid` sources; they do not measure live financial research quality.

Optional `RESEARCHPILOT_MODEL_PRICING_JSON` is a JSON object keyed by the configured
model ID with `input_per_million`, `output_per_million`, optional
`cached_input_per_million`, and `as_of` (rate date). Rates are USD per million
tokens. Cached input requires an explicit cached rate when present in usage.
No pricing defaults are assumed, and estimates are not billing statements.
The Agent's existing tool details panel shows trace metadata and missing costs.

Architecture and scope: [phase-1 notes](docs/V2_PHASE1.md).
Initial audit: [review and baseline](docs/V2_REVIEW_AND_BASELINE_2026-10-12.md).
Remaining work includes general semantic verification, live source/provider
certification, cross-process worker ownership and broader production evaluation.
The later core increment adds financial tools, hypotheses, relations and diffs.

## Agent workspace preview

Requires Python 3.11 and the dependencies in `requirements.txt`.

```powershell
.\.venv\Scripts\python.exe -m streamlit run agent_app.py --server.address 127.0.0.1 --server.port 8502
```

Open http://127.0.0.1:8502. The agent selects searches from evidence gaps,
reads sources, reassesses coverage, and stops when coverage or its search
budget is reached. Its action log, evidence, and report are saved in SQLite.
Research runs in a background thread owned by the local server. Browser
disconnection does not stop it. Messages and pause requests enter a durable
SQLite queue and are processed between tool calls. After restarting the server,
explicitly resume interrupted runs. Completed runs can be continued with an
additional search budget (default new-run budget: 2).
Model decisions require `OPENAI_API_KEY`; unavailable model decisions visibly
fall back to coverage rules. Live searches require `TAVILY_API_KEY`; no mock
research is presented as live research. Search count is bounded, but is not
a currency spending limit. Conversational replies use stored report evidence;
quoted references are checked against stored IDs and verbatim excerpts. This
checks reference integrity, not semantic truth or investment suitability.

The stock workbench includes A-share daily prices and K-lines, raw financial
indicators, same-period comparisons, watchlists, thesis journals, and editable
user preferences. AKShare/Eastmoney and Sina are public data dependencies;
failures and data timestamps are displayed. Prices are unadjusted, not live
execution quotes. Financial source values must be checked against original
report units before numerical comparison. No automated trading is implemented.

Optional watchlist monitors update after 16:00 Asia/Shanghai on weekdays while
the server is running. They default to off, show changes/errors in-app, and do
not send external notifications. Non-trading holidays may return unchanged data.
Local research is in `data/researchpilot.db`; preferences, stock snapshots,
watchlists, journals and commands are in `data/workbench.db` (not encrypted).

Offline agent regression: `.\.venv\Scripts\python.exe -m scripts.test_agent`.
Workbench/background regression: `.\.venv\Scripts\python.exe -m scripts.test_workbench`.
The original pipeline UI remains available through `streamlit run app.py`.

> **An AI-powered research agent that transforms complex research into a
> structured, evidence-driven, and reproducible workflow.**

ResearchPilot is an AI-powered research agent designed to perform
structured research on industries, companies, and emerging technologies.

Instead of generating answers directly, ResearchPilot decomposes
research into explicit stages---including planning, web search, evidence
evaluation, synthesis, and report generation---to improve transparency,
traceability, and reliability.

Every research session is persisted as a **ResearchState**, making
research reproducible, reviewable, and recoverable through a built-in
history system.

------------------------------------------------------------------------

## Last published legacy release

**v1.3.0**

------------------------------------------------------------------------

## ✨ Key Features

-   🤖 Multi-stage AI research workflow
-   🧠 LLM-powered research planning
-   🔍 Multi-query web search
-   📖 Automatic evidence reading and extraction
-   📊 Evidence evaluation and credibility scoring
-   🩺 Research Health assessment
-   📝 Structured report generation
-   💾 Persistent ResearchState management
-   🗂 SQLite-backed history storage
-   📜 Historical research browsing and recovery
-   🌐 Interactive Streamlit interface

------------------------------------------------------------------------

# 🏗 Architecture

    Streamlit UI
          │
          ▼
    Application Service
          │
          ▼
    Research Service
          │
          ▼
    Research Engine
          │
          ▼
    SQLite Persistence

The Research Engine executes the complete research workflow while
sharing a unified **ResearchState** across all stages. This architecture
separates user interaction, business orchestration, research execution,
and persistence, making the system easier to extend and maintain.

------------------------------------------------------------------------

# ⚙ Research Workflow

    User Query
          │
          ▼
    Analyze
          │
          ▼
    Plan
          │
          ▼
    Search
          │
          ▼
    Read
          │
          ▼
    Evaluate
          │
          ▼
    Synthesize
          │
          ▼
    Research Health
          │
          ▼
    Write
          │
          ▼
    Persist
          │
          ▼
    History

Every stage communicates through a shared **ResearchState**, ensuring
the research process is transparent, reproducible, and evidence-driven.

------------------------------------------------------------------------

# 🛠 Tech Stack

  Layer             Technology
  ----------------- ---------------
  Language          Python
  Frontend          Streamlit
  LLM               OpenAI GPT
  Search            Tavily API
  Persistence       SQLite
  Data Model        ResearchState
  Version Control   Git + GitHub

------------------------------------------------------------------------

# 🚀 Quick Start

``` bash
git clone <repository-url>
cd ResearchPilot

python -m venv .venv
```

### Activate Environment

**Windows**

``` powershell
.venv\Scripts\Activate.ps1
```

**macOS / Linux**

``` bash
source .venv/bin/activate
```

### Install Dependencies

``` bash
pip install -r requirements.txt
cp .env.example .env
```

Configure your `.env` file:

  Variable           Description
  ------------------ -----------------------------------
  `OPENAI_API_KEY`   OpenAI API Key
  `TAVILY_API_KEY`   Tavily Search API Key
  `LLM_MODEL`        Optional (default: `gpt-4o-mini`)

Run the application:

``` bash
streamlit run app.py
```

------------------------------------------------------------------------

# 📂 Project Structure

``` text
ResearchPilot
│
├── app.py
├── src/
│   ├── app_service.py
│   ├── research_service.py
│   ├── pipeline.py
│   ├── storage.py
│   ├── research_state.py
│   ├── planner.py
│   ├── searcher.py
│   ├── reader.py
│   ├── evaluator.py
│   ├── synthesizer.py
│   └── writer.py
│
├── docs/
├── scripts/
├── data/
└── README.md
```

------------------------------------------------------------------------

# 💡 Design Principles

### Modular Workflow

Each research stage performs a single responsibility and communicates
through shared state.

### State-driven Architecture

The complete research lifecycle is represented by a unified
**ResearchState**, making every execution reproducible and inspectable.

### Evidence-first Research

Every conclusion is grounded in retrieved evidence before entering the
final report.

### Persistent Lifecycle

Completed research sessions are stored in SQLite and can be revisited
through the History system.

------------------------------------------------------------------------

# 🗺 Roadmap

  Version     Highlights
  ----------- ------------------------------------------
  ✅ v1.0     Initial research workflow
  ✅ v1.1     Evidence evaluation & Research Health
  ✅ v1.2     ResearchState & SQLite persistence
  ✅ v1.3     History management & lifecycle

------------------------------------------------------------------------

# 📄 License

**Private --- All Rights Reserved**

This repository is maintained as a personal portfolio project. All
rights are reserved by the author.
