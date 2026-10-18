# ResearchPilot

## Dark research terminal — 2026-10-18

Studio now uses a compact dark interface, with unified navigation, real research
and watchlist counts, a working resume card, global search, denser financial
panels and readable report/source typography. Data versions, saved drafts,
citations and original financial calculations are preserved.

Acceptance: **51 browser checks** (9 visual/readability + 21 Studio + 14 company
+ 7 PDF/peer workflows), plus **33/33 offline suites and 252 unit tests**.
Screenshots use isolated fictional data. The home description contrast measures
8.85:1 at the tested widths; this is not a full-interface accessibility certification.
[Design changes and evidence](docs/DARK_TERMINAL_2026-10-18.md).

## Financial PDF import and peer research — 2026-10-18

In **公司研究 → 财报导入**, upload a text PDF, inspect proposed figures and
original page excerpts, then explicitly confirm the period, units and scope.
The original file and confirmed records are saved together as a new version.
Limits: 12 MB / 400 pages; scanned documents and automatic OCR are not supported.

In **同业比较**, save a manually chosen group of 2–50 companies and compare
the same reporting period, currency, scope and cutoff. Python computes medians,
coverage and differences; missing inputs remain missing. Results and input
versions persist. Rule-triggered questions can start research with archived
financial inputs and traceable comparison evidence.

Acceptance: **33/33 offline suites, 252 unit tests**, **30/30 source amounts and
6/6 reported YoY values** from three historical public annual reports; **42
browser checks** (7 new + 14 company + 21 Studio) in temporary fictional data.
The three reports are a small acceptance sample, not a general accuracy estimate.
No new production dependencies or model calls during acceptance.

[Delivery, sources and limitations](docs/PEER_RESEARCH_2026-10-18.md).

## Interface wording — 2026-10-18

The interface now uses **公司研究、自选公司、财务检查、验证条件** throughout
navigation and forms. Search limits, source checks and financial results use
clearer Chinese explanations. Existing reports and saved user text are preserved.
[Changes and acceptance evidence](docs/UI_COPY_2026-10-18.md).

## Financial research tools — 2026-10-18

Open **公司研究 → 财务检查** to inspect seven deterministic financial signals:
revenue/profit divergence, cash below profit, inventory/receivables growing faster
than revenue, falling gross margin, lower expensed R&D, and a high gap between
attributable and adjusted attributable profit. Every signal exposes its threshold,
reporting period and original inputs. Missing data remains explicitly unresolved.

The profit waterfall decomposes the change in same-scope net profit into revenue,
gross margin, available aggregate period expenses and an unexplained remainder.
Click bars to inspect exact inputs; export the reconciled accounting ledger.
This is an arithmetic decomposition, not proof of business causality.

In **投资复盘**, set a financial criterion, target reporting period and review date.
Explicit checks use the selected saved financial version and cutoff, preserving
criterion versions, actual observations, original inputs and later revisions.
Results never overwrite manual investment judgments. Checks are user-triggered;
this release does not add a background scheduler or declare a full thesis true.

Validation: **31/31 offline suites, 236 unit tests**, **12/12 new synthetic
evaluation cases**, **46 browser checks** (11 new + 14 cockpit + 21 Studio).
No new production dependencies or paid API calls during acceptance. Existing
tables remain; two additive tables store criterion versions and check runs.

[Delivery report, formulas and limits](docs/FINANCIAL_RESEARCH_2026-10-18.md) ·
[Profit waterfall](artifacts/research-tools-browser/profit-bridge-desktop.png) ·
[Criterion tracking](artifacts/research-tools-browser/thesis-tracking-desktop.png)

[Final code `2318623` passed GitHub CI](https://github.com/qche77-cloud/ResearchPilot/actions/runs/39054561276).
Downloaded cloud artifacts confirm 31/31 suites, 236 unit tests, 12/12 new cases,
and an identical canonical evaluation dataset hash.

Updated production entry while running: **http://127.0.0.1:8526**. Health check
returned 200/ok; starting it submitted no research/model tasks and preserved the
existing services. This health check is not a live financial-provider acceptance.

Isolated fictional preview while running: **http://127.0.0.1:8524**.
Open **自选公司 → 公司 A → 财务检查 / 投资复盘**. Original production services
were not restarted. Use a fresh updated backend for the new storage features.

## Claim verification — 2026-10-18

New reports save sentence-level claim checks alongside their exact report and
evidence versions. In Studio, open **过程 → 此版本的结论验证** to inspect complete
source-statement matches, direct conflicts, unresolved claims, original excerpts
and source dates; download the selected version's verification JSON.

`supported` means a complete saved source statement matches (formatting and case
normalized), **not independent factual or semantic verification**. Paraphrases,
causal claims and unmatched scopes remain unresolved. Direct conflicts require
the same statement template apart from direction/percentages. Conflicting or
unresolved claims become Critic warnings; direct unopposed conflicts block normal
report generation. Existing historical versions are not backfilled with newer checks.

Validation: **29/29 offline suites, 216 unit tests**, **32/32 synthetic claim
fixtures**, **9 new + 21 existing Studio browser checks**. No new dependencies,
database migrations or model API calls for these checks.

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_claims
.\.venv\Scripts\python.exe -m scripts.run_offline_tests
```

[Delivery report and limits](docs/CLAIM_VERIFICATION_2026-10-18.md) ·
[Desktop](artifacts/claim-browser/claims-desktop.png) ·
[Mobile](artifacts/claim-browser/claims-mobile.png)

[GitHub CI for final code `fc577f2`](https://github.com/qche77-cloud/ResearchPilot/actions/runs/39051470907)
passed; downloaded cloud artifacts confirm **29/29 suites, 216 unit tests and
32/32 claim fixtures**.

The isolated fictional preview is **http://127.0.0.1:8522** while its process is
running. It deliberately includes a conflicting saved report to exercise the UI;
normal report generation rejects that direct conflict. Existing production
services were not restarted; use a fresh updated Studio process to load backend changes.

## Company research — 2026-10-15

Studio now integrates **财务分析、研究时间轴、研究档案、投资复盘**. Open a
company from **自选公司**, or enter its six-digit code. Financial JSON imports are
versioned; chart points expose exact inputs, units, disclosure dates and sources.
The finance panel supports cumulative/single-quarter/TTM views, YoY/QoQ, margins,
quality checks and deterministic PE/PB with eligible disclosed denominators.

Company research can pin the selected financial version and cutoff as structured
Agent evidence. The timeline compares saved conclusions, hypotheses, financial
revisions and actual report text. Profiles, preferences and manual review versions
persist in the existing workbench database.

Financial screening supports saved fixed-date criteria, durable execution results
and replay using the original financial input versions, even after new imports.
Updated workers use OS-backed locks across processes, durable attempts and safe
checkpoint replay; a crashed process releases its lock without a time-based lease.

```powershell
.\.venv\Scripts\python.exe -m streamlit run studio_app.py --server.address 127.0.0.1 --server.port 8521
```

Current full local entry: **http://127.0.0.1:8521**. Isolated writable fictional
acceptance preview: **http://127.0.0.1:8520**. Earlier services remain untouched.
Use updated workers for task execution; unupdated running services cannot follow
the new lock protocol. Studio still does not automatically resume old jobs or
start another monitor scheduler.

Validation: **27/27 offline suites, 197 unit tests**, **14/14 cockpit browser
checks**, plus **21/21 existing UI checks**. No paid API calls during acceptance.
[Delivery report](docs/COMPANY_COCKPIT_2026-10-15.md) ·
[Finance view](artifacts/cockpit-browser/finance-desktop.png) ·
[Research timeline](artifacts/cockpit-browser/timeline-desktop.png) ·
[Mobile finance](artifacts/cockpit-browser/finance-mobile.png)

[GitHub CI for the full cockpit](https://github.com/qche77-cloud/ResearchPilot/actions/runs/38600813215)
passed 27/27 suites and 197 unit tests for code commit `e3695ba`.

All published screenshots use isolated fictional inputs. Stock quotes, monitor
configuration and AI judgment-proposal confirmation remain in **完整数据工具**.

## ResearchPilot Studio — 2026-10-14

The new `studio_app.py` entry point replaces the research page layout with a
dedicated frontend: a persistent task library, report canvas and assistant/source
inspector. Click a citation to inspect its original saved evidence beside the
report; switch report versions or open the version associated with a chat message.
It also adds a resizable workspace, keyboard task search (`Ctrl/Cmd K`), browser
session drafts, responsive reading and financial screening with input lineage.

The frontend is a local HTML/CSS/JavaScript Streamlit component. It uses the
existing Python Runner, financial calculations and SQLite repositories; no new
frontend build tools, graph database or paid service are required. Full financial
imports, stock tools and investment review remain accessible through **完整数据工具**.
The original `agent_app.py` remains available.

```powershell
.\.venv\Scripts\python.exe -m streamlit run studio_app.py --server.address 127.0.0.1 --server.port 8511
```

The October 14 Studio entry was verified at `http://127.0.0.1:8511`. Its fictional preview:
`http://127.0.0.1:8510`. These are local links, not public hosting.
Studio does not automatically resume historical jobs or start a second monitor
scheduler. Avoid executing the same task from multiple application processes.

[Implementation and acceptance report](docs/STUDIO_INTERFACE_2026-10-14.md) ·
[Research workspace](artifacts/studio-preview/research-desktop.png) ·
[Citation inspector](artifacts/studio-preview/evidence-desktop.png) ·
[Mobile reading](artifacts/studio-preview/report-mobile.png)

Offline regression: **25/25 suites, 178 unit tests**. Browser acceptance: **15/15
checks** at 1440, 1024 and 390 pixels. All published screenshots use fictional data.
The [GitHub CI run](https://github.com/qche77-cloud/ResearchPilot/actions/runs/38537194631)
also passed 25/25 suites and 178 unit tests for code commit `0dc212b`.

Studio now includes delayed hover tooltips, version-scoped citation previews,
card/button feedback and short page/panel transitions. Polling does not replay
animations, and reduced-motion preferences are respected. The layout is retained.
[Interaction polish report](docs/STUDIO_INTERACTIONS_2026-10-14.md) ·
[Citation hover preview](artifacts/studio-polish/citation-hover.png).
The updated browser acceptance passes **21/21 checks**.

## Financial screening foundation — 2026-10-14

The stock workspace now includes **财务质量体检** and **财务筛选**. Review
revenue/profit growth, margins and cash conversion with explicit dates, scope,
currency, formulas and input IDs. Filter up to 50 locally saved watchlist datasets;
missing values stay unavailable, and screening does not fetch data or call a model.
An explicit fictional demo is available without saving or launching real research.

Financial calculations support date-level `as_of`; valuation selects an older
publicly available report when the latest one was not disclosed at the market date.
Invalid publication metadata and inconsistent/nonfinite OHLCV bars are rejected.

The prior financial-screening Streamlit entry was verified at `http://127.0.0.1:8506`.
See the [delivery and limitations](docs/QUANT_FOUNDATION_2026-10-14.md) and
[review roadmap](docs/REVIEW_AND_QUANT_ROADMAP_2026-10-14.md).
This is financial research screening, without strategy backtesting or trading.

## Research desk interface — 2026-10-13

The redesigned workspace uses a warm light canvas, a teal navigation sidebar and
separate views for conversations, reports, evidence and verification. Stock
research separates market snapshots, financial charts, company profiles and thesis
reviews. Existing local data and background research commands are retained.

[Interface delivery and test report](docs/UI_REDESIGN_2026-10-13.md) ·
[Desktop preview](artifacts/ui-preview/home-desktop.png) ·
[Mobile preview](artifacts/ui-preview/home-mobile.png)

The October 13 interface was verified at `http://127.0.0.1:8504`; the previous
8502 process was preserved. For a fresh service, use an available port:

```powershell
.\.venv\Scripts\python.exe -m streamlit run agent_app.py --server.address 127.0.0.1 --server.port 8504
```

Requires Streamlit 1.41 or newer. That delivery included 164 unit tests
across 24 suite entries, including Windows asyncio/socketpair isolation checks.
See the [GitHub CI diagnosis and fix](docs/CI_FIX_2026-10-13.md).
Optional browser acceptance uses isolated fictional data;
see the interface report for setup and limits.

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
Latest test and GitHub publication record: [2026-10-13 delivery report](docs/DAILY_2026-10-13.md).
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
