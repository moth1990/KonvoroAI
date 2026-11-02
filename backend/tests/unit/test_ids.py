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


def test_ids_made_in_one_millisecond_keep_their_order() -> None:
    # BUG-018: rows created in the same millisecond were ordered by the random part.
    same_ms = [ulid(1_700_000_000_000) for _ in range(1_000)]
    assert same_ms == sorted(same_ms)
    assert len(set(same_ms)) == len(same_ms)
    made = [new_id("qev") for _ in range(10_000)]
    assert made == sorted(made)


def test_an_earlier_timestamp_still_sorts_by_its_own_time() -> None:
    # Monotonic within a millisecond only: an explicit earlier time is not pushed past the last id.
    later = ulid(1_700_000_000_005)
    earlier = ulid(1_700_000_000_000)
    assert earlier < later
    assert earlier.startswith(ulid(1_700_000_000_000)[:10])


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
