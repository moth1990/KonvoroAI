"""The local stand-ins for RDS, S3 and SQS answer through the same clients the app uses in AWS."""

import uuid

import psycopg

from .conftest import BUCKET, PG_DSN

STAGE_QUEUES = [
    "konboro-s1-intake",
    "konboro-s2-extraction",
    "konboro-s3-symbols",
    "konboro-s4-association",
    "konboro-s5-matching",
    "konboro-s6-validation",
    "konboro-s7-pricing",
]


def test_postgres_has_pgvector() -> None:
    with psycopg.connect(PG_DSN) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        row = conn.execute("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector").fetchone()
    assert row is not None
    assert row[0] == 1.0


def test_s3_round_trip(s3) -> None:  # type: ignore[no-untyped-def]
    key = f"tests/{uuid.uuid4()}.txt"
    body = "שרטוט NURSERY-1".encode()
    s3.put_object(Bucket=BUCKET, Key=key, Body=body)
    assert s3.get_object(Bucket=BUCKET, Key=key)["Body"].read() == body
    s3.delete_object(Bucket=BUCKET, Key=key)


def test_every_stage_has_a_queue_and_a_dlq(sqs) -> None:  # type: ignore[no-untyped-def]
    names = {url.rsplit("/", 1)[-1] for url in sqs.list_queues()["QueueUrls"]}
    assert set(STAGE_QUEUES) | {"konboro-dlq"} <= names


def test_queue_round_trip(sqs) -> None:  # type: ignore[no-untyped-def]
    # Messages carry ids only (specs/12-tech-stack.md §3).
    url = sqs.get_queue_url(QueueName="konboro-s1-intake")["QueueUrl"]
    sqs.send_message(QueueUrl=url, MessageBody='{"drawing_id": "drw_test"}')
    msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=1, WaitTimeSeconds=2)["Messages"]
    assert msgs[0]["Body"] == '{"drawing_id": "drw_test"}'
    sqs.delete_message(QueueUrl=url, ReceiptHandle=msgs[0]["ReceiptHandle"])
