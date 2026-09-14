"""Goal-specific planning and inspectable evidence gaps for the agent UI."""
from datetime import datetime, timezone
import json
import os
import urllib.request

from src.models import ResearchPlanStep


def focus_plan(state):
    plan = state.plan
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        return '沿用原计划（模型未配置）'
    payload = {
        'model': os.getenv('LLM_MODEL') or 'gpt-4o-mini',
        'response_format': {'type': 'json_object'},
        'messages': [
            {'role': 'system', 'content':
             '将用户研究目标转为3到5个直接支持判断的可验证问题，不要通用行业目录。'
             '返回JSON: objective, steps:[{question,criterion,queries:[2条简短搜索词]}]。'
             'criterion明确什么原始证据支持判断，以及何种情况不能下结论。'
             '比较业绩兑现时必须区分实际收入/利润、已交付订单、仅签约订单及扩产规划；'
             '注明比较期间、单位及业务口径需要一致，不得编造企业数据。'},
            {'role': 'user', 'content': state.topic + '\n用户偏好：' + state.diagnostics.get('agent', {}).get('preferences', '')},
        ],
    }
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            data = json.loads(json.loads(response.read())['choices'][0]['message']['content'])
        steps = []
        for item in data.get('steps', [])[:5]:
            question, criterion = item.get('question'), item.get('criterion')
            queries = item.get('queries')
            if not isinstance(question, str) or not isinstance(criterion, str) or not isinstance(queries, list):
                continue
            queries = [q.strip()[:160] for q in queries if isinstance(q, str) and q.strip()][:2]
            if not question.strip() or not queries or question in [s.title for s in steps]:
                continue
            steps.append(ResearchPlanStep(len(steps) + 1, question[:150], criterion[:1200], queries))
        if len(steps) < 3:
            raise ValueError('invalid focused plan')
        plan.steps = steps
        plan.research_objective = str(data.get('objective') or state.topic)[:2000]
        return '已按研究目标制定问题与证据标准'
    except Exception as exc:
        return f'目标规划暂不可用（{type(exc).__name__}），沿用原计划'


def evidence_gaps(state):
    """Observable limitations, not claims of semantic contradiction detection."""
    gaps = []
    for step in state.plan.steps:
        docs = [d for d in state.documents if d.source.research_task == step.title]
        if not docs:
            gaps.append({'task': step.title, 'issue': '尚无来源', 'next': step.search_queries[0] if step.search_queries else step.title})
            continue
        if not any(d.read_status == 'success' and not d.snippet_fallback for d in docs):
            gaps.append({'task': step.title, 'issue': '只有摘要或读取失败，尚未核验正文', 'next': f'{step.title} 原始公告 全文'})
        if not any(d.source.published_date or d.source.published_at for d in docs):
            gaps.append({'task': step.title, 'issue': '所有来源日期未知，无法确认时效及比较期间', 'next': f'{step.title} {datetime.now(timezone.utc).year} 年报'})
    return gaps
