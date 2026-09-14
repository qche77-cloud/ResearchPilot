"""Apply non-destructive chat presentation migration to saved reports."""
from src.storage import ResearchRunRepository
from src.report_links import normalize_history


def main():
    repo = ResearchRunRepository()
    repo.initialize()
    # Collect IDs before updates change history ordering.
    ids = []
    for offset in range(0, repo.count_runs(), 100):
        ids.extend(row.run_id for row in repo.list_runs(limit=100, offset=offset))
    updated = 0
    for run_id in ids:
        state = repo.get_state(run_id)
        if state and state.report and normalize_history(state):
            repo.save_state(state)
            updated += 1
    print(f'Updated {updated} saved reports; original content preserved.')


if __name__ == '__main__':
    main()
