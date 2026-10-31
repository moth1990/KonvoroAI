"""The pipeline's queues (12 §3): one SQS queue per stage, and a shared dead-letter queue after 3 failed receives
(infra/elasticmq.conf). Messages carry IDs only; the data stays in RDS and S3.
"""

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from konboro.settings import Settings

from . import aws

STAGE_QUEUES = {
    1: "konboro-s1-intake",
    2: "konboro-s2-extraction",
    3: "konboro-s3-symbols",
    4: "konboro-s4-association",
    5: "konboro-s5-matching",
    6: "konboro-s6-validation",
    7: "konboro-s7-pricing",
}
DLQ = "konboro-dlq"
MAX_RECEIVES = 3  # then the redrive policy moves the message to the DLQ (infra/elasticmq.conf)


class StageMessage(BaseModel):
    """The whole message. Nothing else may ride along: no file contents, no prices, no customer data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    drawing_id: str = Field(pattern=r"^drw_[0-9A-Z]{26}$")
    tenant_id: str = Field(pattern=r"^tnt_[0-9A-Z]{26}$")
    stage: int = Field(ge=1, le=7)
    trace_id: str = Field(pattern=r"^trc_[0-9A-Z]{26}$")


@dataclass(frozen=True)
class Received:
    message: StageMessage
    receipt: str
    receive_count: int
    queue: str


class Queue:
    def __init__(self, settings: Settings, sqs: Any | None = None) -> None:
        self.sqs = sqs or aws.client("sqs", settings)
        self.prefix = settings.sqs_queue_prefix
        self._urls: dict[str, str] = {}

    def name(self, base: str) -> str:
        return f"{self.prefix}{base}"

    def url(self, base: str) -> str:
        if base not in self._urls:
            self._urls[base] = self.sqs.get_queue_url(QueueName=self.name(base))["QueueUrl"]
        return self._urls[base]

    def ensure(self) -> None:
        """Create the stage queues and the DLQ if missing, with the same redrive policy as infra/elasticmq.conf.
        Tests and E2E use this for their prefixed queues; in AWS the queues come from infrastructure (S29)."""
        dlq_url = self.sqs.create_queue(QueueName=self.name(DLQ))["QueueUrl"]
        dlq_arn = self.sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        redrive = json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": str(MAX_RECEIVES)})
        for base in STAGE_QUEUES.values():
            self.sqs.create_queue(QueueName=self.name(base), Attributes={"RedrivePolicy": redrive})

    def send(self, message: StageMessage) -> None:
        body = message.model_dump_json()
        self.sqs.send_message(QueueUrl=self.url(STAGE_QUEUES[message.stage]), MessageBody=body)

    def receive(self, base: str, wait_s: int = 0, max_messages: int = 1) -> list[Received]:
        """Messages that don't parse as a StageMessage are left for the DLQ, never acted on."""
        response = self.sqs.receive_message(
            QueueUrl=self.url(base),
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_s,
            AttributeNames=["ApproximateReceiveCount"],
        )
        out = []
        for raw in response.get("Messages", []):
            try:
                message = StageMessage.model_validate(json.loads(raw["Body"]))
            except (ValueError, TypeError):
                continue
            count = int(raw.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
            out.append(Received(message, raw["ReceiptHandle"], count, base))
        return out

    def delete(self, received: Received) -> None:
        self.sqs.delete_message(QueueUrl=self.url(received.queue), ReceiptHandle=received.receipt)

    def retry_later(self, received: Received, delay_s: int) -> None:
        """Leave the message on its queue and make it visible again after `delay_s`; SQS counts the receive,
        and the redrive policy moves it to the DLQ after the third."""
        self.sqs.change_message_visibility(
            QueueUrl=self.url(received.queue), ReceiptHandle=received.receipt, VisibilityTimeout=delay_s
        )

    def purge(self, base: str) -> None:
        self.sqs.purge_queue(QueueUrl=self.url(base))
