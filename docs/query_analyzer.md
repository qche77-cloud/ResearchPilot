# Query Analyzer examples

The `QueryAnalyzer` classifies user input before planning. Rule-based for now (no LLM).

## Examples

| User query | `query_type` | `normalized_topic` | Research focus |
| --- | --- | --- | --- |
| `PCB industry chain` | `industry` | `PCB Industry Chain` | Market structure, value chain, players, risks |
| `Shengquan Group` | `company` | `Shengquan Group` | Company profile, segments, peers, risks |
| `AI glasses` | `technology/theme` | `AI Glasses` | Adoption drivers, stack, commercialization |

## Pipeline position

```
User Query
  → QueryAnalyzer   → AnalyzedQuery
  → Planner         → ResearchPlan (type-specific steps)
  → Searcher → Reader → EvidenceEvaluator → Synthesizer → Writer
```

## How to try

```python
from src.query_analyzer import QueryAnalyzer

for q in ["PCB industry chain", "Shengquan Group", "AI glasses"]:
    a = QueryAnalyzer().analyze(q)
    print(a.query_type.value, "|", a.normalized_topic, "|", a.research_goal)
```
