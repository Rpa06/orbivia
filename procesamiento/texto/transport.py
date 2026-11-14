import hmac
import os

from fastapi import HTTPException, Request

from .contracts import normalize_media_type

MAX_AUDIO_BYTES = 25 * 1024 * 1024


def require_bearer_token(authorization: str | None, environment_key: str) -> None:
    expected_token = os.environ.get(environment_key, "")
    if not expected_token:
        raise HTTPException(status_code=503, detail="Audio authentication is not configured")

    scheme, separator, supplied_token = (authorization or "").partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(supplied_token, expected_token)
    ):
        raise HTTPException(status_code=401, detail="Invalid bearer token")


async def read_audio_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from error
        if declared_length < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if declared_length > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Audio exceeds the 25 MiB limit")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Audio exceeds the 25 MiB limit")

    if not body:
        raise HTTPException(status_code=400, detail="Audio body is empty")
    return bytes(body)


def request_media_type(request: Request) -> str:
    try:
        return normalize_media_type(request.headers.get("content-type", ""))
    except ValueError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
