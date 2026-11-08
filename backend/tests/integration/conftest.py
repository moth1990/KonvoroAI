"""Shared setup for integration tests: connection settings for the docker-compose services (make up)."""

import os
from collections.abc import Iterator

import boto3
import pytest

from .. import perf

PG_DSN = os.environ.get("KONBORO_TEST_PG_DSN", "postgresql://konboro:konboro@localhost:5433/konboro")
S3_ENDPOINT = os.environ.get("KONBORO_S3_ENDPOINT", "http://localhost:9000")
SQS_ENDPOINT = os.environ.get("KONBORO_SQS_ENDPOINT", "http://localhost:9324")
BUCKET = "konboro-files"

# Local stand-ins accept any credentials; boto3 still requires some to sign requests.
_AWS = {"region_name": "eu-central-1", "aws_access_key_id": "local", "aws_secret_access_key": "local"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def s3():  # type: ignore[no-untyped-def]
    return boto3.client("s3", endpoint_url=S3_ENDPOINT, **_AWS)


@pytest.fixture
def sqs():  # type: ignore[no-untyped-def]
    return boto3.client("sqs", endpoint_url=SQS_ENDPOINT, **_AWS)


from .api import api  # noqa: E402, F401  (module fixture: the app on konboro_test, two tenants)
from .aws import clean_queue, queue, storage  # noqa: E402, F401  (local S3 and this run's own queues)
from .db import migrated_db  # noqa: E402, F401  (session fixture: a fresh, migrated konboro_test database)


@pytest.fixture(scope="session", autouse=True)
def _empty_bucket(storage):  # type: ignore[no-untyped-def]  # noqa: F811
    """This run's bucket exists and is empty before anything writes to it (Storage.reset_local_bucket)."""
    return storage


@pytest.fixture(autouse=True)
def _timed_test(request: pytest.FixtureRequest) -> Iterator[None]:
    """A response-time guard knows its test, so it can require the `perf` marker `make perf` selects (BUG-115)."""
    perf.running = request.node
    yield
    perf.running = None
