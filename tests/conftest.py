import os

import pytest

# Opt in to python-telegram-bot's future timedelta API (as the app does in __main__),
# which also silences its deprecation warning.
os.environ.setdefault("PTB_TIMEDELTA", "1")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="rewrite golden files instead of comparing against them",
    )


@pytest.fixture
def update_golden(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-golden"))
