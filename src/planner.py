"""Planner — decompose an analyzed query into an actionable research plan.

Responsibility
--------------
Own *only* research planning. Given an ``AnalyzedQuery`` and depth, produce
a ``ResearchPlan`` with:

- research_objective
- research_strategy
- ordered tasks (title, description, search_queries)

Prefers an OpenAI LLM plan (``OPENAI_API_KEY``, model ``gpt-4o-mini`` by
default). Falls back to rule-based templates if the key is missing or the
API call fails. Does not search, read, or write.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request

from src.env import load_env, openai_api_key_status
from src.models import (
    AnalyzedQuery,
    QueryType,
    ResearchDepth,
    ResearchPlan,
    ResearchPlanStep,
)
from src.query_analyzer import QueryAnalyzer

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
OPENAI_TIMEOUT_SECONDS = 60

INDUSTRY_PLAN_TEMPLATES: list[tuple[str, str, list[str]]] = [
    (
        "行业界定与当前背景",
        "明确{topic}的行业口径、下游场景，以及当前A股市场关注的核心背景。",
        ["{topic} 行业界定 中国", "{topic} industry chain China overview", "{topic} A股 投资逻辑"],
    ),
    (
        "产业链拆解（上中下游）",
        "梳理{topic}上游材料/零部件、中游制造、下游应用，并标出待核实的关键环节。",
        ["{topic} 产业链 上游 中游 下游", "{topic} industry chain upstream midstream downstream China"],
    ),
    (
        "供需驱动因素",
        "识别当前需求侧与供给侧核心变量（景气、库存、开工、订单），只列研究问题不预设结论。",
        ["{topic} 需求 供给 景气 2025 2026", "{topic} demand supply China 2026"],
    ),
    (
        "技术趋势与瓶颈",
        "梳理关键技术路径、国产替代进度与主要瓶颈，待证据验证。",
        ["{topic} 技术瓶颈 国产替代", "{topic} technology bottleneck China"],
    ),
    (
        "近期催化事件",
        "检索涨价、扩产、大订单、政策与技术突破等近期催化线索（待公告/报道核实）。",
        ["{topic} 涨价 扩产 大订单", "{topic} price increase capacity expansion China", "{topic} 政策 催化"],
    ),
    (
        "A股标的与产业链映射",
        "按产业链环节检索相关A股上市公司名单，规划映射关系，不编造公司事实。",
        ["{topic} A股 上市公司", "{topic} A-share listed companies China", "{topic} 概念股 产业链标的"],
    ),
    (
        "竞争壁垒",
        "研究进入壁垒、份额格局与差异化来源（技术、客户、产能、认证等）。",
        ["{topic} 竞争格局 壁垒", "{topic} competitive barriers China"],
    ),
    (
        "风险与不确定性",
        "列出周期、价格、客户集中、技术迭代、政策与出口等关键风险待验证点。",
        ["{topic} 行业风险 产能过剩", "{topic} industry risks China"],
    ),
]

COMPANY_PLAN_TEMPLATES: list[tuple[str, str, list[str]]] = [
    (
        "公司概况与主业",
        "梳理{topic}的上市背景、主营业务与业务结构，待年报/公告核实。",
        ["{topic} 主营业务 年报", "{topic} company profile A-share", "{topic} 业务结构"],
    ),
    (
        "收入与利润驱动",
        "识别收入/毛利/净利的关键驱动因素与量价结构，只列待验证问题。",
        ["{topic} 营收 毛利率 业绩驱动", "{topic} revenue profit drivers"],
    ),
    (
        "产业链位置",
        "明确{topic}在所属产业链中的环节定位及上下游关系。",
        ["{topic} 产业链 位置", "{topic} industry chain position"],
    ),
    (
        "核心产品与客户",
        "梳理核心产品、应用场景与主要客户结构（待公告/调研核实）。",
        ["{topic} 核心产品 客户", "{topic} products customers"],
    ),
    (
        "竞争壁垒",
        "研究技术、客户、产能、资质等护城河来源。",
        ["{topic} 竞争优势 壁垒", "{topic} competitive advantages moat"],
    ),
    (
        "近期公告与催化",
        "检索定增扩产、中标订单、涨价、股权激励、政策相关等近期公告/催化线索。",
        ["{topic} 公告 扩产 中标", "{topic} announcements capacity expansion orders"],
    ),
    (
        "A股同业与竞争对手",
        "检索同行业A股可比公司与竞争关系，不做未经证实的优劣判断。",
        ["{topic} 同行业 可比公司 A股", "{topic} A-share peers competitors"],
    ),
    (
        "关键风险",
        "列出客户集中、原材料、产能利用率、商誉、诉讼与政策等风险待核实点。",
        ["{topic} 风险提示 年报", "{topic} company risks A-share"],
    ),
]

# Technology/theme research follows the same A-share industry-chain playbook.
TECHNOLOGY_PLAN_TEMPLATES = INDUSTRY_PLAN_TEMPLATES

_TEMPLATES_BY_TYPE = {
    QueryType.INDUSTRY: INDUSTRY_PLAN_TEMPLATES,
    QueryType.COMPANY: COMPANY_PLAN_TEMPLATES,
    QueryType.TECHNOLOGY: TECHNOLOGY_PLAN_TEMPLATES,
}

_INDUSTRY_TASK_GUIDE = """
For industry or technology/theme queries, prioritize these research angles
(select/adapt to the requested task count; keep A-share focus):
1) Industry definition and current China/A-share context
2) Industry chain mapping: upstream materials/components, midstream manufacturers, downstream applications
3) Current demand and supply drivers
4) Key technology trends and bottlenecks
5) Recent catalysts to investigate: price increases, capacity expansion, major orders, policy changes, technology breakthroughs
6) A-share listed companies mapped to each industry-chain segment
7) Competitive advantages and barriers to entry
8) Key risks and uncertainties
"""

_COMPANY_TASK_GUIDE = """
For company queries, prioritize these research angles
(select/adapt to the requested task count; keep A-share focus):
1) Company overview and core businesses
2) Revenue/profit drivers
3) Position in the industry chain
4) Core products and customers
5) Competitive advantages and barriers
6) Recent announcements and catalysts
7) Related A-share peers and competitors
8) Key risks
"""


def _ashare_system_prompt(query_type: QueryType) -> str:
    """Build the A-share investment-research system prompt for the LLM planner."""
    if query_type == QueryType.COMPANY:
        methodology = _COMPANY_TASK_GUIDE
        audience = "China A-share company / equity research"
    else:
        methodology = _INDUSTRY_TASK_GUIDE
        audience = "China A-share industry / theme research"

    return f"""You are ResearchPilot's research planner for {audience}.

Mission:
- Produce an actionable research PLAN for Chinese A-share investors.
- Focus on China mainland markets, A-share listed companies, industry chains, catalysts, and risks.
- Do NOT write conclusions. Do NOT invent companies, facts, numbers, or catalysts.
- Only define what to research and what to search for.

Return ONLY valid JSON with this schema:
{{
  "research_objective": "one sentence A-share research objective",
  "research_strategy": "2-4 sentences on how to investigate (chain → drivers → catalysts → A-share mapping → risks)",
  "tasks": [
    {{
      "title": "short Chinese or bilingual task title",
      "description": "what to investigate; no fabricated findings",
      "search_queries": ["query1", "query2"]
    }}
  ]
}}

Methodology to follow:
{methodology}

Search query rules:
- Each task MUST include 2-4 targeted search queries.
- Queries must be specific, entity-rich, and useful for Chinese A-share research.
- Prefer China / A-share / 产业链 / 上市公司 / 公告 / 涨价 / 扩产 / 中标 style terms.
- Mix Chinese and English queries when useful.
- Avoid generic global queries like "PCB technology adoption drivers" or "market outlook overview".
- Prefer queries like:
  - PCB AI server demand 2026
  - PCB 覆铜板 上游 供应商 中国
  - PCB A股 上市公司
  - PCB 涨价 扩产
  - PCB 产业链 中国
  - 液冷 服务器 需求 2026
  - 圣泉集团 主营业务 公告

Hard constraints:
- Prefer Chinese for research_objective, research_strategy, and task titles when the user query is primarily Chinese.
- Explicitly mention 中国 / A股 / 产业链 where relevant.
- Prefer time anchors 2025 / 2026 (or “近一年”) — avoid stale years like 2023 unless searching historical base periods.
- Never invent company names as established facts; if suggesting where to look, phrase as search targets (e.g. "PCB A股 上市公司").
- Never invent price hikes, orders, or policy outcomes; ask the search to find evidence.
- For industry/theme plans with >=5 tasks, include at least: 产业链拆解, 催化检索, A股标的映射, and 风险.
- For company plans with >=5 tasks, include at least: 主业/驱动, 公告催化, A股同业, and 风险.
- Tasks must be concrete and investment-research oriented, not textbook global market research.
"""


def _ashare_user_prompt(
    analyzed: AnalyzedQuery,
    depth: ResearchDepth,
) -> str:
    """Build the user prompt for the A-share LLM planner."""
    task_count = depth.step_count
    return (
        f"User query: {analyzed.raw_query}\n"
        f"Normalized topic: {analyzed.normalized_topic}\n"
        f"Query type: {analyzed.query_type.value}\n"
        f"Analyzer hint: {analyzed.research_goal}\n"
        f"Research depth: {depth.value} — produce exactly {task_count} tasks.\n\n"
        "Design an A-share investment research plan with:\n"
        "- research_objective (Chinese preferred if query is Chinese; mention A股/产业链)\n"
        "- research_strategy (chain → drivers/tech → catalysts → A-share mapping → risks)\n"
        "- tasks (each with 2-4 China/A-share oriented CN/EN search queries; prefer 2025/2026)\n"
        "Remember: planning only — no invented facts or companies."
    )


def _format_step_description(summary: str, queries: list[str]) -> str:
    """Build a checklist-friendly description including search queries."""
    summary = (summary or "").strip()
    if not queries:
        return summary
    query_block = "Queries: " + "; ".join(queries)
    return f"{summary} {query_block}".strip() if summary else query_block


def _classify_openai_error(exc: BaseException) -> str:
    """Map OpenAI/network failures to a safe, user-visible reason."""
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            detail = str(exc.reason or "")
        detail_l = detail.lower()

        if code in (401, 403):
            return "authentication error"
        if code == 404 or "model_not_found" in detail_l or "does not exist" in detail_l:
            return "model unavailable"
        if code == 429 or "insufficient_quota" in detail_l or "billing" in detail_l:
            return "quota/billing error"
        if code == 400 and ("invalid" in detail_l or "model" in detail_l):
            return f"invalid request (HTTP {code})"
        return f"API request failed (HTTP {code})"

    if isinstance(exc, urllib.error.URLError):
        return f"network error ({exc.reason})"

    message = str(exc).lower()
    if "api key not found" in message or "not configured" in message:
        return "API key not found"
    if "authentication" in message or "unauthorized" in message:
        return "authentication error"
    if "model" in message and ("unavailable" in message or "not found" in message):
        return "model unavailable"
    if "quota" in message or "billing" in message or "insufficient_quota" in message:
        return "quota/billing error"
    if "invalid response" in message or "json" in message or "missing tasks" in message:
        return "invalid response format"
    if "unexpected openai response" in message:
        return "invalid response format"
    return f"planner error ({exc.__class__.__name__})"


class Planner:
    """Create a structured research plan from an analyzed query.

    Attributes:
        last_warning: Human-readable fallback reason from the latest ``plan`` call.
    """

    def __init__(self) -> None:
        self.last_warning: str | None = None
        load_env()

    def plan(self, analyzed: AnalyzedQuery, depth: ResearchDepth) -> ResearchPlan:
        """Generate a research plan for the analyzed query and depth.

        Tries OpenAI first when ``OPENAI_API_KEY`` is set; otherwise uses
        rule-based templates. On API failure, falls back to rules and sets
        ``last_warning`` with a classified reason.

        Args:
            analyzed: Structured query from the QueryAnalyzer.
            depth: How thorough the research should be.

        Returns:
            A ResearchPlan with objective, strategy, and tasks.
        """
        self.last_warning = None
        load_env()
        status = openai_api_key_status()
        logger.info(
            "Planner OpenAI key detected=%s length=%s model=%s",
            status["present"],
            status["length"],
            status["model"],
        )

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            self.last_warning = (
                "API key not found. OPENAI_API_KEY is missing or empty after loading "
                ".env (check that the line is uncommented). Using rule-based planner."
            )
            logger.warning(self.last_warning)
            return self._rule_based_plan(analyzed, depth)

        try:
            plan = self._llm_plan(analyzed, depth, api_key)
            self.last_warning = None
            return plan
        except Exception as exc:  # noqa: BLE001 — intentional graceful fallback
            reason = _classify_openai_error(exc)
            self.last_warning = (
                f"{reason}. Falling back to rule-based planner."
            )
            logger.warning("OpenAI planner fallback: %s | detail=%s", reason, exc)
            return self._rule_based_plan(analyzed, depth)

    def _rule_based_plan(
        self,
        analyzed: AnalyzedQuery,
        depth: ResearchDepth,
    ) -> ResearchPlan:
        """Template-based planner used as default fallback."""
        topic = analyzed.normalized_topic
        templates = _TEMPLATES_BY_TYPE.get(analyzed.query_type, INDUSTRY_PLAN_TEMPLATES)

        steps: list[ResearchPlanStep] = []
        for i, (title, description, query_tmpls) in enumerate(templates[: depth.step_count]):
            queries = [q.format(topic=topic) for q in query_tmpls]
            summary = description.format(topic=topic)
            steps.append(
                ResearchPlanStep(
                    order=i + 1,
                    title=title,
                    description=_format_step_description(summary, queries),
                    search_queries=queries,
                )
            )

        if analyzed.query_type == QueryType.COMPANY:
            objective = f"围绕A股视角梳理{topic}的主业、业绩驱动、产业链位置、催化与风险。"
            strategy = (
                f"先核实公司概况与收入驱动，再定位产业链与产品客户，"
                f"随后检索近期公告催化、A股同业对比与关键风险，全程以公开信息为准。"
            )
        else:
            objective = f"从A股产业研究视角拆解{topic}的产业链、供需、催化与可跟踪标的。"
            strategy = (
                f"按「界定→产业链→供需/技术→催化→A股映射→壁垒/风险」推进，"
                f"搜索以中国市场、A股上市公司与可验证事件为导向，不预设结论。"
            )

        return ResearchPlan(
            topic=topic,
            depth=depth,
            steps=steps,
            query_type=analyzed.query_type,
            research_goal=objective,
            research_objective=objective,
            research_strategy=strategy,
            analyzed_query=analyzed,
            planner_source="rules",
        )

    def _llm_plan(
        self,
        analyzed: AnalyzedQuery,
        depth: ResearchDepth,
        api_key: str,
    ) -> ResearchPlan:
        """Call OpenAI Chat Completions and map JSON into ResearchPlan."""
        model = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL).strip() or DEFAULT_LLM_MODEL
        task_count = depth.step_count

        system_prompt = _ashare_system_prompt(analyzed.query_type)
        user_prompt = _ashare_user_prompt(analyzed, depth)

        payload = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        request = urllib.request.Request(
            OPENAI_CHAT_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=OPENAI_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError:
            # Re-raise so _classify_openai_error can inspect status/body.
            raise
        except urllib.error.URLError:
            raise

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("invalid response format") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("invalid response format") from exc

        try:
            parsed = _parse_llm_json(content)
        except (json.JSONDecodeError, RuntimeError) as exc:
            raise RuntimeError("invalid response format") from exc

        return self._plan_from_llm_json(analyzed, depth, parsed)

    def _plan_from_llm_json(
        self,
        analyzed: AnalyzedQuery,
        depth: ResearchDepth,
        data: dict,
    ) -> ResearchPlan:
        """Validate LLM JSON and build a ResearchPlan."""
        topic = analyzed.normalized_topic
        objective = str(data.get("research_objective") or "").strip()
        strategy = str(data.get("research_strategy") or "").strip()
        raw_tasks = data.get("tasks") or data.get("research_tasks") or []

        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise RuntimeError("LLM response missing tasks")

        if not objective:
            objective = analyzed.research_goal or f"Research {topic}."
        if not strategy:
            strategy = f"Execute structured research tasks for {topic}."

        steps: list[ResearchPlanStep] = []
        for i, task in enumerate(raw_tasks[: depth.step_count]):
            if not isinstance(task, dict):
                continue
            title = str(task.get("title") or f"Task {i + 1}").strip()
            summary = str(task.get("description") or "").strip()
            queries_raw = task.get("search_queries") or task.get("queries") or []
            if isinstance(queries_raw, str):
                queries = [queries_raw]
            elif isinstance(queries_raw, list):
                queries = [str(q).strip() for q in queries_raw if str(q).strip()]
            else:
                queries = []

            if not queries:
                queries = [f"{topic} {title}"]

            steps.append(
                ResearchPlanStep(
                    order=i + 1,
                    title=title,
                    description=_format_step_description(summary, queries),
                    search_queries=queries,
                )
            )

        if not steps:
            raise RuntimeError("LLM produced no usable tasks")

        # Pad with rule-based tasks if the model returned too few for the depth.
        if len(steps) < depth.step_count:
            fallback = self._rule_based_plan(analyzed, depth)
            for extra in fallback.steps[len(steps) : depth.step_count]:
                extra.order = len(steps) + 1
                steps.append(extra)

        return ResearchPlan(
            topic=topic,
            depth=depth,
            steps=steps,
            query_type=analyzed.query_type,
            research_goal=objective,
            research_objective=objective,
            research_strategy=strategy,
            analyzed_query=analyzed,
            planner_source="llm",
        )


def _parse_llm_json(content: str) -> dict:
    """Parse model content into a dict, tolerating markdown fences."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RuntimeError("LLM JSON root must be an object")
    return data


def create_research_plan(topic: str, depth: ResearchDepth) -> ResearchPlan:
    """Convenience wrapper: analyze raw text, then plan."""
    analyzed = QueryAnalyzer().analyze(topic)
    return Planner().plan(analyzed, depth)
