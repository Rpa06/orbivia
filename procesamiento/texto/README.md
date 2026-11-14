# Transcripción backend

La API recibe audio binario en `POST /audio/transcriptions`, con:

- `Authorization: Bearer <AUDIO_INGEST_TOKEN>`
- `X-Subject-ID`: identificador seudónimo estable usado por el resto del sistema.
- `X-Recorded-At`: fecha ISO 8601 con zona horaria.
- `Content-Type`: WAV, MP3, MP4/M4A, WebM, OGG, FLAC o AAC.
- Cuerpo: audio de 1 a 120 segundos y hasta 25 MiB.

La ruta es un contrato para integrarse con la aplicación futura. El token compartido
es una protección de servicio para pruebas o llamadas desde un backend de confianza;
no debe incluirse en código JavaScript ni entregarse al navegador. La API aún no
dispone de una tabla de personas ni de autenticación por usuario, por lo que valida
el formato del ID, pero no puede comprobar su existencia o autorización. Al conectar
la aplicación se debe vincular la sesión autenticada con el `subject_id` autorizado.
El ID debe ser seudónimo; no usar nombres, correos ni otros datos identificativos.

La API reenvía el audio al servicio interno `worker-ml`. La transcripción se realiza
en este módulo (`procesamiento/texto`) con `faster-whisper` y el modelo Whisper
`small`, ejecutado en CPU con cuantización `int8`. Después, el texto inglés pasa al
clasificador Longformer `Hrishikesh4/mental-health-classifier-longformer`, también
en CPU. FFmpeg decodifica el audio a PCM mono de 16 kHz; ni el audio ni los pesos
del modelo se incluyen en la imagen. Los modelos se descargan al iniciar el worker
y se conservan en un volumen Docker dedicado.

El `POST` devuelve `202` y un `job_id`. Consultar
`GET /audio/transcriptions/{job_id}` con el mismo token para obtener el estado y, al
completar, la transcripción. Los resultados se mantienen solo en memoria durante un
máximo de 24 horas; se pierden si el worker se reinicia.

```json
{
  "schema_version": "1.0",
  "job_id": "uuid",
  "subject_id": "pseudonymous-id",
  "recorded_at": "2026-11-14T08:00:00Z",
  "source": "audio_transcription",
  "language": "en",
  "duration_seconds": 2.5,
  "transcript": "Text recognized by Whisper",
  "classification": {
    "model": "Hrishikesh4/mental-health-classifier-longformer",
    "revision": "54edff7f513b60314a4171c848ebe33c2850039a",
    "problem_type": "multi_label_classification",
    "input_tokens": 12,
    "input_truncated": false,
    "scores": {
      "LABEL_0": 0.12,
      "LABEL_1": 0.71,
      "LABEL_2": 0.24,
      "LABEL_3": 0.08
    }
  }
}
```

Las puntuaciones se calculan con sigmoid porque el modelo es multietiqueta. Se
devuelven como probabilidades crudas por `LABEL_0`–`LABEL_3`: la configuración del
modelo no mapea esos índices a nombres, así que el backend no les asigna por
suposición “neutral”, “depression”, “anxiety” o “stress”, ni aplica un umbral de
decisión. El resultado numérico puede mapearse a un vector tras confirmar el
significado de cada salida y el esquema de destino. Estas puntuaciones no son un
diagnóstico ni una decisión clínica.

Configurar `AUDIO_INGEST_TOKEN`, `AUDIO_WORKER_TOKEN` y opcionalmente
`WHISPER_MODEL` en `.env`; `WHISPER_LANGUAGE` se configura por defecto como `en`.
El modelo de texto está fijado a una revisión concreta
para que sus pesos sean reproducibles. La clave del worker se usa solo entre los
contenedores API y worker. Reconstruir los servicios con
`docker compose up -d --build api worker-ml`.
