"""Writable temporary financial-research fixture; no models or live stock APIs."""
import json
from pathlib import Path
import runpy
from unittest.mock import patch
import streamlit as st
from scripts.preview_cockpit import cockpit_service
from scripts.test_research_tools import research_fixture


@st.cache_resource
def research_service(token='default'):
    service=cockpit_service('research-tools-'+token)
    payload=research_fixture()
    payload['provenance']='synthetic_fixture'
    with service.store.connect() as db:
        db.execute('INSERT OR IGNORE INTO financial_inputs VALUES (?,?,?,?)',
            ('fictional-research-v1','002837','2026-10-18T00:00:00Z',json.dumps(payload,ensure_ascii=False)))
    if not service.store.theses('002837'):
        service.store.add_thesis('002837','收入同比增长能够保持在 15% 以上（虚构验收）','下一份财报','收入增长低于目标')
    return service


if __name__=='__main__':
    service=research_service(st.query_params.get('acceptance_token','default'))
    with patch('src.workbench_ui.fetch_stock',side_effect=RuntimeError('隔离验收禁止网络')),patch('src.workbench_ui.fetch_directory',side_effect=RuntimeError('隔离验收禁止网络')):
        runpy.run_path(str(Path(__file__).resolve().parents[1]/'studio_app.py'),run_name='__main__',init_globals={'_preview_service':service})
