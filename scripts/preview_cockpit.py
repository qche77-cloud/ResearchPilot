"""Writable acceptance sandbox: temporary DBs, fictional data, paid actions blocked."""
from pathlib import Path
import json
import runpy
from unittest.mock import patch
import streamlit as st
from scripts.preview_studio import preview_service
from src.financial_screening_ui import demo_pool
from src.workbench import Workbench
from src.agent import create_agent
from src.models import ResearchReport, ReportSection


@st.cache_resource
def cockpit_service(cache_scope='default'):
    service=preview_service('cockpit-'+cache_scope)
    service._studio_fixture_writes=True
    # Use the real version repository for acceptance, with clearly fictional
    # fixtures inserted only into this service's TemporaryDirectory database.
    service.store.financial_dataset=Workbench.financial_dataset.__get__(service.store)
    for symbol,payload in demo_pool().items():
        with service.store.connect() as db:
            db.execute('INSERT OR IGNORE INTO financial_inputs VALUES (?,?,?,?)',
                ('fictional-input-'+symbol,symbol,'2026-04-01T00:00:00Z',json.dumps(payload,ensure_ascii=False)))
    state=next(service.repo.get_state(r.run_id) for r in service.repo.list_runs() if '公司 A' in r.topic)
    state.diagnostics['agent']['stock_symbol']='002837'
    service.repo.save_state(state)
    service.store.link_run('002837',state.run_id)
    previous=create_agent('离线演示公司 A：最初研究基线')
    previous.created_at='2026-04-01T09:00:00Z'
    previous.mark_completed()
    previous.report=ResearchReport(previous.topic,previous.depth,[ReportSection('基线','离线合成基线，尚未核对现金流。')])
    previous.diagnostics['agent']['stock_symbol']='002837'
    previous.diagnostics['agent']['report_versions']={'fictional-baseline':dict(as_of='2026-04-01',sections=[dict(title='基线',content='离线合成基线')],evidence={},findings=[dict(text='增长假设尚待检验',kind='inference',evidence_ids=[])])}
    service.repo.save_state(previous)
    service.store.link_run('002837',previous.run_id)
    return service


if __name__=='__main__':
    service=cockpit_service(st.query_params.get('acceptance_token','default'))
    with patch('src.workbench_ui.fetch_stock',side_effect=RuntimeError('隔离验收禁用网络')),patch('src.workbench_ui.fetch_directory',side_effect=RuntimeError('隔离验收禁用网络')):
        runpy.run_path(str(Path(__file__).resolve().parents[1]/'studio_app.py'),run_name='__main__',init_globals={'_preview_service':service})
