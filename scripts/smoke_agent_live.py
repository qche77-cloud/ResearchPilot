"""Explicit live smoke run; consumes up to two searches and model requests."""
from src.agent import create_agent, tick
from src.storage import ResearchRunRepository


def main():
    repo = ResearchRunRepository()
    repo.initialize()
    state = create_agent('液冷产业链：核查 A 股公司相关业务收入兑现，优先年报和公告', 2)
    for _ in range(20):
        tick(state)
        repo.save_state(state)
        print(state.current_stage, 'sources=', len(state.sources), 'documents=', len(state.documents), flush=True)
        if state.status in {'completed', 'failed'}:
            break
    print('run_id=', state.run_id, 'status=', state.status, flush=True)
    if state.status != 'completed' or not state.sources:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
