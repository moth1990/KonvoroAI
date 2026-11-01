"""Settings and clients for the local S3 and SQS, with a queue prefix per test run so no other worker sees them."""

import uuid

import pytest

from konboro.services.queue import STAGE_QUEUES, Queue
from konboro.services.storage import Storage
from konboro.settings import Settings

from .conftest import S3_ENDPOINT, SQS_ENDPOINT

RUN_PREFIX = f"test-{uuid.uuid4().hex[:8]}-"
RUN_BUCKET = "konboro-test"  # emptied at the start of each run (Storage.reset_local_bucket)


def aws_settings(**extra: object) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        env="test",
        s3_endpoint=S3_ENDPOINT,
        sqs_endpoint=SQS_ENDPOINT,
        sqs_queue_prefix=RUN_PREFIX,
        s3_bucket=RUN_BUCKET,
        stage_retry_seconds=0,
        **extra,
    )


@pytest.fixture(scope="session")
def queue() -> Queue:
    q = Queue(aws_settings())
    q.ensure()
    return q


@pytest.fixture
def clean_queue(queue: Queue) -> Queue:
    """The run's queues, emptied before the test."""
    for base in [*STAGE_QUEUES.values(), "konboro-dlq"]:
        queue.purge(base)
    return queue


@pytest.fixture(scope="session")
def storage() -> Storage:
    store = Storage(aws_settings())
    store.reset_local_bucket()
    return store
