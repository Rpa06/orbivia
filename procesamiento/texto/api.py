import os
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .contracts import normalize_recorded_at, validate_subject_id
from .transport import read_audio_body, request_media_type, require_bearer_token

router = APIRouter(prefix="/audio/transcriptions", tags=["audio"])


def _validate_metadata(subject_id: str, recorded_at: str) -> tuple[str, str]:
    try:
        return validate_subject_id(subject_id), normalize_recorded_at(recorded_at)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _worker_url() -> str:
    return os.environ.get("WORKER_ML_URL", "http://worker-ml:8001").rstrip("/")


def _worker_token() -> str:
    token = os.environ.get("AUDIO_WORKER_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="Audio worker authentication is not configured")
    return token


def _response_from_worker(response: httpx.Response) -> JSONResponse:
    try:
        content: Any = response.json()
    except ValueError as error:
        raise HTTPException(status_code=502, detail="Audio worker returned an invalid response") from error

    if response.status_code >= 400:
        status_code = response.status_code if response.status_code < 500 else 502
        detail = content.get("detail", "Audio worker request failed") if isinstance(content, dict) else "Audio worker request failed"
        raise HTTPException(status_code=status_code, detail=detail)
    return JSONResponse(status_code=response.status_code, content=content)


async def _call_worker(
    method: str,
    path: str,
    token: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
) -> httpx.Response:
    worker_headers = {"Authorization": f"Bearer {token}"}
    if headers:
        worker_headers.update(headers)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            return await client.request(
                method,
                f"{_worker_url()}{path}",
                headers=worker_headers,
                content=content,
            )
    except httpx.RequestError as error:
        raise HTTPException(status_code=503, detail="Audio worker is unavailable") from error


@router.post("", status_code=202)
async def submit_audio(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_subject_id: str = Header(..., alias="X-Subject-ID"),
    x_recorded_at: str = Header(..., alias="X-Recorded-At"),
) -> JSONResponse:
    require_bearer_token(authorization, "AUDIO_INGEST_TOKEN")
    subject_id, recorded_at = _validate_metadata(x_subject_id, x_recorded_at)
    media_type = request_media_type(request)
    audio = await read_audio_body(request)
    response = await _call_worker(
        "POST",
        "/internal/text/transcriptions",
        _worker_token(),
        headers={
            "Content-Type": media_type,
            "X-Subject-ID": subject_id,
            "X-Recorded-At": recorded_at,
        },
        content=audio,
    )
    return _response_from_worker(response)


@router.get("/{job_id}")
async def get_audio_transcription(
    job_id: UUID,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> JSONResponse:
    require_bearer_token(authorization, "AUDIO_INGEST_TOKEN")
    response = await _call_worker(
        "GET",
        f"/internal/text/transcriptions/{job_id}",
        _worker_token(),
    )
    return _response_from_worker(response)
