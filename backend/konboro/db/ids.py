"""Entity IDs: a prefix plus a ULID, e.g. "quo_01JB8Z3K7Q9T2M5X0R4W6Y8C1D" (00 §6.1, docs/db-schema.md §1, §7).

ULIDs sort by creation time and are safe in URLs. Generated here to avoid a dependency for 20 lines.
"""

import os
import re
import threading
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

PREFIXES = frozenset(
    # 00 §6.1
    {"drw", "fil", "pg", "pnl", "ts", "blk", "tl", "det", "ins", "cmp", "iss", "quo", "ln", "trc"}
    # docs/db-schema.md §7
    | {"tnt", "usr", "cus", "prj", "ctx", "qv", "evt", "prd", "sup", "psp", "prh", "mr", "dr", "mm", "qev", "llm"}
    | {
        "cnv",
        "msg",
        "prp",
        "aud",
        "dif",
        "aql",
        "kc",
        "cat",
        "ref",
        "trf",
        "abr",
        "tab",
        "vat",
        "tpl",
        "spf",
        "ckt",
        "cac",
        "spl",
    }
)

_ID = re.compile(r"^([a-z]+)_([0-9A-HJKMNP-TV-Z]{26})$")


_RANDOM_MAX = (1 << 80) - 1
_last = (-1, 0)  # (ms, random part) of the last id made in this process
_lock = threading.Lock()


def ulid(timestamp_ms: int | None = None) -> str:
    """26 Crockford base32 chars: 48-bit millisecond timestamp, then 80 random bits.

    Monotonic within a process (the ULID spec's monotonic mode): an id made in the same millisecond as the last one
    takes the last one's random part plus one, so rows created together keep their order (BUG-018). A clock that
    steps back reuses the last millisecond. Ids from different processes still order only by their millisecond."""
    global _last
    with _lock:
        ms = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
        last_ms, last_rand = _last
        if timestamp_ms is None and ms < last_ms:
            ms = last_ms
        same_ms = ms == last_ms and last_rand < _RANDOM_MAX
        rand = last_rand + 1 if same_ms else int.from_bytes(os.urandom(10), "big")
        _last = (ms, rand)
    value = (ms << 80) | rand
    chars = []
    for _ in range(26):
        value, rem = divmod(value, 32)
        chars.append(_CROCKFORD[rem])
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix {prefix!r}; add it to docs/db-schema.md §7 and PREFIXES")
    return f"{prefix}_{ulid()}"


def is_id(value: str, prefix: str | None = None) -> bool:
    m = _ID.match(value)
    if m is None:
        return False
    return prefix is None or m.group(1) == prefix
