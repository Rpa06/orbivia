# Inferencia de fatiga desde video

Este directorio contiene el pipeline de inferencia del modelo cinemático del
notebook. Acepta una ruta a un video, extrae rasgos faciales con MediaPipe y
devuelve la predicción del modelo ONNX como JSON. No contiene ni ejecuta código
de entrenamiento.

El modelo del notebook predice **Alert**, **Low Vigilant** y **Drowsy**; no es
un clasificador general de emociones ni una herramienta de diagnóstico clínico.
Las probabilidades son puntuaciones del modelo y no deben interpretarse como
una decisión médica.

## Archivos del modelo

Los siguientes archivos deben permanecer juntos al subir/desplegar el pipeline:

- `drowsiness_kinematic_net.onnx`: grafo ONNX.
- `drowsiness_kinematic_net.onnx.data`: pesos externos requeridos por el grafo.
- `face_landmarker.task`: modelo de MediaPipe Face Landmarker usado para extraer
  los rasgos faciales.

El archivo `.onnx.data` se carga por ONNX Runtime desde el mismo directorio que
el `.onnx`; no se debe renombrar ni separar.

## Instalación y uso

Con Python 3.9 o posterior, instala las dependencias desde la raíz del proyecto:

```powershell
python -m pip install -r procesamiento\video\requirements.txt
python procesamiento\video\predict_pipeline.py ruta\al\video.mp4
```

La salida contiene una predicción agregada y puntuaciones por ventanas de 30
segundos, evaluadas cada 10 segundos. Para integrar el pipeline en un worker,
se puede reutilizar la sesión ONNX:

```python
from procesamiento.video.predict_pipeline import VideoPredictionPipeline

pipeline = VideoPredictionPipeline()
prediction = pipeline.analyze(ruta_del_video)
```

`analyze` recibe la ruta de un archivo legible por OpenCV y devuelve un
diccionario serializable a JSON. También se puede llamar a `analyze_video` si se
prefiere crear una sesión por análisis.

La configuración Docker actual de `worker-ml` no copia `procesamiento/video` a
la imagen. Por la restricción de mantener todos los cambios en este directorio,
el módulo queda listo para invocarse desde un worker, pero activarlo en ese
contenedor requiere añadir allí la copia del módulo y sus modelos.

## Memoria y privacidad

El video se decodifica secuencialmente; nunca se carga completo ni se copia a un
archivo temporal. El pipeline reduce los fotogramas a 160 píxeles de ancho y
mantiene solo la geometría facial necesaria para la ventana actual. La sesión
ONNX usa CPU, ejecución secuencial y un hilo intraoperación por defecto. Los
rasgos intermedios solo viven en memoria y la función devuelve puntuaciones y
metadatos, no fotogramas ni audio.
