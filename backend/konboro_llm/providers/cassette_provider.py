"""Recorded answers, for the golden-set eval (dev-strategy §6) and for tests that need a real model's output.

    replay: the answer comes from `<root>/<stage>/<key>.json`; a missing cassette is an error, never a live call.
    record: the wrapped provider answers, and the answer is written to that file.

The key is a hash of everything that can change the answer: stage, model, system prompt, user text, image bytes
(or the image's stable `key`, when the caller gives one),
few-shot examples, the output schema and the retry hint. Change any of them and the cassette must be recorded again.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from ..base import LLMProvider, RawAnswer
from ..types import LLMError, LLMRequest

CassetteMode = Literal["replay", "record"]


class CassetteMissingError(LLMError):
    """Replay found no recording for this request."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cassette_key(request: LLMRequest[Any], model: str, retry_hint: str | None) -> str:
    material = {
        "stage": request.stage,
        "model": model,
        "system": request.system,
        "user_text": request.user_text,
        "images": [[i.media_type, i.key or _sha256(i.data)] for i in request.images],
        "examples": [[e.text, e.expected_json, _sha256(e.image.data) if e.image else None] for e in request.examples],
        "schema": request.output_schema.model_json_schema(),
        "retry_hint": retry_hint,
    }
    return _sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode())


class CassetteProvider:
    def __init__(self, root: Path, mode: CassetteMode = "replay", wrapped: LLMProvider | None = None):
        if mode == "record" and wrapped is None:
            raise ValueError("record mode needs a provider to record from")
        self.root = root
        self.mode = mode
        self.wrapped = wrapped
        self.name = wrapped.name if wrapped is not None else "cassette"

    def path(self, request: LLMRequest[Any], model: str, retry_hint: str | None = None) -> Path:
        return self.root / request.stage / f"{cassette_key(request, model, retry_hint)}.json"

    def complete_structured(self, request: LLMRequest[Any], model: str, retry_hint: str | None = None) -> RawAnswer:
        path = self.path(request, model, retry_hint)
        if self.mode == "replay":
            if not path.exists():
                raise CassetteMissingError(
                    f"no cassette for stage '{request.stage}' ({path.name}): the prompt, schema or input changed. "
                    "Record it with EVAL_MODE=live EVAL_RECORD=1 make eval"
                )
            return RawAnswer.model_validate(json.loads(path.read_text(encoding="utf-8"))["answer"])
        assert self.wrapped is not None  # noqa: S101 (checked in __init__)
        answer = self.wrapped.complete_structured(request, model, retry_hint)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"stage": request.stage, "model": model, "answer": answer.model_dump()}
        path.write_text(json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return answer
