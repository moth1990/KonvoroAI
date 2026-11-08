"""Response-time guards against the specs' targets (BUG-115).

A guard times an action by wall clock, so on a loaded machine it measures the machine too: on GitHub's runners
`/lines/{id}/qty` took 1.18 s where it takes 0.09 s locally, and a 1 s guard failed a PR that changed nothing on that
path. So the integration suite allows each target × `CI_MARGIN`, which still catches a slowdown of a different order
(a model call, a full pipeline run, a query per line), and `make perf` holds the target itself (`KONBORO_PERF=1`) on a
quiet machine, outside CI. Every guard names its target and where it comes from.

A test that times something is marked `@pytest.mark.perf`, which is what `make perf` selects; `within` fails a test
without the marker, so no guard is left out of it.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

CI_MARGIN = 3.0


@dataclass(frozen=True)
class Target:
    seconds: float
    spec: str


# 09 §14's table, and the rows of 06 §9 and 07 §9 that a review action waits for.
ACTION = Target(0.5, "09 §14: an action (approve, quantity, delete) with the server's recalculation ≤ 500 ms")
RERUN = Target(1.0, "09 §14: an alternative or an attribute edit, stages 5–7 for the lines it touches, ≤ 1 s")
REVALIDATION = Target(1.0, "06 §9: the rules again after the user's fix < 1 s")
RECALCULATION = Target(2.0, "07 §9: a full recalculation after a price-list change, with the diff, ≤ 2 s")


class _Node(Protocol):
    nodeid: str

    def get_closest_marker(self, name: str) -> object | None: ...


# The running test, set by `tests/integration/conftest.py`; None outside pytest's integration tests.
running: _Node | None = None


def strict() -> bool:
    """`make perf`: the target itself, with no margin."""
    return os.environ.get("KONBORO_PERF") == "1"


def limit(target: Target) -> float:
    return target.seconds if strict() else target.seconds * CI_MARGIN


@contextmanager
def within(target: Target, what: str) -> Iterator[None]:
    """Fail when the block takes the target or longer: × `CI_MARGIN` in the suite, the target alone in `make perf`."""
    if running is not None and running.get_closest_marker("perf") is None:
        raise AssertionError(f"{running.nodeid} times {what}: mark it @pytest.mark.perf so `make perf` runs it")
    start = perf_counter()
    yield
    took = perf_counter() - start
    allowed = limit(target)
    margin = "" if strict() else f", × {CI_MARGIN:g} for a loaded runner; `make perf` checks the target itself"
    assert took < allowed, f"{what} took {took:.2f} s, over {allowed:.2f} s ({target.spec}{margin})"
