"""Isolated fictional claim-verification preview; no production reads or API work."""
from pathlib import Path
import runpy
import streamlit as st

from scripts.evaluate_claims import case_inputs
from scripts.preview_studio import preview_service
from src.agent import create_agent
from src.report_links import snapshot_report
from src.research_reasoning import critic_review, build_evidence_graph


@st.cache_resource
def claim_preview():
    service = preview_service('claim-verification-v1')
    state = create_agent('逐条结论验证验收（全部虚构）')
    state.report, state.synthesis = case_inputs({
        'report': '2025年甲公司营收同比增长10% [E1]。\n2025年甲公司净利润同比增长20% [E2]。\n因此甲公司已形成长期竞争优势 [E1]。',
        'evidence': {'E1': {'text': '2025年甲公司营收同比增长10%。'},
                     'E2': {'text': '2025年甲公司净利润同比增长20%。'}}})
    state.documents = [e.document for e in state.synthesis.evidence_index.values()]
    state.sources = [d.source for d in state.documents]
    state.mark_completed()
    a = state.diagnostics['agent']
    a['report_versions'] = {'legacy-unchecked': {'sections': [{'title': '旧报告', 'content': '历史版本未记录逐条验证。'}],
                                                 'evidence': {}, 'findings': [], 'as_of': '2026-01-01'}}
    a['report_as_of'] = '2026-04-01T00:00:00Z'
    old = snapshot_report(state)
    state.synthesis.evidence_index['E2'].document.extracted_text = '2025年甲公司净利润同比下降20%。'
    a['report_as_of'] = '2026-04-02T00:00:00Z'
    critic_review(state)
    build_evidence_graph(state)
    current = snapshot_report(state)
    a['messages'] = [{'role': 'user', 'content': '离线虚构材料，用于验证界面与版本隔离。'},
                     {'role': 'assistant', 'content': '旧版与新版原始数据不同，请查看逐条验证。', 'report_version': old},
                     {'role': 'assistant', 'content': '新版包含一条原文匹配、一条直接冲突及一条证据不足。', 'report_version': current}]
    service.repo.save_state(state)
    return service


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'studio_app.py'), run_name='__main__',
                   init_globals={'_preview_service': claim_preview()})
