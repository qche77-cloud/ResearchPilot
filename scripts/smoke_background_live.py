"""Explicit bounded live background acceptance run (two search budget)."""
from src.background import Runner
from src.agent import create_agent


def main():
    runner = Runner()
    state = create_agent('研究 A 股 002837 的现金流及业绩兑现，核对财务期间，区分公告事实与预期。', 2)
    state.diagnostics['agent']['messages'] = [{'role': 'user', 'content': state.topic}]
    runner.repo.save_state(state)
    runner.submit(state.run_id, 'resume')
    thread = runner.threads[state.run_id]
    print('Started', state.run_id, flush=True)
    thread.join(300)
    saved = runner.repo.get_state(state.run_id)
    print('Status', saved.status, 'Outcome', saved.diagnostics['agent'].get('outcome'),
          'Sources', len(saved.sources), 'Report', bool(saved.report), flush=True)
    if thread.is_alive() or saved.status != 'completed' or not saved.report:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
