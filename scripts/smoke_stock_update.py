"""Explicit live acceptance: one real stock update, at most two searches."""
import time
from src.agent import create_agent, tick
from src.storage import ResearchRunRepository
from src.workbench import Workbench
from src.stock_research import attach_research
from src.report_links import normalize_history


def main():
    repo, store = ResearchRunRepository(), Workbench()
    repo.initialize()
    state = create_agent('更新 A 股 002837 英维克：核查最新公告、财报期间和现金流。区分公告原文、推断及未核实事项。', 2)
    attach_research(state, store, repo, '002837', update=True)
    state.diagnostics['agent']['messages'] = [{'role': 'user', 'content': state.topic}]
    repo.save_state(state)
    store.link_run('002837', state.run_id)
    print('run_id', state.run_id, flush=True)
    deadline = time.monotonic() + 480
    for _ in range(40):
        if time.monotonic() > deadline:
            print('time_limit: checkpoint retained, not complete', flush=True)
            return
        try:
            tick(state)
        except Exception as exc:
            state.mark_failed('Live acceptance failed: ' + type(exc).__name__)
        normalize_history(state)
        repo.save_state(state)
        a = state.diagnostics['agent']
        print(state.current_stage, 'searches', a['searches'], 'sources', len(state.sources), flush=True)
        if state.status in {'completed', 'failed'}:
            print('RESULT', state.status, a.get('outcome'), 'report', bool(state.report), flush=True)
            return


if __name__ == '__main__':
    main()
