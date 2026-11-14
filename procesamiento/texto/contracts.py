from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any


ALLOWED_MEDIA_TYPES = {
    "audio/aac",
    "audio/flac",
    "audio/mp3",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
    "audio/wave",
}
SUBJECT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
TRANSCRIPT_SCHEMA_VERSION = "1.0"
MAX_TRANSCRIPT_CHARS = 50_000


def validate_subject_id(subject_id: str) -> str:
    if not SUBJECT_ID_PATTERN.fullmatch(subject_id):
        raise ValueError("subject_id must be a non-empty pseudonymous identifier")
    return subject_id


def normalize_recorded_at(value: str) -> str:
    try:
        recorded_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("recorded_at must be an ISO 8601 timestamp") from error

    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must include a timezone")

    return recorded_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_media_type(value: str) -> str:
    media_type = value.partition(";")[0].strip().lower()
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise ValueError("unsupported audio media type")
    return media_type


def build_transcript_record(
    job_id: str,
    subject_id: str,
    recorded_at: str,
    transcript: str,
    language: str,
    duration_seconds: float,
    classification: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(transcript, str) or len(transcript) > MAX_TRANSCRIPT_CHARS:
        raise ValueError("transcript must be text no longer than 50000 characters")
    if not isinstance(language, str) or not re.fullmatch(r"[a-z]{2,3}", language):
        raise ValueError("language must be a two- or three-letter code")
    if not math.isfinite(duration_seconds) or not 1 <= duration_seconds <= 120:
        raise ValueError("duration_seconds must be between 1 and 120")

    return {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "job_id": job_id,
        "subject_id": validate_subject_id(subject_id),
        "recorded_at": normalize_recorded_at(recorded_at),
        "source": "audio_transcription",
        "language": language,
        "duration_seconds": duration_seconds,
        "transcript": transcript,
        "classification": classification,
    }
