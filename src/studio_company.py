"""Read-only company cockpit assembled from existing finance and memory modules."""
import json
import difflib
from datetime import date
from src.financial_analysis import analyze_financials, financial_evidence, METRICS
from src.financial_quality import financial_quality
from src.research_memory import compare_snapshots, diff_markdown
from src.stock_research import stock_history
from src.stock_data import normalize_symbol
from src.studio_bridge import run_view
from src.financial_diagnostics import research_diagnostics


def financial_payload(store, symbol, dataset_id=None):
    if dataset_id:
        row = store.financial_version(symbol,dataset_id)
        if row is None:
            raise ValueError('该公司不存在此财务版本')
    else:
        row = store.financial_dataset(symbol)
    if row:
        return row['payload'], row['id'], row['created']
    snapshots = store.snapshots(symbol, 1)
    if snapshots:
        return snapshots[0]['payload'], 'snapshot-' + str(snapshots[0]['id']), snapshots[0]['created']
    return {'symbol': symbol}, None, None


def import_financial(store, symbol, content):
    normalize_symbol(symbol)
    if not isinstance(content, str) or len(content.encode('utf-8')) > 2 * 1024 * 1024:
        raise ValueError('请选择不超过 2 MB 的财务 JSON')
    def reject_constant(value):
        raise ValueError('JSON 不允许 NaN 或 Infinity')
    payload = json.loads(content, parse_constant=reject_constant)
    if not isinstance(payload, dict):
        raise ValueError('JSON 顶层必须为对象')
    rows = payload.get('financial_records', payload.get('finance', []))
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError('财务记录须为数组，一次最多 5000 条')
    payload.setdefault('provenance', 'user_import')
    return store.save_financial_dataset(symbol, payload)


def company_view(service, session):
    symbol = session.get('studio_company')
    if not symbol:
        return None
    normalize_symbol(symbol)
    payload, dataset_id, saved = financial_payload(service.store, symbol, session.get('studio_dataset'))
    cutoff = session.get('studio_finance_asof', date.today().isoformat())
    analysis = analyze_financials(payload, as_of=cutoff)
    quality = financial_quality(payload, as_of=cutoff)
    versions = [dict(id=v['id'], created=v['created'], fetched_at=v['payload'].get('fetched_at'))
                for v in service.store.financial_versions(symbol)]
    history = stock_history(service.store, service.repo, symbol)
    timeline = []
    previous = None
    for state in reversed(history):
        view = run_view(state, service.active(state.run_id))
        snapshot = next(reversed(view['versions'].values())) if view['versions'] else None
        diff = compare_snapshots(previous, snapshot) if previous and snapshot else None
        def report_lines(saved):
            return '\n\n'.join('## '+section.get('title','')+'\n'+section.get('content','') for section in saved.get('sections',[])).splitlines()
        report_diff = '\n'.join(difflib.unified_diff(report_lines(previous),report_lines(snapshot),
            fromfile='previous-report',tofile='current-report',lineterm='')) if previous and snapshot else None
        timeline.append(dict(id=state.run_id, topic=state.topic, status=view['status'], created=state.created_at,
            versions=len(view['versions']), conclusions=(snapshot or {}).get('findings', []),
            hypotheses=(snapshot or {}).get('hypotheses', []), diff=diff,
            report_diff=report_diff,
            diff_markdown=diff_markdown(diff) if diff else None))
        if snapshot:
            previous = snapshot
    theses = service.store.theses(symbol)
    tracking_ready=all(callable(getattr(service.store,name,None)) for name in
                       ('thesis_test','thesis_test_versions','thesis_test_runs','save_thesis_test','run_thesis_test'))
    research = research_diagnostics(analysis,**session.get('studio_research_options',{}))
    name = next((w['name'] for w in service.store.watches() if w['symbol'] == symbol), None)
    name = name or next((d['name'] for d in service.store.directory() if d['symbol'] == symbol), symbol)
    valuation = session.get('studio_valuation')
    from src.peer_workspace import workspace_view
    return dict(symbol=symbol, name=name, as_of=cutoff, dataset_id=dataset_id, saved_at=saved,
        versions=versions, analysis=analysis, quality=quality, evidence=financial_evidence(analysis), metrics=METRICS,
        research=research, tracking_ready=tracking_ready, peer_workspace=workspace_view(service.store,session,symbol),
        profile=service.store.profile(symbol), theses=[dict(t, history=service.store.review_history(t['id']),
            test=service.store.thesis_test(symbol,t['id']) if tracking_ready else None,
            test_versions=service.store.thesis_test_versions(symbol,t['id']) if tracking_ready else [],
            test_runs=service.store.thesis_test_runs(symbol,t['id']) if tracking_ready else []) for t in theses],
        timeline=list(reversed(timeline)), watched=any(w['symbol'] == symbol for w in service.store.watches()),
        valuation=valuation if valuation and valuation['symbol'] == symbol and valuation['dataset_id'] == dataset_id else None,
        preferences=service.store.preferences())
