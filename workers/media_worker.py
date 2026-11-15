"""worker-ml: procesa en memoria las sesiones de audio y vídeo del Redis Stream efímero.

Garantías de privacidad (README, privacidad desde el diseño):
- El audio y el vídeo solo existen en RAM: en el stream de `media-broker` (Redis
  sin AOF ni RDB) y en búferes de este proceso. Nunca se escriben en disco, en
  PostgreSQL ni en los logs.
- La transcripción solo existe mientras se clasifica; no se guarda ni se devuelve.
- Tras procesar un trabajo con éxito: se guardan los números, se hace XACK y XDEL
  y se vacían los búferes. Si el proceso cae antes, el mensaje sigue pendiente en
  el grupo de consumo y se recupera con XAUTOCLAIM al reiniciar (no se pierde).
- Si el contenido no es válido, el trabajo se marca como fallido y el mensaje se
  borra igualmente: no se conserva multimedia por un error.

NLP: desactivado por defecto (ENABLE_NLP=false). El README define categorías de
'ánimo bajo' y 'ansiedad' que rozan la prohibición de inferir emociones del
Reglamento de IA (art. 5.1.f) fuera del uso médico. Hasta que se garantice el
uso restringido previsto, el modelo de texto no se carga y sus cuatro campos del
vector quedan ausentes. Las métricas acústicas sí se calculan.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import time
from typing import Any

import psycopg
import redis

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("worker-ml")

STREAM = "orbivia:media"
GROUP = "worker-ml"
HEARTBEAT_KEY = "orbivia:media:heartbeat"
CLAIM_IDLE_MS = 60_000
SAMPLE_RATE = 16_000

NLP_LABELS = {"neutral": "neutral", "normal": "neutral", "depression": "low_mood", "depressed": "low_mood",
              "anxiety": "anxiety", "anxious": "anxiety", "stable": "stable"}

stopping = False


def _stop(*_: Any) -> None:
    global stopping
    stopping = True


def enabled(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def media_client() -> redis.Redis:
    return redis.Redis(host=os.environ.get("MEDIA_REDIS_HOST", "media-broker"),
                       port=int(os.environ.get("MEDIA_REDIS_PORT", "6379")),
                       socket_connect_timeout=3, socket_timeout=10)


def db() -> psycopg.Connection:
    return psycopg.connect(host=os.environ.get("POSTGRES_HOST", "db"),
                           port=int(os.environ.get("POSTGRES_PORT", "5432")),
                           dbname=os.environ.get("POSTGRES_DB", "orbivia"),
                           user=os.environ.get("ORBIVIA_DB_ENGINE_USER", "orbivia_engine"),
                           password=os.environ["ORBIVIA_DB_ENGINE_PASSWORD"], connect_timeout=5)


class Processors:
    """Modelos cargados una vez. Cada uno es opcional y se informa si falta."""

    def __init__(self) -> None:
        import opensmile

        self.smile = opensmile.Smile(feature_set=opensmile.FeatureSet.eGeMAPSv02,
                                     feature_level=opensmile.FeatureLevel.Functionals)
        self.nlp_enabled = enabled("ENABLE_NLP")
        self.transcriber = self.classifier = None
        if self.nlp_enabled:
            from texto.mental_health_classifier import MentalHealthTextClassifier
            from texto.transcriber import AudioTranscriber

            self.transcriber = AudioTranscriber()
            self.transcriber.load_model()
            self.classifier = MentalHealthTextClassifier()
            self.classifier.load_model()
        self.video = None
        if enabled("ENABLE_VIDEO", "true"):
            try:
                from video.predict_pipeline import VideoPredictionPipeline

                self.video = VideoPredictionPipeline()
            except Exception:  # sin modelo o sin mediapipe: el vídeo queda desactivado
                logger.exception("Pipeline de vídeo no disponible")

    # --- audio -----------------------------------------------------------------------

    @staticmethod
    def decode_audio(payload: bytes):
        from texto.transcriber import AudioTranscriber

        return AudioTranscriber._decode(payload)  # ffmpeg por tuberías, sin ficheros

    def acoustic(self, samples) -> dict[str, float]:
        frame = self.smile.process_signal(samples, SAMPLE_RATE)
        row = frame.iloc[0]
        out = {
            "f0_mean": float(row["F0semitoneFrom27.5Hz_sma3nz_amean"]),
            "pause_mean_s": float(row["MeanUnvoicedSegmentLength"]),
            "voiced_segments_per_s": float(row["VoicedSegmentsPerSec"]),
            "loudness_mean": float(row["loudness_sma3_amean"]),
        }
        return {k: round(v, 5) for k, v in out.items()}

    def nlp(self, payload: bytes, media_type: str) -> dict[str, float] | None:
        if not self.nlp_enabled:
            return None
        transcription = self.transcriber.transcribe(payload, media_type)
        text = transcription["transcript"]
        try:
            if not text.strip():
                return None
            scores = self.classifier.classify(text)["scores"]
        finally:
            transcription["transcript"] = ""
            del text, transcription
        out = {}
        for label, value in scores.items():
            key = NLP_LABELS.get(label.strip().lower())
            if key:
                out[key] = round(float(value), 5)
        return out or None


def process(proc: Processors, fields: dict[bytes, bytes]) -> dict[str, Any]:
    kind = fields[b"kind"].decode()
    media_type = fields[b"media_type"].decode()
    payload = fields[b"payload"]
    if kind == "audio":
        samples, duration = proc.decode_audio(payload)
        try:
            return {"acoustic": {**proc.acoustic(samples), "duration_s": round(duration, 2)},
                    "nlp": proc.nlp(payload, media_type)}
        finally:
            samples.fill(0)
            del samples
    if kind == "video":
        if proc.video is None:
            raise RuntimeError("video_disabled")
        result = proc.video.analyze_bytes(payload)
        # Solo signos físicos de fatiga (Alert / Low Vigilant / Drowsy): no emociones
        return {"video": {"prediction": result["prediction"], "probabilities": result["probabilities"],
                          "windows": result["window_count"], "duration_s": result["duration_seconds"]}}
    raise ValueError("unknown_kind")


def store(job_id: str, status: str, result: dict | None, error: str | None) -> None:
    result = result or {}
    with db() as conn:
        conn.execute(
            "UPDATE biometrics.media_results SET status = %s, acoustic = %s, nlp = %s, video = %s, "
            "error_code = %s, completed_at = now() WHERE job_id = %s",
            (status, json.dumps(result.get("acoustic")) if result.get("acoustic") else None,
             json.dumps(result.get("nlp")) if result.get("nlp") else None,
             json.dumps(result.get("video")) if result.get("video") else None, error, job_id))


def handle(client: redis.Redis, proc: Processors, message_id: bytes, fields: dict[bytes, bytes]) -> None:
    job_id = fields.get(b"job_id", b"").decode()
    try:
        try:
            result, status, error = process(proc, fields), "completed", None
        except Exception as exc:  # contenido no válido: no se reintenta y no se guarda nada
            code = str(exc) if str(exc) in ("video_disabled", "unknown_kind") else type(exc).__name__
            logger.info("Trabajo %s fallido (%s)", job_id, code)  # sin contenido ni transcripción
            result, status, error = None, "failed", code
        store(job_id, status, result, error)  # si falla la BD, el mensaje queda pendiente
        client.xack(STREAM, GROUP, message_id)
        client.xdel(STREAM, message_id)
    finally:
        payload = fields.get(b"payload")
        fields.clear()
        del payload


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    proc = Processors()
    consumer = socket.gethostname()
    logger.info("worker-ml listo (NLP %s, vídeo %s)", "activado" if proc.nlp_enabled else "desactivado",
                "activado" if proc.video else "desactivado")
    while not stopping:
        try:
            client = media_client()
            try:
                client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
            except redis.ResponseError as error:
                if "BUSYGROUP" not in str(error):
                    raise
            while not stopping:
                client.set(HEARTBEAT_KEY, str(time.time()), ex=60)
                # Primero, lo que quedó pendiente de un proceso anterior
                _, claimed, _ = client.xautoclaim(STREAM, GROUP, consumer, min_idle_time=CLAIM_IDLE_MS,
                                                  start_id="0-0", count=5)
                for message_id, fields in claimed:
                    if fields:
                        handle(client, proc, message_id, fields)
                batch = client.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=1, block=5000)
                for _, messages in batch or []:
                    for message_id, fields in messages:
                        handle(client, proc, message_id, fields)
        except (redis.RedisError, psycopg.Error):
            logger.exception("Dependencia no disponible; reintento en 5 s")
            time.sleep(5)


def healthcheck() -> int:
    try:
        beat = media_client().get(HEARTBEAT_KEY)
        return 0 if beat and time.time() - float(beat) < 60 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "healthcheck":
        sys.exit(healthcheck())
    main()
