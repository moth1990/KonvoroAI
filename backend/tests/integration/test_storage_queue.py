"""S3 and SQS as the pipeline uses them (12 §3): tenant prefixes, encryption, IDs-only messages, the DLQ."""

import json
import urllib.request

import pytest
from pydantic import ValidationError

from konboro.db.ids import new_id
from konboro.services.queue import DLQ, MAX_RECEIVES, STAGE_QUEUES, Queue, StageMessage
from konboro.services.storage import Storage, TenantKeyError, drawing_key


def message(stage: int = 1) -> StageMessage:
    return StageMessage(drawing_id=new_id("drw"), tenant_id=new_id("tnt"), stage=stage, trace_id=new_id("trc"))


def test_files_live_under_the_tenant_prefix_encrypted(storage: Storage) -> None:
    tenant, drawing = new_id("tnt"), new_id("drw")
    key = drawing_key(tenant, drawing, "files", "NURSERY-1.pdf")
    assert key == f"tenants/{tenant}/drawings/{drawing}/files/NURSERY-1.pdf"
    storage.put(tenant, key, b"%PDF-1.7 test", "application/pdf")
    assert storage.get(tenant, key) == b"%PDF-1.7 test"
    head = storage.s3.head_object(Bucket=storage.bucket, Key=key)
    assert head["ServerSideEncryption"] == "AES256"


def test_another_tenants_key_is_refused(storage: Storage) -> None:
    a, b = new_id("tnt"), new_id("tnt")
    key = drawing_key(a, new_id("drw"), "x.png")
    for call in (lambda: storage.get(b, key), lambda: storage.presigned_get(b, key), lambda: storage.put(b, key, b"")):
        with pytest.raises(TenantKeyError):
            call()


@pytest.mark.parametrize("parts", [("..", "x"), ("a/b",), ("",)])
def test_key_parts_cannot_escape(parts: tuple[str, ...]) -> None:
    with pytest.raises(TenantKeyError):
        drawing_key(new_id("tnt"), new_id("drw"), *parts)


def test_a_presigned_url_serves_the_file(storage: Storage) -> None:
    tenant = new_id("tnt")
    key = drawing_key(tenant, new_id("drw"), "thumb.png")
    storage.put(tenant, key, b"\x89PNG fake", "image/png")
    with urllib.request.urlopen(storage.presigned_get(tenant, key)) as response:  # noqa: S310 (local S3Mock)
        assert response.read() == b"\x89PNG fake"


def test_a_message_carries_ids_only(clean_queue: Queue) -> None:
    sent = message(stage=3)
    clean_queue.send(sent)
    url = clean_queue.url(STAGE_QUEUES[3])
    (raw,) = clean_queue.sqs.receive_message(QueueUrl=url, WaitTimeSeconds=2, VisibilityTimeout=0)["Messages"]
    assert json.loads(raw["Body"]) == {
        "drawing_id": sent.drawing_id,
        "tenant_id": sent.tenant_id,
        "stage": 3,
        "trace_id": sent.trace_id,
    }
    (got,) = clean_queue.receive(STAGE_QUEUES[3], wait_s=2)
    assert got.message == sent
    clean_queue.delete(got)


def test_extra_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        StageMessage.model_validate(message().model_dump() | {"file_bytes": "JVBERi0"})


def test_a_message_that_is_not_ours_is_never_acted_on(clean_queue: Queue) -> None:
    clean_queue.sqs.send_message(QueueUrl=clean_queue.url(STAGE_QUEUES[1]), MessageBody='{"drawing_id": "x"}')
    assert clean_queue.receive(STAGE_QUEUES[1], wait_s=2) == []


def test_three_failed_receives_move_a_message_to_the_dlq(clean_queue: Queue) -> None:
    sent = message(stage=2)
    clean_queue.send(sent)
    for attempt in range(1, MAX_RECEIVES + 1):
        (got,) = clean_queue.receive(STAGE_QUEUES[2], wait_s=2)
        assert got.receive_count == attempt
        clean_queue.retry_later(got, 0)
    assert clean_queue.receive(STAGE_QUEUES[2], wait_s=1) == []
    (dead,) = clean_queue.receive(DLQ, wait_s=2)
    assert dead.message == sent
