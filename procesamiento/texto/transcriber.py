import os
import subprocess
from typing import Any

from faster_whisper import WhisperModel
import numpy as np

from .contracts import normalize_media_type

MAX_AUDIO_SECONDS = 120
DECODE_TIMEOUT_SECONDS = 30
SAMPLE_RATE = 16_000


class TranscriptionError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class AudioTranscriber:
    def __init__(self) -> None:
        self._model: WhisperModel | None = None
        self._model_size = os.environ.get("WHISPER_MODEL", "small")
        self._language = os.environ.get("WHISPER_LANGUAGE", "en")
        self._compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
        self._model_path = os.environ.get("WHISPER_MODEL_PATH", "/models")

    def load_model(self) -> None:
        self._model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type=self._compute_type,
            download_root=self._model_path,
            cpu_threads=int(os.environ.get("WHISPER_CPU_THREADS", "2")),
            num_workers=1,
        )

    def transcribe(self, audio: bytes, media_type: str) -> dict[str, Any]:
        normalize_media_type(media_type)
        if self._model is None:
            raise RuntimeError("Whisper model was not initialized")
        samples, duration = self._decode(audio)
        try:
            segments, info = self._model.transcribe(
                samples,
                language=self._language,
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            transcript = " ".join(segment.text.strip() for segment in segments).strip()
        except (RuntimeError, ValueError, OSError) as error:
            raise TranscriptionError("Speech transcription failed", "transcription_failed") from error

        return {
            "transcript": transcript,
            "language": info.language,
            "duration_seconds": round(duration, 3),
        }

    @staticmethod
    def _decode(audio: bytes) -> tuple[np.ndarray, float]:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "pipe",
            "-i",
            "pipe:0",
            "-map",
            "0:a:0",
            "-vn",
            "-t",
            str(MAX_AUDIO_SECONDS + 1),
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            "-f",
            "s16le",
            "pipe:1",
        ]
        try:
            result = subprocess.run(
                command,
                input=audio,
                capture_output=True,
                check=False,
                timeout=DECODE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise TranscriptionError("Audio decoding timed out", "audio_decode_timeout") from error
        except OSError as error:
            raise TranscriptionError("Audio decoder is unavailable", "audio_decoder_unavailable") from error

        if result.returncode != 0 or not result.stdout:
            raise TranscriptionError("Audio is invalid or its codec is unsupported", "invalid_audio")

        try:
            samples = np.frombuffer(result.stdout, dtype="<i2").astype(np.float32) / 32768.0
        except ValueError as error:
            raise TranscriptionError("Audio is invalid", "invalid_audio") from error
        duration = samples.size / SAMPLE_RATE

        if duration < 1:
            raise TranscriptionError("Audio must be at least one second long", "audio_too_short")
        if duration > MAX_AUDIO_SECONDS:
            raise TranscriptionError("Audio exceeds the 120 second limit", "audio_too_long")
        return samples, duration
