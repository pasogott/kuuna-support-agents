from __future__ import annotations

from redis import Redis
from rq import Queue, Retry

from kuuna_backend.config.settings import get_settings

OUTBOUND_DISPATCH_RETRY_INTERVALS = [30, 120, 300]


def get_redis_connection() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url)


def get_default_queue() -> Queue:
    return Queue("default", connection=get_redis_connection())


def enqueue_media_processing(media_asset_id: str, trace_id: str | None = None) -> str:
    queue = get_default_queue()
    normalized_id = media_asset_id.replace("-", "_")
    job = queue.enqueue(
        "kuuna_backend.jobs.media_processing.process_media_asset_job",
        media_asset_id,
        trace_id,
        job_id=f"media_processing_{normalized_id}",
    )
    return job.id


def enqueue_outbound_dispatch(outbound_intent_id: str) -> str:
    queue = get_default_queue()
    normalized_id = outbound_intent_id.replace("-", "_")
    job = queue.enqueue(
        "kuuna_backend.jobs.outbound_dispatch.dispatch_outbound_intent_job",
        outbound_intent_id,
        job_id=f"outbound_dispatch_{normalized_id}",
        retry=Retry(
            max=len(OUTBOUND_DISPATCH_RETRY_INTERVALS),
            interval=OUTBOUND_DISPATCH_RETRY_INTERVALS,
        ),
    )
    return job.id


def enqueue_inbound_execution(
    message_id: str,
    provider_group_id: str,
    reason: str | None = None,
    trace_id: str | None = None,
) -> str:
    queue = get_default_queue()
    normalized_id = message_id.replace("-", "_")
    job = queue.enqueue(
        "kuuna_backend.jobs.ingest.process_inbound_message_job",
        message_id,
        provider_group_id,
        reason,
        trace_id,
        job_id=f"inbound_execution_{normalized_id}",
    )
    return job.id


def enqueue_template_build(build_id: str) -> str:
    queue = get_default_queue()
    normalized_id = build_id.replace("-", "_")
    job = queue.enqueue(
        "kuuna_backend.jobs.template_build.process_template_build_job",
        build_id,
        job_id=f"template_build_{normalized_id}",
    )
    return job.id


def enqueue_knowledge_indexing(knowledge_version_id: str, trace_id: str | None = None) -> str:
    queue = get_default_queue()
    normalized_id = knowledge_version_id.replace("-", "_")
    job = queue.enqueue(
        "kuuna_backend.jobs.indexing.process_knowledge_version_job",
        knowledge_version_id,
        trace_id,
        job_id=f"knowledge_indexing_{normalized_id}",
    )
    return job.id
