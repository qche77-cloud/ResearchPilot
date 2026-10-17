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
from src.worker_lock import WorkerLock


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
    from src.studio_company import company_view
    current_screen = session.get('studio_screen_result')
    result = dict(
        view=view, preview=bool(getattr(service, '_studio_preview', False)),
        fixture_writes=bool(getattr(service, '_studio_fixture_writes', False) is True),
        history=[dict(id=r.run_id, topic=r.topic, status=r.status, updated_at=r.updated_at)
                 for r in service.repo.list_runs(limit=100)],
        history_count=service.repo.count_runs(),
        run=run_view(state, service.active(selected)) if state else None,
        watches=service.store.watches(), criteria=criteria,
        screening=(current_screen or screening_view(service.store, criteria)) if view == 'screening' else None,
        company=company_view(service, session) if view == 'company' else None,
        directory=service.store.directory() if view == 'watchlist' else [],
        presets=service.store.screening_presets() if view == 'screening' else [],
        executions=service.store.screening_executions() if view == 'screening' else [],
        worker=dict(locked=WorkerLock.held(service.repo.db_path, selected), attempts=service.store.worker_attempts(selected)) if state else None,
        notice=session.get('studio_notice'), ack=session.get('studio_event'),
        pending=[dict(kind=c['kind'], content=c['content']) for c in service.store.pending(selected)] if state else [],
    )
    return to_json_safe(result)


def execute_screen(service, session, criteria, preset=None, archived=None):
    payloads, bindings, missing = {}, {}, []
    if archived is not None:
        for symbol, binding in archived.items():
            row = service.store.financial_version(symbol,binding['dataset_id'])
            if not row:
                raise ValueError('历史筛选输入版本缺失，不能用最新数据替代')
            payloads[symbol], bindings[symbol] = row['payload'], binding
    else:
        for stock in service.store.watches()[:50]:
            row = service.store.financial_dataset(stock['symbol'])
            if row:
                payloads[stock['symbol']] = row['payload']
                bindings[stock['symbol']] = {'dataset_id': row['id']}
            else:
                missing.append(stock['symbol'])
    result = screen_financials(payloads, **criteria)
    result['missing_symbols'] = missing
    # The fixture may calculate screens, but synthetic executions aren't persisted.
    if not getattr(service, '_studio_preview', False) or getattr(service, '_studio_fixture_writes', False) is True:
        result['execution_id'] = service.store.save_screening_execution(result, bindings, preset)
    session['studio_screen_result'] = result
    session['studio_criteria'] = criteria
    return result


def start_run(service, session, topic, budget=2, symbol=None, update=False, financial_context=None):
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
    if financial_context:
        from src.financial_analysis import attach_financial_analysis
        payload,dataset_id,cutoff=financial_context
        if payload.get('symbol')!=symbol:
            raise ValueError('财务输入与研究公司不匹配')
        attach_financial_analysis(state,payload,as_of=cutoff)
        state.diagnostics['agent']['market_checked']=True
        state.diagnostics['agent']['financial_input_context']=dict(dataset_id=dataset_id,as_of=cutoff)
        state.diagnostics['agent']['instructions'].append(f'本轮财务证据固定为输入版本 {dataset_id}，仅采用截至 {cutoff} 可用的记录。未自动采集最新行情；公开资料可能来自其他时点，必须明确标识，不宣称这是完整历史回测。')
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
            screening_view(service.store, criteria)
            execute_screen(service, session, criteria)
            session['studio_view'] = 'screening'
        elif action in {'company', 'finance_options', 'finance_import', 'valuation', 'save_profile', 'add_thesis', 'review_thesis', 'watch', 'save_preferences', 'company_research', 'research_options', 'save_thesis_test', 'run_thesis_test'}:
            from src.stock_data import normalize_symbol
            from src.studio_company import financial_payload, import_financial
            symbol = event.get('symbol')
            normalize_symbol(symbol)
            if action != 'company' and symbol != session.get('studio_company'):
                raise ValueError('公司已切换，请在当前公司重试')
            mutations = {'finance_import','save_profile','add_thesis','review_thesis','watch','save_preferences','company_research','save_thesis_test','run_thesis_test'}
            if action in {'save_thesis_test','run_thesis_test'} and not callable(getattr(service.store,action,None)):
                raise ValueError('此后台进程尚未加载判据存储模块，请使用更新后的服务')
            if action in mutations and getattr(service, '_studio_preview', False) and (getattr(service, '_studio_fixture_writes', False) is not True or action=='company_research'):
                raise ValueError('离线预览不保存或启动真实研究')
            if action == 'company':
                session['studio_company'] = symbol
                session.pop('studio_dataset', None)
                session.pop('studio_research_options',None)
                session['studio_view'] = 'company'
            elif action == 'research_options':
                from src.financial_analysis import analyze_financials
                from src.financial_diagnostics import research_diagnostics
                options={k:event.get(k) for k in ('basis','currency','scope')}
                if event.get('period_end'):
                    options['period_end']=event['period_end']
                payload,_,_=financial_payload(service.store,symbol,session.get('studio_dataset'))
                analysis=analyze_financials(payload,as_of=session.get('studio_finance_asof',date.today().isoformat()))
                research_diagnostics(analysis,**options)
                session['studio_research_options']=options
            elif action == 'save_thesis_test':
                _,dataset_id,_=financial_payload(service.store,symbol,session.get('studio_dataset'))
                if event.get('dataset_id')!=dataset_id or event.get('as_of')!=session.get('studio_finance_asof',date.today().isoformat()):
                    raise ValueError('财务输入或截止日已变化，请刷新判据表单')
                service.store.save_thesis_test(symbol,event.get('thesis_id'),event.get('test'),
                    expected_revision=event.get('revision'),baseline_dataset_id=dataset_id,
                    baseline_as_of=session.get('studio_finance_asof',date.today().isoformat()))
                session['studio_notice']='财务判据已保存新版本；人工投资判断保持原样'
            elif action == 'run_thesis_test':
                _,dataset_id,_=financial_payload(service.store,symbol,session.get('studio_dataset'))
                if event.get('dataset_id')!=dataset_id or event.get('as_of')!=session.get('studio_finance_asof',date.today().isoformat()):
                    raise ValueError('财务输入或截止日已变化，请刷新后再执行检查')
                service.store.run_thesis_test(symbol,event.get('thesis_id'),expected_revision=event.get('revision'),
                    dataset_id=dataset_id,as_of=session.get('studio_finance_asof',date.today().isoformat()))
                session['studio_notice']='财务判据检查已保存，未自动修改人工复盘状态'
            elif action == 'finance_options':
                cutoff = event.get('as_of')
                date.fromisoformat(cutoff)
                if event.get('dataset_id'):
                    financial_payload(service.store, symbol, event['dataset_id'])
                session['studio_finance_asof'] = cutoff
                session['studio_dataset'] = event.get('dataset_id') or None
            elif action == 'finance_import':
                session['studio_dataset'] = import_financial(service.store, symbol, event.get('content'))
                session['studio_notice'] = '财务输入已保存为新版本；来源真实性仍需核对'
            elif action == 'valuation':
                from src.financial_analysis import analyze_financials, identity, number
                from urllib.parse import urlsplit
                if number(event.get('value')) is None or number(event.get('value'))<=0 or event.get('currency') not in {'CNY','USD','HKD','EUR'}:
                    raise ValueError('市值须为正数，并明确币种')
                date.fromisoformat(event.get('as_of'))
                if urlsplit(event.get('source_url','')).scheme not in {'http','https'}:
                    raise ValueError('请提供有效的市值来源链接')
                payload, dataset_id, _ = financial_payload(service.store, symbol, session.get('studio_dataset'))
                market = dict(symbol=symbol,value=event.get('value'),unit='元',currency=event.get('currency'),as_of=event.get('as_of'),source_url=event.get('source_url'))
                market['id'] = identity(market,'M')
                analysis = analyze_financials(dict(payload,market_valuation=market))
                session['studio_valuation'] = dict(symbol=symbol,dataset_id=dataset_id,market=market,results=analysis['valuations'])
                session['studio_notice'] = '估值结果已计算；缺少合格分母时不输出数值'
            elif action == 'save_profile':
                values = [event.get(k,'') for k in ('focus','supporting','contrary','questions')]
                if any(not isinstance(v,str) or len(v)>6000 for v in values):
                    raise ValueError('档案字段须为不超过 6000 字的文本')
                service.store.save_profile(symbol,*values)
                session['studio_notice'] = '研究档案已保存'
            elif action == 'add_thesis':
                values = [event.get(k,'') for k in ('thesis','catalyst','invalidation')]
                if not all(isinstance(v,str) and len(v)<=6000 for v in values) or not values[0].strip():
                    raise ValueError('请填写有效的投资假设')
                service.store.add_thesis(symbol,*values)
                session['studio_notice'] = '投资假设已保存'
            elif action == 'review_thesis':
                thesis = next((t for t in service.store.theses(symbol) if t['id']==event.get('thesis_id')),None)
                if not thesis or event.get('status') not in {'观察中','得到支持','被推翻','已结束'}:
                    raise ValueError('投资假设或状态无效')
                review = event.get('review')
                if not isinstance(review,str) or len(review)>6000:
                    raise ValueError('复盘须为不超过 6000 字的文本')
                if event.get('before') != {'review':thesis['review'],'status':thesis['status']}:
                    raise ValueError('复盘已变更，请刷新后再保存')
                service.store.review(thesis['id'],review,event['status'],expected=event['before'])
                session['studio_notice'] = '复盘及变更历史已保存'
            elif action == 'watch':
                service.store.watch(symbol,event.get('name') or symbol)
                session['studio_notice'] = '已加入自选'
            elif action == 'save_preferences':
                content = event.get('content','')
                if not isinstance(content,str) or len(content)>6000:
                    raise ValueError('偏好须为不超过 6000 字的文本')
                service.store.save_preferences(content)
                session['studio_notice'] = '长期研究偏好已保存'
            elif action == 'company_research':
                payload,dataset_id,_=financial_payload(service.store,symbol,session.get('studio_dataset'))
                context=(payload,dataset_id,session.get('studio_finance_asof',date.today().isoformat())) if dataset_id else None
                start_run(service,session,event.get('topic') or f'研究 A 股 {symbol} 的经营质量、现金流与反面证据。',event.get('budget',2),symbol,bool(event.get('update')),financial_context=context)
        elif action in {'save_preset','run_preset','open_screen_execution','replay_screen_execution'}:
            if getattr(service,'_studio_preview',False) and getattr(service,'_studio_fixture_writes',False) is not True and action!='open_screen_execution':
                raise ValueError('离线预览不保存真实筛选方案或执行历史')
            if action=='save_preset':
                criteria=session.get('studio_criteria',dict(as_of=date.today().isoformat(),minimums={}))
                screening_view(service.store,criteria)
                service.store.save_screening_preset(event.get('name'),criteria)
                session['studio_notice']='筛选方案已保存，包含固定截止日与阈值'
            elif action=='run_preset':
                preset=next((p for p in service.store.screening_presets() if p['id']==event.get('preset_id')),None)
                if not preset: raise ValueError('筛选方案不存在')
                execute_screen(service,session,preset['criteria'],preset)
                session['studio_notice']='按保存方案运行完成，已记录本次输入版本'
            else:
                execution=next((e for e in service.store.screening_executions(100) if e['id']==event.get('execution_id')),None)
                if not execution: raise ValueError('筛选执行记录不存在')
                if action=='open_screen_execution':
                    session['studio_screen_result']=dict(execution['result'],execution_id=execution['id'])
                    session['studio_criteria']=execution['criteria']
                else:
                    execute_screen(service,session,execution['criteria'],archived=execution['input_ids'])
                    session['studio_notice']='已使用历史输入版本重新计算'
            session['studio_view']='screening'
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
