"""Speech to text for the chat builder (13 §4.2, S27): a recording in, Hebrew words out.

The product's transcriber is Amazon Transcribe in `he-IL` (12; real in S29, with its account and permissions). It has
no Hebrew custom language model, so "שלוש על שש עשרה" and "מא"ז" come out as spoken; the `chat_bom_extraction` step
normalizes them, and the estimator sees what was heard and what was understood before anything is added
(S27 decision 1).

Until S29 the transcriber is a stand-in: whatever was recorded, it hears the prototype's sentence (`startRec`, line
1327), so the whole path (the microphone, the upload, the card, the lines) runs end to end. The screen says so.

A recording is never stored: it is read, transcribed and dropped in the request. Only its words are kept, as the
build message's "heard" text.
"""

from dataclasses import dataclass
from typing import Protocol

MAX_BYTES = 2 * 1024 * 1024  # about a minute of Opus at the browser's default bitrate, with room to spare
MAX_SECONDS = 60
AUDIO_TYPES = frozenset({"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac"})

# The prototype's recording (`startRec`, line 1327)
STAND_IN_HEARD = (
    "מפסק ראשי ארבע על שישים ושלוש, שנים עשר מא״ז אחד על שש עשרה, ארבעה מא״ז שלוש על עשרים וחמש, ופחת ארבע על ארבעים"
)


class RecordingError(Exception):
    """The recording is empty, too long, or not audio the transcriber reads."""


class Transcriber(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def stand_in(self) -> bool: ...

    def transcribe(self, audio: bytes, content_type: str) -> str: ...


@dataclass(frozen=True)
class StandInTranscriber:
    name: str = "stand-in"
    stand_in: bool = True

    def transcribe(self, audio: bytes, content_type: str) -> str:
        return STAND_IN_HEARD


def media_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().casefold()


def check(audio: bytes, content_type: str | None) -> str:
    """The recording's media type, after the checks; raises `RecordingError`."""
    kind = media_type(content_type)
    if kind not in AUDIO_TYPES:
        raise RecordingError("type")
    if not audio:
        raise RecordingError("empty")
    if len(audio) > MAX_BYTES:
        raise RecordingError("too_large")
    return kind


def transcriber() -> Transcriber:
    """The transcriber this deployment uses. Amazon Transcribe arrives with the cloud setup (S29)."""
    return StandInTranscriber()
