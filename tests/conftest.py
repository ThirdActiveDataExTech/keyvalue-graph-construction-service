"""공용 pytest 훅 — 단위테스트별 수행 시간 측정 리포트.

(테스트 fixture 는 각 테스트 파일이 자체 페이크를 구성한다)
"""

from time import time

import pytest
from tabulate import tabulate

test_durations = []


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_setup(item):
    item.start_time = time()
    yield


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    outcome = yield
    duration = time() - item.start_time
    test_durations.append((item.name, duration))


@pytest.hookimpl(tryfirst=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if test_durations:
        headers = ["Test", "Duration (seconds)"]
        table = tabulate(test_durations, headers, tablefmt="pretty")
        terminalreporter.write("\nTest durations:\n")
        terminalreporter.write(table)
        terminalreporter.write("\n")
