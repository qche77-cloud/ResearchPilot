# ResearchPilot

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

## Current Release

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
