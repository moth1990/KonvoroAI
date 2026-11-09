"""The response-time guards (BUG-115): a loaded runner within the margin passes the suite, `make perf` holds the spec's
target itself, a slowdown beyond the margin fails both, and a guard needs the `perf` marker so `make perf` runs it."""

from dataclasses import dataclass

import pytest

from tests import perf


@pytest.fixture(autouse=True)
def _suite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KONBORO_PERF", raising=False)
    monkeypatch.setattr(perf, "running", None)


def taking(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """The guarded block takes `seconds`: the guard's clock reads 0, then that."""
    readings = iter((0.0, seconds))
    monkeypatch.setattr(perf, "perf_counter", lambda: next(readings))


@dataclass
class Node:
    nodeid: str
    markers: tuple[str, ...]

    def get_closest_marker(self, name: str) -> object | None:
        return name if name in self.markers else None


def test_an_action_slowed_by_a_loaded_runner_passes_the_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR #43's CI: `/lines/{id}/qty` took 1.18 s against 09 §14's 1 s, where it takes 0.09 s locally."""
    taking(monkeypatch, 1.18)
    with perf.within(perf.RERUN, "/lines/ln_1/qty"):
        pass


def test_make_perf_holds_the_target_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KONBORO_PERF", "1")
    taking(monkeypatch, 1.18)
    with pytest.raises(AssertionError) as failed, perf.within(perf.RERUN, "/lines/ln_1/qty"):
        pass
    assert str(failed.value).startswith("/lines/ln_1/qty took 1.18 s, over 1.00 s (09 §14:")
    assert "loaded runner" not in str(failed.value)


def test_a_slowdown_beyond_the_margin_fails_the_suite_and_names_its_target(monkeypatch: pytest.MonkeyPatch) -> None:
    taking(monkeypatch, 1.6)
    with pytest.raises(AssertionError) as failed, perf.within(perf.ACTION, "/lines/ln_1/approve"):
        pass
    message = str(failed.value)
    assert message.startswith("/lines/ln_1/approve took 1.60 s, over 1.50 s (09 §14:")
    assert "≤ 500 ms" in message and "× 3 for a loaded runner" in message


def test_each_target_names_its_spec() -> None:
    assert [(t.seconds, t.spec[:6]) for t in (perf.ACTION, perf.RERUN, perf.REVALIDATION, perf.RECALCULATION)] == [
        (0.5, "09 §14"),
        (1.0, "09 §14"),
        (1.0, "06 §9:"),
        (2.0, "07 §9:"),
    ]


def test_a_guard_in_a_test_without_the_perf_marker_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    taking(monkeypatch, 0.01)
    monkeypatch.setattr(perf, "running", Node("tests/integration/test_x.py::test_y", ("integration",)))
    unmarked = pytest.raises(AssertionError, match=r"test_y times /approve: mark it @pytest.mark.perf")
    with unmarked, perf.within(perf.ACTION, "/approve"):
        pass
    monkeypatch.setattr(perf, "running", Node("tests/integration/test_x.py::test_y", ("integration", "perf")))
    with perf.within(perf.ACTION, "/approve"):
        pass


def test_a_failure_inside_the_block_is_not_hidden_by_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    taking(monkeypatch, 9.0)
    with pytest.raises(ValueError, match="the request failed"), perf.within(perf.ACTION, "/approve"):
        raise ValueError("the request failed")
