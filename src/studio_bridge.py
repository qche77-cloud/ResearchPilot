"""Presentation contract for the Studio component; reuse the existing research engine.

Building a packet never starts a worker, monitor, model or network fetch. Commands
are explicit, validated and consumed once per Streamlit session.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import date

from src.agent import create_agent
from src.evidence_cards import cards
from src.financial_screening import screen_financials
from src.research_state import _to_jsonable as to_json_safe
from src.stock_research import attach_research, symbols_in


def run_view(state, active=False):
    a = state.diagnostics.get('agent', {})
    versions = deepcopy(a.get('report_versions', {}))
    # Unsnapshotted legacy reports remain visible without inventing citation lineage.
    if state.report and not versions:
        versions['legacy'] = dict(as_of=state.updated_at, evidence={}, findings=[],
            sections=[asdict(s) for s in state.report.sections])
    for snapshot in versions.values():
        snapshot['cards'] = cards(snapshot)
    status = ('后台执行中' if active else '执行失败' if state.status == 'failed' else
              '部分完成' if a.get('outcome') == 'partial' else
              '已完成' if state.status == 'completed' else '待恢复')
    # Keep source metadata separate: old uncited sources must never become [E1].
    return to_json_safe(dict(
        id=state.run_id, topic=state.topic, status=status, active=active,
        completed=state.status == 'completed', stage=state.current_stage,
        updated_at=state.updated_at, error=state.error,
        budget=a.get('budget', 2), searches=a.get('searches', 0),
        messages=a.get('messages', []), versions=versions,
        sources=[dict(title=s.title, url=s.url, date=s.published_date) for s in state.sources],
        hypotheses=state.diagnostics.get('hypotheses', []),
        graph=state.diagnostics.get('evidence_graph', {}),
        critic=state.diagnostics.get('critic'), diff=state.diagnostics.get('research_diff'),
        trace_summary=state.diagnostics.get('trace_summary'),
        trace=[{k: t.get(k) for k in ('operation', 'kind', 'stage', 'status', 'started_at', 'elapsed_ms', 'model', 'usage', 'estimated_cost')}
               for t in state.diagnostics.get('trace', [])],
        events=a.get('events', []), revisions=a.get('automatic_revisions', []),
        plan=[asdict(s) for s in state.plan.steps] if state.plan else [],
        gaps=a.get('evidence_gaps', []), baseline=a.get('baseline'),
        stock_symbol=a.get('stock_symbol')))


def screening_view(store, criteria):
    if not isinstance(criteria.get('minimums', {}), dict):
        raise ValueError('筛选阈值必须为指标与数值的映射')
    if criteria.get('basis', 'cumulative') not in {'cumulative', 'single_quarter'}:
        raise ValueError('请选择累计或单季口径')
    if criteria.get('currency', 'CNY') not in {'CNY', 'USD', 'HKD', 'EUR'}:
        raise ValueError('请选择支持的币种')
    if criteria.get('scope', 'consolidated') not in {'consolidated', 'parent_company'}:
        raise ValueError('请选择合并或母公司报表')
    payloads, missing = {}, []
    for stock in store.watches()[:50]:
        row = store.financial_dataset(stock['symbol'])
        if row:
            payloads[stock['symbol']] = row['payload']
        else:
            missing.append(stock['symbol'])
    result = screen_financials(payloads, **criteria)
    result['missing_symbols'] = missing
    return result


def packet(service, session):
    selected = session.get('studio_run')
    # Use the repository for rendering. Runner.read can write legacy normalization;
    # the Studio's polling is deliberately read-only.
    state = service.repo.get_state(selected) if selected else None
    criteria = session.get('studio_criteria', dict(as_of=date.today().isoformat(), minimums={}))
    view = session.get('studio_view', 'research')
    return dict(
        view=view, preview=bool(getattr(service, '_studio_preview', False)),
        history=[dict(id=r.run_id, topic=r.topic, status=r.status, updated_at=r.updated_at)
                 for r in service.repo.list_runs(limit=100)],
        history_count=service.repo.count_runs(),
        run=run_view(state, service.active(selected)) if state else None,
        watches=service.store.watches(), criteria=criteria,
        screening=screening_view(service.store, criteria) if view == 'screening' else None,
        notice=session.get('studio_notice'), ack=session.get('studio_event'),
        pending=[dict(kind=c['kind'], content=c['content']) for c in service.store.pending(selected)] if state else [],
    )


def start_run(service, session, topic, budget=2, symbol=None, update=False):
    if getattr(service, '_studio_preview', False):
        raise ValueError('离线预览不启动真实研究，请使用正式工作区')
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 6000:
        raise ValueError('请输入 1–6000 字的研究问题')
    if isinstance(budget, bool) or not isinstance(budget, int) or not 2 <= budget <= 16:
        raise ValueError('搜索预算范围为 2–16 次')
    topic = topic.strip()
    candidates = symbols_in(topic, service.store.directory())
    symbol = symbol or (candidates[0] if len(candidates) == 1 else None)
    if symbol and symbol not in topic:
        topic = f'{symbol} · {topic}'
    state = create_agent(topic, budget)
    if symbol:
        attach_research(state, service.store, service.repo, symbol, update)
    state.diagnostics['agent']['preferences'] = service.store.preferences()
    state.diagnostics['agent']['messages'] = [
        {'role': 'user', 'content': topic},
        {'role': 'assistant', 'content': '研究已创建。我会核查原始资料，记录支持与反面证据。'}]
    service.repo.save_state(state)
    if symbol:
        service.store.link_run(symbol, state.run_id)
    session['studio_run'] = state.run_id
    session['studio_view'] = 'research'
    service.submit(state.run_id, 'resume')
    return state.run_id


def consume_event(event, service, session):
    """Handle one component intent; never accept arbitrary backend/tool names."""
    if not isinstance(event, dict) or event.get('id') in session.get('studio_events', []):
        return False
    eid = event.get('id')
    if not isinstance(eid, str) or not 1 <= len(eid) <= 100:
        return False
    session['studio_events'] = (session.get('studio_events', []) + [eid])[-256:]
    session['studio_event'] = eid
    session['studio_notice'] = None
    action = event.get('action')
    try:
        if action == 'navigate':
            view = event.get('view')
            if view not in {'research', 'watchlist', 'screening', 'workbench'}:
                raise ValueError('未知工作区')
            session['studio_view'] = view
        elif action == 'open':
            target = event.get('run_id')
            if not isinstance(target, str) or not 1 <= len(target) <= 100:
                raise ValueError('无效研究标识')
            if not service.repo.get_state(target):
                raise ValueError('研究记录不存在')
            session['studio_run'] = event['run_id']
            session['studio_view'] = 'research'
        elif action == 'new':
            session.pop('studio_run', None)
            session['studio_view'] = 'research'
        elif action == 'start':
            if getattr(service, '_studio_preview', False):
                raise ValueError('离线预览不启动真实研究，请使用正式工作区')
            start_run(service, session, event.get('topic'), event.get('budget', 2))
            session['studio_notice'] = '研究已创建，正在后台执行'
        elif action == 'screen':
            criteria = dict(as_of=event.get('as_of'), minimums=event.get('minimums', {}),
                            basis=event.get('basis', 'cumulative'),
                            currency=event.get('currency', 'CNY'), scope=event.get('scope', 'consolidated'))
            date.fromisoformat(criteria['as_of'])
            screening_view(service.store, criteria)  # Validate before persisting UI criteria.
            session['studio_criteria'] = criteria
            session['studio_view'] = 'screening'
        elif action in {'chat', 'pause', 'resume', 'budget', 'update'}:
            run_id = event.get('run_id')
            # An old iframe event cannot steer the newly selected task.
            if run_id != session.get('studio_run'):
                raise ValueError('任务已切换，请在当前任务重试')
            state = service.repo.get_state(run_id)
            if not state:
                raise ValueError('研究记录不存在')
            if getattr(service, '_studio_preview', False):
                raise ValueError('离线预览不执行模型或任务命令')
            if action == 'update':
                symbol = state.diagnostics.get('agent', {}).get('stock_symbol')
                if not symbol or service.active(run_id):
                    raise ValueError('需选择已结束的公司研究')
                start_run(service, session, f'更新 A 股 {symbol} 的研究，对照上次结论核查新增信息。',
                          symbol=symbol, update=True)
            else:
                content = event.get('content', '')
                if action == 'chat' and (not isinstance(content, str) or not content.strip() or len(content) > 6000):
                    raise ValueError('追问需为 1–6000 字')
                if action == 'resume' and state.status == 'completed':
                    raise ValueError('研究已完成，请追问或创建更新研究')
                service.submit(run_id, action, content.strip() if action == 'chat' else '')
            session['studio_notice'] = '请求已加入后台队列'
        else:
            raise ValueError('未知操作')
    except (ValueError, TypeError, KeyError) as exc:
        session['studio_notice'] = '操作未执行：' + str(exc)
    return True
