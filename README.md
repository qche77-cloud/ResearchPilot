# ResearchPilot

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
