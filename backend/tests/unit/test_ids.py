import pytest

from konboro.db.ids import PREFIXES, is_id, new_id, ulid


def test_format_is_prefix_and_26_crockford_chars() -> None:
    value = new_id("quo")
    assert is_id(value, "quo")
    assert len(value) == len("quo_") + 26
    assert not set(value[4:]) & set("ILOU")  # excluded from Crockford base32


def test_ids_sort_by_creation_time() -> None:
    earlier = ulid(1_700_000_000_000)
    later = ulid(1_700_000_000_001)
    assert earlier < later


def test_ids_are_unique() -> None:
    assert len({new_id("ln") for _ in range(10_000)}) == 10_000


def test_unknown_prefix_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown id prefix"):
        new_id("xyz")


def test_spec_prefixes_are_known() -> None:
    # 00 §6.1
    assert {"drw", "fil", "pg", "pnl", "ts", "blk", "tl", "det", "ins", "cmp", "iss", "quo", "ln", "trc"} <= PREFIXES


@pytest.mark.parametrize(
    "value",
    ["quo_123", "QUO_01JB8Z3K7Q9T2M5X0R4W6Y8C1D", "quo-01JB8Z3K7Q9T2M5X0R4W6Y8C1D", "quo_01JB8Z3K7Q9T2M5X0R4W6Y8CID"],
)
def test_malformed_ids_are_rejected(value: str) -> None:
    assert not is_id(value)


def test_prefix_check() -> None:
    assert not is_id(new_id("ln"), "quo")
