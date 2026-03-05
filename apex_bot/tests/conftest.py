from pathlib import Path


def pytest_sessionstart(session):
    """Ensure runtime directories exist for tests that write artifacts."""
    for rel in ("logs", "data/cache", "reports"):
        Path(rel).mkdir(parents=True, exist_ok=True)
