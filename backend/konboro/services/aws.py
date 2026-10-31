"""boto3 clients for S3 and SQS. With a local endpoint (S3Mock, ElasticMQ) any credentials work; boto3 still needs
some to sign, so fixed local ones are used there. In AWS the endpoints are unset and the IAM role signs."""

from typing import Any

import boto3

from konboro.settings import Settings


def client(service: str, settings: Settings) -> Any:
    endpoint = settings.s3_endpoint if service == "s3" else settings.sqs_endpoint
    local = {"aws_access_key_id": "local", "aws_secret_access_key": "local"} if endpoint else {}
    return boto3.client(service, region_name=settings.aws_region, endpoint_url=endpoint, **local)
