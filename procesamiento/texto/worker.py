import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Request

from .contracts import build_transcript_record, normalize_recorded_at, validate_subject_id
from .mental_health_classifier import ClassificationError, MentalHealthTextClassifier
from .transcriber import AudioTranscriber, TranscriptionError
from .transport import read_audio_body, request_media_type, require_bearer_token

logger = logging.getLogger("orbivia.text")
JOB_TTL_SECONDS = 24 * 60 * 60
MAX_RETAINED_JOBS = 1_000
MAX_PENDING_JOBS = 2
MAX_CONCURRENT_UPLOADS = 2


@dataclass(frozen=True, slots=True)
class AudioJob:
    job_id: str
    subject_id: str
    recorded_at: str
    media_type: str
    payload: bytes = field(repr=False)


async def _consume_jobs(
    queue: asyncio.Queue[AudioJob],
    jobs: dict[str, dict[str, Any]],
    transcriber: AudioTranscriber,
    classifier: MentalHealthTextClassifier,
) -> None:
    while True:
        job = await queue.get()
        try:
            jobs[job.job_id]["status"] = "processing"
            transcription = await asyncio.to_thread(
                transcriber.transcribe,
                job.payload,
                job.media_type,
            )
            if transcription["transcript"].strip():
                classification = await asyncio.to_thread(
                    classifier.classify,
                    transcription["transcript"],
                )
            else:
                classification = {
                    "status": "skipped",
                    "reason": "empty_transcript",
                }
            record = build_transcript_record(
                job_id=job.job_id,
                subject_id=job.subject_id,
                recorded_at=job.recorded_at,
                transcript=transcription["transcript"],
                language=transcription["language"],
                duration_seconds=transcription["duration_seconds"],
                classification=classification,
            )
            jobs[job.job_id].update(status="completed", result=record)
        except TranscriptionError as error:
            logger.info("Audio transcription failed for job %s (%s)", job.job_id, error.code)
            jobs[job.job_id].update(status="failed", error_code=error.code)
        except ClassificationError:
            logger.exception("Text classification failed for job %s", job.job_id)
            jobs[job.job_id].update(status="failed", error_code="classification_failed")
        except (ValueError, RuntimeError, OSError, TypeError):
            logger.exception("Unexpected transcription error for job %s", job.job_id)
            jobs[job.job_id].update(status="failed", error_code="transcription_failed")
        finally:
            queue.task_done()
            del job


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.queue = asyncio.Queue(maxsize=MAX_PENDING_JOBS)
    application.state.upload_slots = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)
    application.state.jobs = {}
    transcriber = AudioTranscriber()
    classifier = MentalHealthTextClassifier()
    await asyncio.to_thread(transcriber.load_model)
    await asyncio.to_thread(classifier.load_model)
    consumer = asyncio.create_task(
        _consume_jobs(
            application.state.queue,
            application.state.jobs,
            transcriber,
            classifier,
        )
    )
    try:
        yield
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)


app = FastAPI(title="Orbivia Transcription Worker", version="1.0.0", lifespan=lifespan)


@app.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/internal/text/transcriptions", status_code=202)
async def enqueue_audio(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_subject_id: str = Header(..., alias="X-Subject-ID"),
    x_recorded_at: str = Header(..., alias="X-Recorded-At"),
) -> dict[str, str]:
    require_bearer_token(authorization, "AUDIO_WORKER_TOKEN")
    try:
        subject_id = validate_subject_id(x_subject_id)
        recorded_at = normalize_recorded_at(x_recorded_at)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    media_type = request_media_type(request)
    queue: asyncio.Queue[AudioJob] = request.app.state.queue
    if queue.full():
        raise HTTPException(status_code=429, detail="Audio worker queue is full")

    async with request.app.state.upload_slots:
        if queue.full():
            raise HTTPException(status_code=429, detail="Audio worker queue is full")
        payload = await read_audio_body(request)
        _purge_expired_jobs(request.app.state.jobs)
        if len(request.app.state.jobs) >= MAX_RETAINED_JOBS:
            raise HTTPException(status_code=429, detail="Audio result cache is full")
        job_id = str(uuid4())
        job = AudioJob(job_id, subject_id, recorded_at, media_type, payload)
        request.app.state.jobs[job_id] = {
            "job_id": job_id,
            "subject_id": subject_id,
            "recorded_at": recorded_at,
            "status": "queued",
            "result": None,
            "error_code": None,
            "created_at": time.monotonic(),
        }
        try:
            queue.put_nowait(job)
        except asyncio.QueueFull as error:
            request.app.state.jobs.pop(job_id, None)
            raise HTTPException(status_code=429, detail="Audio worker queue is full") from error

    return {"job_id": job_id, "status": "queued"}


@app.get("/internal/text/transcriptions/{job_id}")
async def get_audio_job(
    job_id: UUID,
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    require_bearer_token(authorization, "AUDIO_WORKER_TOKEN")
    jobs: dict[str, dict[str, Any]] = request.app.state.jobs
    _purge_expired_jobs(jobs)
    job = jobs.get(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Transcription job not found")

    return {
        "job_id": str(job_id),
        "subject_id": job["subject_id"],
        "recorded_at": job["recorded_at"],
        "status": job["status"],
        "result": job["result"],
        "error_code": job["error_code"],
    }


def _purge_expired_jobs(jobs: dict[str, dict[str, Any]]) -> None:
    cutoff = time.monotonic() - JOB_TTL_SECONDS
    expired = [
        job_id
        for job_id, job in jobs.items()
        if job["created_at"] < cutoff
    ]
    for job_id in expired:
        del jobs[job_id]
