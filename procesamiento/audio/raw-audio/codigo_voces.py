"""
Señal de bienestar a partir de la voz (4 preguntas abiertas) con wav2vec2.
NO es diagnóstico: produce indicadores orientativos para que un profesional los valore.

Pipeline (solo 4 preguntas, las mismas en calibración y en evaluación):
  pregunta -> audio WAV guardado (00_audios/pregunta_N.wav)
     (a) openSMILE (eGeMAPS) sobre audio crudo
     (b) FFT: espectro, tono (F0), temblor vocal, pausas -> GRÁFICAS (PNG)
     (c) transcripción (Whisper local) -> rasgos de texto / modelo de texto opcional
     (d) wav2vec2 (XLS-R, multilingüe) -> embedding de la voz de cada respuesta
  -> desviaciones respecto a la línea base NEUTRAL PERSONAL (sesiones de calibración)
  -> indicios orientativos de estrés / ansiedad / depresión / neutral
  -> PANEL VISUAL de resultados (resultados.png, se muestra al terminar) + informe.json

Uso (cada astronauta tiene su propio estado neutral e historial):
  python las_voces_7.py calibracion A1                 # 5+ veces, en reposo: construye su neutral
  python las_voces_7.py evaluacion  A1 --phq9 4 --gad7 3 --pss10 12   # cuestionarios opcionales
  python las_voces_7.py resumen                        # tabla + ficha de cada astronauta
  python las_voces_7.py entrenar                       # entrena las cabezas wav2vec2 con etiquetas

Dependencias:
  pip install sounddevice soundfile numpy scipy librosa matplotlib opensmile faster-whisper
  pip install torch transformers scikit-learn joblib          # NUEVO: wav2vec2 y clasificador
  (opcional, modelo de texto) pip install sentence-transformers
"""
from __future__ import annotations

import os
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import argparse
import json
import re
import textwrap
import warnings
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import librosa
import librosa.display
import matplotlib.pyplot as plt
import numpy as np
import opensmile
import sounddevice as sd
import soundfile as sf
from scipy.signal import welch

SR = 16_000
HOP = 160  # 10 ms a 16 kHz
SEGUNDOS_POR_RESPUESTA = 5
CARPETA_DATOS = Path("datos_astronautas")  # una subcarpeta por astronauta: su neutral y su historial
MIN_RESPUESTAS_PARA_BASE = 2  # una sesión con menos respuestas con habla NO entra en la línea base

MOSTRAR_GRAFICAS = True        # abre las ventanas de gráficas al terminar la sesión
GUARDAR_JSON_FOURIER = False   # True = además guarda analisis_fourier.json con los números
MOSTRAR_FOURIER = False        # True = abre también las 5 ventanas de Fourier (los PNG se guardan siempre)

# Solo estas 4 preguntas, tanto en calibración como en evaluación (se compara lo mismo con lo mismo).
PREGUNTAS = [
    "¿Cómo te has sentido en general durante las últimas dos semanas?",
    "Cuéntame cómo has dormido y cómo ha sido tu energía durante el día.",
    "¿Qué cosas te han preocupado últimamente y cómo las llevas?",
    "Háblame de algo que hayas disfrutado o que te haya costado disfrutar.",
]

# ---- wav2vec2 ----
W2V_MODELO = "facebook/wav2vec2-xls-r-300m"  # preentrenado en 128 idiomas (incluye español)
W2V_CAPA = 12                                # capa intermedia (de 24): las capas medias codifican
                                             # mejor lo paralingüístico (emoción, tono) que la última
W2V_Z_MODERADO = 2.0                         # z de distancia al neutral: por encima, "se aleja"
W2V_Z_ALTO = 4.0                             # por encima, "se aleja mucho"
RUTA_MODELO_W2V = CARPETA_DATOS / "modelo_w2v.joblib"
UMBRALES_ETIQUETA = {"depresion": ("phq9", 10), "ansiedad": ("gad7", 10), "estres": ("pss10", 14)}
MIN_POSITIVOS_ENTRENAR = 10
MIN_ASTRONAUTAS_ENTRENAR = 3


# =============================================================== 1. Captura
def grabar(segundos: int, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    print(f"Grabando {segundos}s...")
    audio = sd.rec(int(segundos * SR), samplerate=SR, channels=1, dtype="float32")
    sd.wait()
    sf.write(destino, audio, SR)
    print(f"  Audio guardado: {destino}")
    return destino


def _cargar(wav: Path):
    y, sr = sf.read(wav, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    return y, sr


# =============================================================== 2a. openSMILE
_smile = opensmile.Smile(
    feature_set=opensmile.FeatureSet.eGeMAPSv02,
    feature_level=opensmile.FeatureLevel.Functionals,
)


def rasgos_opensmile(wav: Path) -> dict[str, float]:
    df = _smile.process_file(str(wav))
    return {k: float(v) for k, v in df.iloc[0].to_dict().items()}


# =============================================================== 2b. FFT, tono, temblor, pausas
BANDAS = {
    "b0_500": (0, 500),
    "b500_1k": (500, 1000),
    "b1k_2k": (1000, 2000),
    "b2k_4k": (2000, 4000),
    "b4k_8k": (4000, 8000),
}


def rasgos_espectrales(y: np.ndarray, sr: int) -> dict[str, float]:
    f, p = welch(y, fs=sr, nperseg=min(2048, len(y)))
    total = p.sum() + 1e-12
    out: dict[str, float] = {}
    for nombre, (lo, hi) in BANDAS.items():
        m = (f >= lo) & (f < hi)
        out[f"fft_{nombre}"] = float(p[m].sum() / total)
    out["fft_centroide_hz"] = float((f * p).sum() / total)
    cum = np.cumsum(p) / total
    out["fft_rolloff85_hz"] = float(f[min(np.searchsorted(cum, 0.85), len(f) - 1)])
    out["fft_planitud"] = float(np.exp(np.mean(np.log(p + 1e-12))) / (np.mean(p) + 1e-12))
    lf = p[(f >= 50) & (f < 1000)].sum()
    hf = p[(f >= 1000) & (f < 5000)].sum()
    out["fft_ratio_alfa_db"] = float(10 * np.log10((hf + 1e-12) / (lf + 1e-12)))

    S = np.abs(librosa.stft(y, n_fft=512, hop_length=HOP))
    S = S / (S.sum(axis=0, keepdims=True) + 1e-12)
    flujo = np.sqrt((np.diff(S, axis=1) ** 2).sum(axis=0))
    out["fft_flujo_media"] = float(flujo.mean())
    out["fft_flujo_std"] = float(flujo.std())
    return out


def _espectro_modulacion(serie: np.ndarray, fs: float):
    """FFT de una serie lenta (contorno de F0 o envolvente) tras quitar la deriva."""
    n = len(serie)
    t = np.arange(n)
    serie = serie - np.polyval(np.polyfit(t, serie, 2), t)
    nfft = max(n, 512)
    X = np.abs(np.fft.rfft(serie * np.hanning(n), n=nfft)) ** 2
    fr = np.fft.rfftfreq(nfft, d=1 / fs)
    return fr, X


def _tremor(serie: np.ndarray, fs: float, banda=(3.0, 12.0)) -> tuple[float, float]:
    """(frecuencia dominante en la banda, fracción de potencia en la banda)."""
    if len(serie) < int(fs * 0.5):
        return np.nan, np.nan
    fr, X = _espectro_modulacion(serie, fs)
    m = (fr >= banda[0]) & (fr <= banda[1])
    if not m.any() or X[1:].sum() <= 0:
        return np.nan, np.nan
    return float(fr[m][np.argmax(X[m])]), float(X[m].sum() / X[1:].sum())


def _segmentos_sonoros(sonoro: np.ndarray, min_tramas: int):
    ini = None
    for i, v in enumerate(np.append(sonoro, False)):
        if v and ini is None:
            ini = i
        elif not v and ini is not None:
            if i - ini >= min_tramas:
                yield ini, i
            ini = None


def rasgos_tono_y_temblor(y: np.ndarray, sr: int) -> dict[str, float]:
    f0, sonoro, _ = librosa.pyin(y, fmin=65, fmax=400, sr=sr, hop_length=HOP)
    sonoro = sonoro & ~np.isnan(f0)
    out: dict[str, float] = {"f0_prop_sonora": float(sonoro.mean())}
    if sonoro.sum() < 20:
        return out

    st = 12 * np.log2(np.where(np.isnan(f0), 100.0, f0) / 100.0)  # semitonos vs 100 Hz
    v = st[sonoro]
    out["f0_media_st"] = float(v.mean())
    out["f0_std_st"] = float(v.std())
    out["f0_rango_p5_p95_st"] = float(np.percentile(v, 95) - np.percentile(v, 5))
    # Cambio de tono entre tramas CONSECUTIVAS con voz (si no, los huecos sin voz meten
    # saltos entre sonidos distintos y el rasgo sale inflado).
    consecutivas = sonoro[1:] & sonoro[:-1]
    out["f0_cambio_trama_st"] = (
        float(np.mean(np.abs(np.diff(st))[consecutivas])) if consecutivas.any() else float("nan")
    )

    rms = librosa.feature.rms(y=y, frame_length=400, hop_length=HOP)[0]
    n = min(len(rms), len(st))
    rms_db = 20 * np.log10(rms[:n] + 1e-9)

    fs = sr / HOP
    ft_l, pt_l, fa_l, pa_l = [], [], [], []
    for a, b in _segmentos_sonoros(sonoro[:n], min_tramas=int(0.5 * fs)):
        ft, pt = _tremor(st[a:b], fs)
        fa, pa = _tremor(rms_db[a:b], fs)
        ft_l.append(ft); pt_l.append(pt); fa_l.append(fa); pa_l.append(pa)

    out["temblor_f0_hz"] = media_segura(ft_l)
    out["temblor_f0_potencia"] = media_segura(pt_l)
    out["temblor_amp_hz"] = media_segura(fa_l)
    out["temblor_amp_potencia"] = media_segura(pa_l)
    return out


def pausas_y_ritmo(y: np.ndarray, sr: int, caida_db: float = 35.0,
                   suelo_db: float = -70.0) -> dict[str, float]:
    """Silencio = tramas `caida_db` dB por debajo del nivel típico de habla (percentil 95).
    Es relativo al volumen de la grabación: con un umbral fijo de -40 dB, un micro bajo de
    volumen salía como 100% silencio. `suelo_db` evita tomar el ruido de fondo como habla."""
    win, hop = int(0.025 * sr), int(0.010 * sr)
    if len(y) <= win:
        return {"prop_silencio": float("nan"), "n_pausas_largas": 0.0, "pausa_media_s": 0.0}
    rms = np.array([np.sqrt(np.mean(y[i:i + win] ** 2) + 1e-12)
                    for i in range(0, len(y) - win, hop)])
    db = 20 * np.log10(rms + 1e-12)
    silencio = db < max(np.percentile(db, 95) - caida_db, suelo_db)
    rachas, n = [], 0
    for s in silencio:
        if s:
            n += 1
        elif n:
            rachas.append(n * hop / sr)
            n = 0
    if n:
        rachas.append(n * hop / sr)
    pausas = [r for r in rachas if r > 0.3]
    return {
        "prop_silencio": float(silencio.mean()),
        "n_pausas_largas": float(len(pausas)),
        "pausa_media_s": float(np.mean(pausas)) if pausas else 0.0,
    }


def rasgos_fft(wav: Path) -> dict[str, float]:
    y, sr = _cargar(wav)
    return {**rasgos_espectrales(y, sr), **rasgos_tono_y_temblor(y, sr), **pausas_y_ritmo(y, sr)}


# =============================================================== utilidades numéricas
def media_segura(valores) -> float:
    x = [v for v in valores if v is not None and np.isfinite(v)]
    return float(np.mean(x)) if x else float("nan")


def limpiar_nan(d):
    """Convierte NaN/inf en None (y tipos de numpy en tipos normales) para que el JSON sea válido."""
    if isinstance(d, dict):
        return {k: limpiar_nan(v) for k, v in d.items()}
    if isinstance(d, (list, tuple)):
        return [limpiar_nan(v) for v in d]
    if isinstance(d, np.generic):
        d = d.item()
    if isinstance(d, float) and not np.isfinite(d):
        return None
    return d


# =============================================================== 3. Texto
_whisper = None


def transcribir(wav: Path) -> str:
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel("small", compute_type="int8")  # local
    y, _ = _cargar(wav)
    segs, _ = _whisper.transcribe(y, language="es", vad_filter=True)
    return " ".join(s.text.strip() for s in segs)


_PRON_1P = re.compile(r"\b(yo|me|mi|mí|conmigo|mis)\b", re.I)
_NEG = re.compile(r"\b(nunca|nada|nadie|siempre|fatal|cansad[oa]|agobi\w+|ansios\w+|"
                  r"triste|solo|sola|vac[ií]o|inútil|no puedo|sin ganas)\b", re.I)


def rasgos_texto_lexicos(texto: str) -> dict[str, float]:
    palabras = max(len(texto.split()), 1)
    return {
        "n_palabras": float(palabras),
        "prop_primera_persona": len(_PRON_1P.findall(texto)) / palabras,
        "prop_lexico_negativo": len(_NEG.findall(texto)) / palabras,
    }


class ModeloTexto:
    """
    Embeddings multilingües + regresión logística (estrés, ansiedad, ánimo bajo).
    Necesita datos propios etiquetados con escalas validadas y consentimiento.
    Sin entrenar, NO se debe usar para puntuar.
    """
    DIMS = ("estres", "ansiedad", "animo_bajo")

    def __init__(self, ruta: Path | None = None):
        from sentence_transformers import SentenceTransformer
        import joblib
        self.enc = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        self.cabezas = joblib.load(ruta) if ruta and ruta.exists() else None

    def entrenar(self, textos: list[str], etiquetas: dict[str, np.ndarray], ruta: Path):
        from sklearn.linear_model import LogisticRegression
        from sklearn.calibration import CalibratedClassifierCV
        import joblib
        X = self.enc.encode(textos, normalize_embeddings=True)
        self.cabezas = {}
        for d in self.DIMS:
            base = LogisticRegression(max_iter=1000, class_weight="balanced", C=0.5)
            self.cabezas[d] = CalibratedClassifierCV(base, cv=5).fit(X, etiquetas[d])
        joblib.dump(self.cabezas, ruta)

    def puntuar(self, texto: str) -> dict[str, float] | None:
        if not self.cabezas:
            return None
        x = self.enc.encode([texto], normalize_embeddings=True)
        return {d: float(self.cabezas[d].predict_proba(x)[0, 1]) for d in self.DIMS}


# =============================================================== 3b. wav2vec2 (NUEVO)
class Wav2VecEmbedder:
    """
    Extrae un embedding de la VOZ (no del texto) con wav2vec2 / XLS-R.
    Toma una capa intermedia y resume el tiempo con media y desviación típica -> vector de 2048.
    Se carga una sola vez (la primera vez descarga ~1,2 GB).
    """
    def __init__(self, nombre: str = W2V_MODELO, capa: int = W2V_CAPA):
        import torch
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2Model
        self.torch = torch
        self.fe = Wav2Vec2FeatureExtractor.from_pretrained(nombre)
        self.modelo = Wav2Vec2Model.from_pretrained(nombre).eval()
        self.capa = capa

    def embedding(self, y: np.ndarray) -> np.ndarray:
        torch = self.torch
        entrada = self.fe(y, sampling_rate=SR, return_tensors="pt")
        with torch.no_grad():
            salida = self.modelo(entrada.input_values, output_hidden_states=True)
        h = salida.hidden_states[self.capa][0]            # (tiempo, 1024)
        return np.concatenate([h.mean(0).numpy(), h.std(0).numpy()]).astype(np.float64)


def _coseno(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def desviacion_w2v(emb: np.ndarray, neutrales: list[np.ndarray]) -> float:
    """
    z robusto de la distancia coseno al centroide neutral de la persona.
    La escala sale de las propias sesiones neutrales (cada una frente a las demás).
    """
    N = np.array(neutrales)
    dist = 1.0 - _coseno(emb, N.mean(axis=0))
    loo = np.array([1.0 - _coseno(N[i], np.delete(N, i, axis=0).mean(axis=0))
                    for i in range(len(N))])
    med = float(np.median(loo))
    escala = max(float(np.median(np.abs(loo - med)) * 1.4826), 0.05 * med, 1e-6)
    return float((dist - med) / escala)


def evaluar_w2v(emb: np.ndarray, neutrales: list[np.ndarray]) -> dict:
    """Distancia al neutral (siempre) + probabilidades por estado (solo si hay modelo entrenado)."""
    if len(neutrales) < LineaBase.MIN_SESIONES:
        return {"z": None, "nivel": "sin_calibracion", "probabilidades": None, "auc_cv": None}
    z = desviacion_w2v(emb, neutrales)
    nivel = ("compatible" if z <= W2V_Z_MODERADO
             else "se_aleja" if z <= W2V_Z_ALTO else "se_aleja_mucho")
    probs, auc = None, None
    if RUTA_MODELO_W2V.exists():
        import joblib
        modelo = joblib.load(RUTA_MODELO_W2V)
        x = (emb - np.mean(neutrales, axis=0)).reshape(1, -1)
        probs = {d: float(c.predict_proba(x)[0, 1]) for d, c in modelo["cabezas"].items()}
        auc = modelo.get("auc_cv")
    return {"z": z, "nivel": nivel, "probabilidades": probs, "auc_cv": auc}


def ruta_w2v(astronauta: str) -> Path:
    return rutas_astronauta(astronauta)[0].parent / "w2v_sesiones.json"


def etiquetas_sesion(s: dict) -> dict[str, int | None] | None:
    """Etiqueta por estado a partir de los cuestionarios del día. Calibración = todo negativo."""
    if s["modo"] == "calibracion":
        return {d: 0 for d in UMBRALES_ETIQUETA}
    if all(s.get(campo) is None for campo, _ in UMBRALES_ETIQUETA.values()):
        return None
    return {d: (None if s.get(campo) is None else int(s[campo] >= corte))
            for d, (campo, corte) in UMBRALES_ETIQUETA.items()}


def entrenar_modelo_w2v() -> str:
    """
    Entrena una cabeza (regresión logística) por estado sobre embeddings RELATIVOS al neutral
    de cada astronauta, con etiquetas de PHQ-9 / GAD-7 / PSS-10. Valida con GroupKFold por
    astronauta (nunca se prueba con alguien que estuvo en el entrenamiento).
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    import joblib

    X, grupos = [], []
    Y: dict[str, list] = {d: [] for d in UMBRALES_ETIQUETA}
    for a in listar_astronautas():
        sesiones = cargar_log(ruta_w2v(a))
        E = [np.array(s["embedding"]) for s in sesiones]
        calib = [i for i, s in enumerate(sesiones) if s["modo"] == "calibracion"]
        for i, s in enumerate(sesiones):
            ref = [E[j] for j in calib if j != i]
            etiq = etiquetas_sesion(s)
            if len(ref) < LineaBase.MIN_SESIONES - 1 or etiq is None:
                continue
            X.append(E[i] - np.mean(ref, axis=0))
            grupos.append(a)
            for d in Y:
                Y[d].append(etiq[d])
    if not X:
        return "No hay sesiones con embeddings y etiquetas todavía."

    X, grupos = np.array(X), np.array(grupos)
    cabezas, auc, lineas = {}, {}, [f"Muestras: {len(X)} de {len(set(grupos))} astronautas"]
    for d, y_lista in Y.items():
        ok = np.array([v is not None for v in y_lista])
        y = np.array([v for v in y_lista if v is not None])
        g, Xd = grupos[ok], X[ok]
        pos, neg, n_g = int(y.sum()), int((1 - y).sum()), len(set(g))
        if pos < MIN_POSITIVOS_ENTRENAR or neg < MIN_POSITIVOS_ENTRENAR or n_g < MIN_ASTRONAUTAS_ENTRENAR:
            lineas.append(f"  {d}: NO entrenado (positivos={pos}, negativos={neg}, astronautas={n_g}; "
                          f"mínimo {MIN_POSITIVOS_ENTRENAR}/{MIN_POSITIVOS_ENTRENAR}/{MIN_ASTRONAUTAS_ENTRENAR})")
            continue
        pipe = make_pipeline(StandardScaler(),
                             LogisticRegression(C=0.05, class_weight="balanced", max_iter=2000))
        p = cross_val_predict(pipe, Xd, y, groups=g, cv=GroupKFold(n_splits=min(5, n_g)),
                              method="predict_proba")[:, 1]
        auc[d] = float(roc_auc_score(y, p))
        cabezas[d] = pipe.fit(Xd, y)
        lineas.append(f"  {d}: entrenado, AUC validación por astronauta = {auc[d]:.2f}")
    if cabezas:
        RUTA_MODELO_W2V.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"cabezas": cabezas, "auc_cv": auc}, RUTA_MODELO_W2V)
        lineas.append(f"Modelo guardado en {RUTA_MODELO_W2V}")
    return "\n".join(lineas)


# =============================================================== 4. Línea base personal
def calcular_z(rasgos: dict, historial: list[dict], min_sesiones: int) -> dict[str, float]:
    """
    z robusto (mediana/MAD) de CADA rasgo respecto a un historial de sesiones neutrales.
    Si la persona casi no varía en un rasgo (MAD ~ 0), dividir por el MAD daba z de 1e9 que
    tapaban todo lo demás: se usa una escala mínima del 5% de la mediana.
    """
    z = {}
    for k, v in rasgos.items():
        if v is None or not np.isfinite(v):
            continue
        hist = np.array([h[k] for h in historial if k in h])
        if len(hist) < min_sesiones:
            continue
        med = np.median(hist)
        escala = max(np.median(np.abs(hist - med)) * 1.4826, 0.05 * abs(med))
        if escala < 1e-9:  # historial constante y mediana 0: no hay escala para medir
            continue
        z[k] = float((v - med) / escala)
    return z


class LineaBase:
    """
    Historial de sesiones de UNA persona; compara con mediana/MAD robustas.
    Usar siempre mismo micro, mismo protocolo y, si se puede, misma hora del día.
    """
    MIN_SESIONES = 5

    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self.historial: list[dict[str, float]] = (
            json.loads(self.ruta.read_text(encoding="utf-8")) if self.ruta.exists() else []
        )

    def guardar_sesion(self, rasgos: dict[str, float]):
        limpio = {k: float(v) for k, v in rasgos.items() if v is not None and np.isfinite(v)}
        self.historial.append(limpio)
        self.ruta.write_text(json.dumps(self.historial), encoding="utf-8")

    def todas_las_z(self, rasgos: dict[str, float]) -> dict[str, float]:
        """z de cada rasgo frente al neutral ({} si aún no hay sesiones neutrales suficientes)."""
        if len(self.historial) < self.MIN_SESIONES:
            return {}
        return calcular_z(rasgos, self.historial, self.MIN_SESIONES)

    def desviaciones(self, rasgos: dict[str, float], top: int = 8) -> dict[str, float]:
        z = self.todas_las_z(rasgos)
        return dict(sorted(z.items(), key=lambda kv: -abs(kv[1]))[:top])


# =============================================================== 5. Informe
@dataclass
class Informe:
    texto_scores: dict | None
    rasgos_texto: dict
    audio_desviaciones: dict
    sesiones_en_linea_base: int
    cobertura: str
    avisos: list[str]
    tendencias: dict | None = None
    w2v: dict | None = None


def construir_informe(texto_scores, rasgos_texto, desv_audio, n_hist, n_respuestas,
                      tendencias=None, w2v=None) -> Informe:
    avisos = [
        "Herramienta de apoyo: no diagnostica ni sustituye la valoración profesional.",
        "Las desviaciones son respecto a la propia línea base de la persona, no emociones identificadas.",
        "La voz varía con micrófono, ruido, cansancio y estado físico.",
        "Cualquier desviación alta es motivo para hablar con un profesional, no una conclusión.",
    ]
    if tendencias:
        avisos += [
            "Las tendencias son un índice heurístico (firmas de la literatura frente a TU línea base "
            "neutral), no un modelo validado. Las cifras de rendimiento del informe técnico "
            "(sensibilidad/especificidad ~0,71-0,79) son de modelos entrenados con datos etiquetados "
            "y no se pueden atribuir a este índice.",
            "Estrés y ansiedad leve se solapan fisiológicamente: con la voz sola no se separan con fiabilidad.",
            "Ansiedad y depresión son cuadros persistentes: una sola sesión nunca es concluyente.",
        ]
    if w2v:
        if w2v.get("probabilidades"):
            avisos.append("Las probabilidades de wav2vec2 vienen de un modelo entrenado con TUS datos "
                          "etiquetados; su fiabilidad es la AUC de validación indicada, no más.")
        else:
            avisos.append("wav2vec2 sin modelo entrenado solo mide cuánto se aleja la voz del neutral "
                          "de la persona: NO distingue estrés, ansiedad ni depresión entre sí.")
    if n_hist < LineaBase.MIN_SESIONES:
        avisos.append(
            f"Línea base en construcción: {n_hist}/{LineaBase.MIN_SESIONES} sesiones; "
            "aún no hay desviaciones."
        )
    if n_respuestas < len(PREGUNTAS):
        avisos.append("Datos incompletos: algunas preguntas no se respondieron.")
    return Informe(texto_scores, rasgos_texto, desv_audio, n_hist,
                   f"{n_respuestas}/{len(PREGUNTAS)} respuestas", avisos, tendencias, w2v)


# =============================================================== 6. Módulo de transcripción
def analizar_transcripcion(wavs: list[Path], carpeta: Path,
                           preguntas: list[str] = PREGUNTAS) -> dict:
    """Transcribe cada audio y guarda los resultados textuales por separado."""
    resultados = []

    for i, wav in enumerate(wavs):
        texto = transcribir(wav)
        resultados.append({
            "pregunta": preguntas[i],
            "archivo_audio": wav.name,
            "transcripcion": texto,
            "rasgos_textuales": rasgos_texto_lexicos(texto),
        })
        print(f"  Transcripción {i + 1}: {texto or '[sin texto reconocido]'}")

    texto_completo = " ".join(r["transcripcion"] for r in resultados).strip()
    salida = {"resultados": resultados, "texto_completo": texto_completo}

    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "transcripcion.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return salida


# =============================================================== 7. Módulo de análisis Fourier (gráficas)
def graficar_fourier(y: np.ndarray, sr: int, titulo: str, destino: Path):
    """
    Una figura por respuesta con 6 paneles:
      1. forma de onda                      4. espectrograma (STFT)
      2. FFT directa (con F0 y armónicos)   5. contorno de F0 en el tiempo
      3. densidad espectral (Welch)         6. FFT del contorno de F0 (temblor, 3-12 Hz)
    Devuelve (figura, (frecuencias_welch, potencia_welch_dB)).
    """
    fig, axs = plt.subplots(3, 2, figsize=(14, 11), constrained_layout=True)
    fig.suptitle(titulo, fontsize=13)

    f0, sonoro, _ = librosa.pyin(y, fmin=65, fmax=400, sr=sr, hop_length=HOP)
    sonoro = sonoro & ~np.isnan(f0)
    f0_media = float(np.mean(f0[sonoro])) if sonoro.any() else float("nan")

    t = np.arange(len(y)) / sr
    ax = axs[0, 0]
    ax.plot(t, y, lw=0.5)
    ax.set(title="Forma de onda", xlabel="Tiempo (s)", ylabel="Amplitud")
    ax.grid(alpha=0.3)

    N = len(y)
    mag = np.abs(np.fft.rfft(y * np.hanning(N)))
    frs = np.fft.rfftfreq(N, d=1 / sr)
    mag_db = 20 * np.log10(mag / (mag.max() + 1e-12) + 1e-9)
    ax = axs[0, 1]
    ax.plot(frs, mag_db, lw=0.6)
    if np.isfinite(f0_media):
        for k in range(1, 6):
            if k * f0_media < 4000:
                ax.axvline(k * f0_media, color="tab:red", ls="--", alpha=0.35,
                           label=f"F0 ≈ {f0_media:.0f} Hz y armónicos" if k == 1 else None)
        ax.legend(loc="upper right")
    ax.set(title="Transformada de Fourier (magnitud)", xlabel="Frecuencia (Hz)",
           ylabel="Magnitud (dB rel. al máximo)", xlim=(0, 4000))
    ax.grid(alpha=0.3)

    f_w, p_w = welch(y, fs=sr, nperseg=min(2048, N))
    p_w_db = 10 * np.log10(p_w + 1e-12)
    ax = axs[1, 0]
    ax.plot(f_w, p_w_db)
    for _, (lo, hi) in BANDAS.items():
        ax.axvline(lo, color="gray", lw=0.4, alpha=0.5)
    ax.set(title="Densidad espectral de potencia (Welch) con bandas", xlabel="Frecuencia (Hz)",
           ylabel="dB/Hz", xlim=(0, 8000))
    ax.grid(alpha=0.3)

    S_db = librosa.amplitude_to_db(np.abs(librosa.stft(y, n_fft=512, hop_length=HOP)) + 1e-12,
                                   ref=np.max)
    ax = axs[1, 1]
    img = librosa.display.specshow(S_db, sr=sr, hop_length=HOP, x_axis="time", y_axis="linear", ax=ax)
    ax.set(title="Espectrograma", ylim=(0, min(8000, sr / 2)))
    fig.colorbar(img, ax=ax, format="%+2.0f dB")

    tf = librosa.times_like(f0, sr=sr, hop_length=HOP)
    ax = axs[2, 0]
    ax.plot(tf, np.where(sonoro, f0, np.nan), ".", ms=3)
    ax.set(title="Contorno de F0 (tono)", xlabel="Tiempo (s)", ylabel="F0 (Hz)")
    ax.grid(alpha=0.3)

    ax = axs[2, 1]
    fs = sr / HOP
    tramos = list(_segmentos_sonoros(sonoro, min_tramas=int(0.5 * fs)))
    if tramos:
        a, b = max(tramos, key=lambda ab: ab[1] - ab[0])
        serie = 12 * np.log2(f0[a:b] / 100.0)
        fr, X = _espectro_modulacion(serie, fs)
        m = (fr > 0) & (fr <= 15)
        ax.plot(fr[m], X[m] / (X[m].max() + 1e-12))
        ax.axvspan(3, 12, color="tab:orange", alpha=0.15, label="banda de temblor 3-12 Hz")
        ax.legend(loc="upper right")
        ax.set(title="FFT del contorno de F0 (temblor vocal)", xlabel="Frecuencia de modulación (Hz)",
               ylabel="Potencia normalizada")
    else:
        ax.text(0.5, 0.5, "Sin tramo sonoro continuo ≥ 0,5 s\n(graba más tiempo o habla sin pausas)",
                ha="center", va="center", transform=ax.transAxes)
        ax.set(title="FFT del contorno de F0 (temblor vocal)")
    ax.grid(alpha=0.3)

    fig.savefig(destino, dpi=150)
    return fig, (f_w, p_w_db)


def analizar_fourier(wavs: list[Path], carpeta: Path,
                     preguntas: list[str] = PREGUNTAS) -> dict:
    """Calcula rasgos acústicos (para la línea base) y dibuja las transformadas de Fourier."""
    carpeta.mkdir(parents=True, exist_ok=True)
    resultados = []
    welch_resp = []

    for i, wav in enumerate(wavs):
        y, sr = _cargar(wav)
        if len(y) == 0:
            raise ValueError(f"El archivo de audio está vacío: {wav}")

        fig, espectro = graficar_fourier(
            y, sr,
            titulo=f"Respuesta {i + 1}: {preguntas[i]}",
            destino=carpeta / f"fourier_resp_{i + 1}.png",
        )
        welch_resp.append(espectro)
        if not MOSTRAR_FOURIER:
            plt.close(fig)

        resultados.append({
            "respuesta": i + 1,
            "pregunta": preguntas[i],
            "archivo_audio": wav.name,
            "caracteristicas_fourier_y_prosodia": rasgos_fft(wav),
            "caracteristicas_opensmile_egemaps": rasgos_opensmile(wav),
        })

    fig, ax = plt.subplots(figsize=(11, 5), constrained_layout=True)
    for i, (f_w, p_db) in enumerate(welch_resp):
        ax.plot(f_w, p_db, label=f"Respuesta {i + 1}", alpha=0.85)
    ax.set(title="Comparación del espectro entre respuestas", xlabel="Frecuencia (Hz)",
           ylabel="dB/Hz", xlim=(0, 5000))
    ax.grid(alpha=0.3)
    ax.legend()
    fig.savefig(carpeta / "comparacion_espectros.png", dpi=150)
    if not MOSTRAR_FOURIER:
        plt.close(fig)

    salida = {"resultados": resultados}
    if GUARDAR_JSON_FOURIER:
        (carpeta / "analisis_fourier.json").write_text(
            json.dumps(limpiar_nan(salida), ensure_ascii=False, indent=2), encoding="utf-8")
    return salida


# =============================================================== 7b. Tendencias: estrés / ansiedad / depresión
# Las "firmas" salen de la tabla del informe técnico (Biomarcadores Vocales en Salud Mental).
# Cada estado se describe con los mismos GRUPOS de la tabla (tono, ritmo y pausas, intensidad,
# perturbación jitter/shimmer, espectro) y cada grupo con una lista de (rasgo, signo):
#   +1 = se espera que SUBA respecto al neutral de esa persona; -1 = que BAJE.
# El estado NEUTRAL no tiene firma: es la propia línea base (sesiones de calibración).
FIRMAS = {
    "estres": {
        "tono": [("f0_media_st", +1), ("f0_cambio_trama_st", +1)],
        "ritmo_pausas": [("VoicedSegmentsPerSec", +1), ("prop_silencio", -1)],
        "intensidad": [("loudness_sma3_amean", +1), ("loudness_sma3_stddevNorm", +1),
                       ("loudnessPeaksPerSec", +1)],
        "perturbacion": [("jitterLocal_sma3nz_amean", +1), ("shimmerLocaldB_sma3nz_amean", +1)],
        "espectro": [("alphaRatioV_sma3nz_amean", +1), ("hammarbergIndexV_sma3nz_amean", +1),
                     ("fft_centroide_hz", +1)],
    },
    "ansiedad": {
        "tono": [("f0_media_st", +1)],
        "ritmo_pausas": [("n_pausas_largas", +1), ("StddevUnvoicedSegmentLength", +1)],
        "intensidad": [("loudness_sma3_stddevNorm", +1)],
        "perturbacion": [("jitterLocal_sma3nz_amean", +1), ("shimmerLocaldB_sma3nz_amean", +1),
                         ("temblor_f0_potencia", +1), ("temblor_amp_potencia", +1)],
        "espectro": [("fft_b4k_8k", +1), ("fft_flujo_std", +1)],
    },
    "depresion": {
        "tono": [("f0_media_st", -1), ("f0_std_st", -1), ("f0_rango_p5_p95_st", -1),
                 ("f0_cambio_trama_st", -1)],
        "ritmo_pausas": [("prop_silencio", +1), ("pausa_media_s", +1),
                         ("VoicedSegmentsPerSec", -1), ("MeanUnvoicedSegmentLength", +1)],
        "intensidad": [("loudness_sma3_amean", -1), ("loudness_sma3_stddevNorm", -1),
                       ("loudness_sma3_pctlrange0-2", -1)],
        "perturbacion": [("jitterLocal_sma3nz_amean", +1), ("shimmerLocaldB_sma3nz_amean", +1)],
        "espectro": [("alphaRatioV_sma3nz_amean", -1), ("hammarbergIndexV_sma3nz_amean", -1),
                     ("fft_centroide_hz", -1), ("fft_rolloff85_hz", -1)],
    },
}
NOMBRE_ESTADO = {"estres": "estrés", "ansiedad": "ansiedad", "depresion": "ánimo bajo/depresión"}

# Parámetros del índice. Son puntos de partida: hay que calibrarlos con datos etiquetados.
Z_MAX = 3.0
COBERTURA_MINIMA = 0.6
MARGEN_TECHO = 0.25
PASO_NIVEL = 0.5
VENTANA_PERSISTENCIA = 5
SESIONES_PARA_PERSISTENCIA = 3
DESVIACION_GLOBAL_MAX = 1.5
NIVELES_CON_INDICIO = ("indicio_debil", "indicio_moderado", "indicio_marcado")


def indices_tendencia(z: dict[str, float]) -> dict[str, dict]:
    """
    Índice de cada estado = media de los grupos; cada grupo = media de (signo * z) de sus rasgos.
    Positivo = la voz se parece a la firma de ese estado frente al neutral de la persona.
    """
    res = {}
    for estado, grupos in FIRMAS.items():
        por_grupo, usados, total = {}, 0, 0
        for grupo, rasgos in grupos.items():
            vals = []
            for rasgo, signo in rasgos:
                total += 1
                if rasgo in z:
                    usados += 1
                    vals.append(signo * float(np.clip(z[rasgo], -Z_MAX, Z_MAX)))
            if vals:
                por_grupo[grupo] = float(np.mean(vals))
        cobertura = usados / total
        # El índice mide "cuánto se PARECE la voz a la firma de este estado". Si la voz se
        # parece menos que en reposo, no existe "ansiedad negativa": simplemente no se parece
        # (índice 0). Por eso nunca baja de 0. (Los grupos conservan su signo para ordenar
        # qué grupo aporta más.)
        indice = (max(0.0, float(np.mean(list(por_grupo.values()))))
                  if por_grupo and cobertura >= COBERTURA_MINIMA else None)
        res[estado] = {"indice": indice, "por_grupo": por_grupo, "cobertura": round(cobertura, 2)}
    return res


def rango_neutral(historial: list[dict], min_sesiones: int) -> dict[str, list[float]] | None:
    """
    Índice de cada estado en las PROPIAS sesiones neutrales (cada una frente a las demás).
    Dice cuánto "parece" estrés/ansiedad/depresión la voz de esa persona cuando está en reposo.
    """
    por_estado: dict[str, list[float]] = {e: [] for e in FIRMAS}
    for i, sesion_i in enumerate(historial):
        resto = historial[:i] + historial[i + 1:]
        if len(resto) < min_sesiones:
            return None
        for estado, d in indices_tendencia(calcular_z(sesion_i, resto, min_sesiones)).items():
            if d["indice"] is not None:
                por_estado[estado].append(d["indice"])
    return por_estado


def nivel_por_techo(indice: float | None, techo: float | None) -> str:
    if indice is None:
        return "sin_datos"
    if techo is None:
        return "sin_calibracion"
    exceso = indice - techo
    if exceso <= 0:
        return "sin_senal"
    if exceso <= PASO_NIVEL:
        return "indicio_debil"
    if exceso <= 2 * PASO_NIVEL:
        return "indicio_moderado"
    return "indicio_marcado"


def persistencia(estado: str, nivel_actual: str, log: list[dict]) -> dict:
    """Estrés puede ser agudo; ansiedad y depresión solo cuentan si se repiten en varias sesiones."""
    previas = [s["tendencias"]["estados"][estado]["nivel"] for s in log
               if s.get("modo") == "evaluacion" and s.get("tendencias")
               and estado in s["tendencias"].get("estados", {})]
    niveles = previas[-(VENTANA_PERSISTENCIA - 1):] + [nivel_actual]
    con_indicio = sum(n in NIVELES_CON_INDICIO for n in niveles)
    if nivel_actual not in NIVELES_CON_INDICIO:
        patron = "sin indicio hoy"
    elif con_indicio >= SESIONES_PARA_PERSISTENCIA:
        patron = "sostenido"
    else:
        patron = "aislado"
    return {"sesiones_con_indicio": con_indicio, "de": len(niveles), "patron": patron}


def evaluar_tendencias(audio_medio: dict, base: LineaBase, log: list[dict]) -> dict | None:
    """None si todavía no hay sesiones neutrales suficientes para comparar."""
    z = base.todas_las_z(audio_medio)
    if not z:
        return None
    rango = rango_neutral(base.historial, LineaBase.MIN_SESIONES - 1)
    estados = {}
    for estado, d in indices_tendencia(z).items():
        techo = (max(rango[estado]) + MARGEN_TECHO) if rango and rango[estado] else None
        nivel = nivel_por_techo(d["indice"], techo)
        estados[estado] = {
            "indice": d["indice"], "techo_neutral": techo, "nivel": nivel,
            "cobertura": d["cobertura"],
            "grupos_que_mas_aportan": [g for g, v in sorted(d["por_grupo"].items(),
                                                           key=lambda kv: -kv[1])[:2] if v > 0],
            "persistencia": persistencia(estado, nivel, log),
        }
    desviacion_global = float(np.median(np.abs(list(z.values()))))
    return {"estados": estados, "desviacion_global": desviacion_global,
            "lectura": lectura_tendencias(estados, desviacion_global)}


def lectura_tendencias(estados: dict, desviacion_global: float) -> list[str]:
    """Texto prudente: habla de indicios y de patrones, nunca de diagnósticos."""
    if any(d["nivel"] in ("sin_datos", "sin_calibracion") for d in estados.values()):
        return ["No hay datos suficientes para comparar con el estado neutral."]
    activos = [e for e, d in estados.items() if d["nivel"] in NIVELES_CON_INDICIO]
    if not activos:
        if desviacion_global <= DESVIACION_GLOBAL_MAX:
            return ["Compatible con el estado neutral de esta persona."]
        return [f"Sin indicios de los estados evaluados, pero la voz se aleja del neutral en general "
                f"(desviación global {desviacion_global:.1f}): pueden influir cansancio, ruido o el micro."]
    lineas = []
    for e in sorted(activos, key=lambda x: -estados[x]["indice"]):
        d = estados[e]
        pers = d["persistencia"]
        txt = (f"{NOMBRE_ESTADO[e]}: {d['nivel'].replace('_', ' ')} "
               f"({pers['patron']}, {pers['sesiones_con_indicio']}/{pers['de']} sesiones)")
        if e in ("ansiedad", "depresion") and pers["patron"] == "aislado":
            txt += " - una sola sesión, no concluyente"
        if d["grupos_que_mas_aportan"]:
            txt += "; destacan: " + ", ".join(d["grupos_que_mas_aportan"])
        lineas.append(txt)
    if "estres" in activos and "ansiedad" in activos:
        lineas.append("Estrés y ansiedad se solapan: con la voz sola no se pueden distinguir.")
    return lineas


def comprobar_calibracion(historial: list[dict]) -> list[str]:
    """Avisa si las sesiones neutrales son tan variables que la línea base no es fiable."""
    if len(historial) < LineaBase.MIN_SESIONES:
        return []
    rango = rango_neutral(historial, LineaBase.MIN_SESIONES - 1)
    if not rango:
        return []
    lineas = ["Calibración: índice máximo de tus propias sesiones neutrales -> "
              + ", ".join(f"{NOMBRE_ESTADO[e]} {max(v):.2f}" for e, v in rango.items() if v)]
    if any(v and max(v) > 1.0 for v in rango.values()):
        lineas.append("Tus sesiones neutrales son muy variables (índice > 1,0): repite la calibración "
                      "con el mismo micro, la misma hora y en silencio.")
    return lineas


# =============================================================== 7c. Datos por astronauta
def _nombre_seguro(astronauta: str) -> str:
    return re.sub(r"[^\w\-]", "_", astronauta.strip()) or "astronauta_1"


def rutas_astronauta(astronauta: str) -> tuple[Path, Path]:
    """(línea base neutral, historial de sesiones) de ESE astronauta. Cada uno tiene los suyos."""
    carpeta = CARPETA_DATOS / _nombre_seguro(astronauta)
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / "linea_base_neutral.json", carpeta / "historial_sesiones.json"


def cargar_log(ruta: Path) -> list[dict]:
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []


def guardar_en_log(ruta: Path, log: list[dict], entrada: dict):
    log.append(limpiar_nan(entrada))
    ruta.write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")


def listar_astronautas() -> list[str]:
    if not CARPETA_DATOS.exists():
        return []
    return sorted(p.name for p in CARPETA_DATOS.iterdir() if p.is_dir())


def avisos_cuestionarios(phq9: int | None, gad7: int | None) -> list[str]:
    return [f"{nombre} = {valor} (corte clínico >= 10): derivar a un profesional con independencia "
            "de lo que diga la voz."
            for nombre, valor in (("PHQ-9", phq9), ("GAD-7", gad7)) if valor is not None and valor >= 10]


# =============================================================== 7d. Valoración en texto (ficha por astronauta)
ANCHO = 68
NOMBRE_TARJETA = {"depresion": "Depresión", "ansiedad": "Ansiedad", "estres": "Estrés"}
ETIQUETA_NIVEL = {"sin_senal": "SIN SEÑAL", "indicio_debil": "INDICIO DÉBIL",
                  "indicio_moderado": "INDICIO MODERADO", "indicio_marcado": "INDICIO MARCADO",
                  "sin_datos": "SIN DATOS", "sin_calibracion": "SIN CALIBRAR"}
ETIQUETA_CORTA = {"sin_senal": "sin señal", "indicio_debil": "débil", "indicio_moderado": "moderado",
                  "indicio_marcado": "marcado", "sin_datos": "sin datos", "sin_calibracion": "sin calibrar"}
BARRA_NIVEL = {"sin_senal": 0, "indicio_debil": 3, "indicio_moderado": 6, "indicio_marcado": 10}
ETIQUETA_W2V = {"compatible": "COMPATIBLE con su neutral", "se_aleja": "SE ALEJA del neutral",
                "se_aleja_mucho": "SE ALEJA MUCHO del neutral", "sin_calibracion": "SIN CALIBRAR"}


def _barra(nivel: str) -> str:
    n = BARRA_NIVEL.get(nivel, 0)
    return "[" + "#" * n + "." * (10 - n) + "]"


def _parrafo(texto: str, sangria: str = " > ") -> str:
    return textwrap.fill(texto, width=ANCHO, initial_indent=sangria,
                         subsequent_indent=" " * len(sangria))


def estado_base(tendencias: dict | None) -> tuple[str, str]:
    """(etiqueta corta, texto largo) de si la voz sigue pareciéndose a su estado neutral."""
    if not tendencias:
        return "sin datos", "SIN DATOS"
    hay_indicio = any(d["nivel"] in NIVELES_CON_INDICIO for d in tendencias["estados"].values())
    if not hay_indicio and tendencias["desviacion_global"] <= DESVIACION_GLOBAL_MAX:
        return "compatible", "COMPATIBLE con su estado neutral"
    if not hay_indicio:
        return "se aleja", "SE ALEJA del neutral, sin patrón claro"
    return "se aleja", "SE ALEJA del neutral"


def lineas_w2v(w2v: dict | None) -> list[str]:
    if not w2v:
        return []
    L = [f" {'wav2vec2 (voz)':<22} {ETIQUETA_W2V.get(w2v['nivel'], w2v['nivel'])}"]
    if w2v.get("z") is not None:
        L.append(f" {'':<22} distancia al neutral: z = {w2v['z']:+.1f}")
    p = w2v.get("probabilidades")
    if p:
        auc = w2v.get("auc_cv") or {}
        for d, v in p.items():
            a = f" (AUC val. {auc[d]:.2f})" if d in auc else ""
            L.append(f" {'':<22} P({NOMBRE_TARJETA[d].lower()}) = {v:.2f}{a}")
    elif w2v.get("z") is not None:
        L.append(f" {'':<22} sin modelo entrenado: no distingue entre estados")
    L.append("-" * ANCHO)
    return L


def tarjeta_astronauta(astronauta: str, fecha: str, tendencias: dict | None, n_respuestas: int,
                       n_neutrales: int, phq9: int | None = None, gad7: int | None = None,
                       w2v: dict | None = None) -> str:
    """Ficha de una sesión: estado base, depresión, ansiedad y estrés, en texto plano."""
    L = ["=" * ANCHO, f" VALORACIÓN VOCAL | {astronauta} | {fecha}", "=" * ANCHO]
    if not tendencias:
        if n_neutrales < LineaBase.MIN_SESIONES:
            L.append(_parrafo(
                f"Sin datos suficientes para valorar. Sesiones neutrales guardadas: "
                f"{n_neutrales}/{LineaBase.MIN_SESIONES}. Haz primero la calibración "
                "(modo calibracion) para fijar su estado neutral.", " "))
        else:
            L.append(_parrafo("No se pudo calcular la valoración: revisa que haya habla en las "
                              "respuestas.", " "))
    else:
        _, largo = estado_base(tendencias)
        L.append(f" {'Estado base (neutral)':<22} {largo}")
        L.append(f" {'':<22} desviación global respecto a su neutral: "
                 f"{tendencias['desviacion_global']:.1f}")
        L.append("-" * ANCHO)
        for e in ("depresion", "ansiedad", "estres"):
            d = tendencias["estados"][e]
            L.append(f" {NOMBRE_TARJETA[e]:<22} {_barra(d['nivel'])} {ETIQUETA_NIVEL[d['nivel']]}")
            if d["indice"] is not None and d["techo_neutral"] is not None:
                det = f"índice {d['indice']:.2f} (techo de su neutral {d['techo_neutral']:.2f})"
            else:
                det = "datos insuficientes"
            if d["nivel"] in NIVELES_CON_INDICIO:
                p = d["persistencia"]
                det += f" | {p['patron']} ({p['sesiones_con_indicio']}/{p['de']} sesiones)"
                if e != "estres" and p["patron"] == "aislado":
                    det += " | no concluyente"
                if d["grupos_que_mas_aportan"]:
                    det += " | destacan: " + ", ".join(d["grupos_que_mas_aportan"])
            L.append(textwrap.fill(det, width=ANCHO, initial_indent=" " * 5,
                                   subsequent_indent=" " * 7))
        L.append("-" * ANCHO)
        L += lineas_w2v(w2v)
        L += [_parrafo(linea) for linea in tendencias["lectura"]]
    if not tendencias and w2v:
        L += lineas_w2v(w2v)
    L += [_parrafo("ATENCIÓN: " + a) for a in avisos_cuestionarios(phq9, gad7)]
    L.append("-" * ANCHO)
    L.append(_parrafo(f"Respuestas con habla: {n_respuestas}/{len(PREGUNTAS)}. Orientativo: no es un "
                      "diagnóstico; ante cualquier indicio, valoración profesional.", " "))
    L.append("=" * ANCHO)
    return "\n".join(L)


def tarjeta_calibracion(astronauta: str, fecha: str, n_neutrales: int, guardada: bool,
                        extra: list[str]) -> str:
    L = ["=" * ANCHO, f" CALIBRACIÓN NEUTRAL | {astronauta} | {fecha}", "=" * ANCHO]
    if guardada:
        L.append(f" Sesión neutral guardada. Total: {n_neutrales}/{LineaBase.MIN_SESIONES} "
                 "(mínimo para poder evaluar).")
    L += [_parrafo(e) for e in extra]
    if n_neutrales >= LineaBase.MIN_SESIONES:
        L.append(" Ya se puede evaluar a este astronauta (modo evaluacion).")
    L.append("=" * ANCHO)
    return "\n".join(L)


def resumen_todos() -> str:
    """Tabla con todos los astronautas y, debajo, la ficha individual de cada uno."""
    astronautas = listar_astronautas()
    if not astronautas:
        return (f"No hay datos todavía en {CARPETA_DATOS}. Empieza con: "
                "python las_voces_7.py calibracion A1")
    filas, tarjetas = [], []
    for a in astronautas:
        ruta_base, ruta_log = rutas_astronauta(a)
        n_neutrales = len(json.loads(ruta_base.read_text(encoding="utf-8"))) if ruta_base.exists() else 0
        evals = [s for s in cargar_log(ruta_log) if s.get("modo") == "evaluacion" and s.get("tendencias")]
        ult = evals[-1] if evals else None
        tend = ult["tendencias"] if ult else None
        fecha = ult["fecha"].replace("T", " ") if ult else "-"
        niv = (lambda e: ETIQUETA_CORTA[tend["estados"][e]["nivel"]]) if tend else (lambda e: "-")
        filas.append(f"{a:<14}{estado_base(tend)[0]:<12}{niv('depresion'):<14}"
                     f"{niv('ansiedad'):<14}{niv('estres'):<14}{fecha}")
        tarjetas.append(tarjeta_astronauta(
            a, fecha, tend, ult["n_respuestas"] if ult else 0, n_neutrales,
            ult.get("phq9") if ult else None, ult.get("gad7") if ult else None,
            ult.get("w2v") if ult else None))
    cab = f"{'ASTRONAUTA':<14}{'BASE':<12}{'DEPRESIÓN':<14}{'ANSIEDAD':<14}{'ESTRÉS':<14}ÚLTIMA SESIÓN"
    return "\n".join(["RESUMEN DE ASTRONAUTAS (última evaluación de cada uno)", cab, "-" * len(cab),
                      *filas, "", *tarjetas])


# =============================================================== 7e. Panel visual de resultados
COLOR_NIVEL = {"sin_senal": "#2e9e5b", "indicio_debil": "#e8c02a", "indicio_moderado": "#f08a24",
               "indicio_marcado": "#d9342b", "sin_datos": "#9aa0a6", "sin_calibracion": "#9aa0a6"}
COLOR_ESTADO = {"depresion": "#3b5bdb", "ansiedad": "#c2255c", "estres": "#0b7285"}
VALOR_NIVEL = {"sin_senal": 0, "indicio_debil": 1, "indicio_moderado": 2, "indicio_marcado": 3}
ORDEN_ESTADOS = ("depresion", "ansiedad", "estres")
SESIONES_EN_GRAFICA = 12


def _etiquetas_sesion(entradas: list[dict]) -> list[str]:
    return [s["fecha"][5:16].replace("T", "\n") for s in entradas]


def _sin_datos(ax, texto: str):
    ax.axis("off")
    ax.text(0.5, 0.5, textwrap.fill(texto, 40), ha="center", va="center", fontsize=12,
            color="#555", transform=ax.transAxes)


def graficar_resultados(astronauta: str, fecha: str, tendencias: dict | None, w2v: dict | None,
                        log: list[dict], n_respuestas: int, destino: Path):
    """
    Panel de una evaluación (3 paneles):
      A. medidor por estado: un punto sobre una escala de 4 zonas (sin señal / débil /
         moderado / marcado). Cuanto más a la derecha, más se parece la voz a ese estado.
      B. semáforo del estado base (+ línea de wav2vec2 en texto)
      C. evolución por sesión de los tres índices (¿mejora, se mantiene o empeora?)
    """
    fig = plt.figure(figsize=(14, 8.5), constrained_layout=True)
    gs = fig.add_gridspec(2, 2)
    fig.suptitle(f"Valoración vocal  |  {astronauta}  |  {fecha}", fontsize=16, fontweight="bold")
    fig.supxlabel("Orientativo: no es un diagnóstico. Ante cualquier indicio, valoración profesional.",
                  fontsize=10, color="#666")
    evals = [s for s in log if s.get("modo") == "evaluacion" and s.get("tendencias")]

    # --- A. indicios frente al neutral
    ax = fig.add_subplot(gs[0, 0])
    ax.set_title("¿Se parece su voz a algún estado?", fontsize=13, loc="left")
    if tendencias:
        # Escala común: posición = índice - techo de su propio neutral.
        #   <= 0 : dentro de lo normal en reposo (sin señal)
        #   0..1 paso : indicio débil | 1..2 pasos : moderado | > 2 pasos : marcado
        x_min, x_max = -PASO_NIVEL, 3 * PASO_NIVEL
        zonas = [(x_min, 0.0, "sin_senal", "Sin señal"),
                 (0.0, PASO_NIVEL, "indicio_debil", "Débil"),
                 (PASO_NIVEL, 2 * PASO_NIVEL, "indicio_moderado", "Moderado"),
                 (2 * PASO_NIVEL, x_max, "indicio_marcado", "Marcado")]
        n = len(ORDEN_ESTADOS)
        for i, e in enumerate(ORDEN_ESTADOS):
            d = tendencias["estados"][e]
            y = n - 1 - i
            for lo, hi, nivel, _ in zonas:
                ax.barh(y, hi - lo, left=lo, height=0.55, color=COLOR_NIVEL[nivel], alpha=0.28,
                        edgecolor="white", lw=2)
            if d["indice"] is None or d["techo_neutral"] is None:
                ax.text((x_min + x_max) / 2, y, "sin datos suficientes", ha="center", va="center",
                        fontsize=11, color="#555")
                continue
            pos = float(np.clip(d["indice"] - d["techo_neutral"], x_min + 0.04, x_max - 0.04))
            ax.plot(pos, y, "o", ms=20, color=COLOR_NIVEL[d["nivel"]], mec="#222", mew=2, zorder=3)
            ax.text(x_max + 0.06, y, ETIQUETA_NIVEL[d["nivel"]], va="center", fontsize=11,
                    fontweight="bold", color="#222")
        for lo, hi, nivel, nombre in zonas:
            ax.text((lo + hi) / 2, n - 0.42, nombre, ha="center", va="bottom", fontsize=10,
                    color="#444")
        ax.set_yticks(range(n))
        ax.set_yticklabels([NOMBRE_TARJETA[e] for e in reversed(ORDEN_ESTADOS)], fontsize=13)
        ax.set_xticks([])
        ax.set_xlim(x_min, x_max + 0.9)
        ax.set_ylim(-0.6, n - 0.1)
        for lado in ("top", "right", "bottom", "left"):
            ax.spines[lado].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.set_xlabel("Más a la derecha = la voz se parece más a ese estado que en su reposo",
                      fontsize=10, color="#555")
    else:
        _sin_datos(ax, "Sin datos suficientes: hacen falta 5 calibraciones guardadas para valorar.")

    # --- B. semáforo del estado base
    ax = fig.add_subplot(gs[0, 1])
    ax.axis("off")
    corto, _ = estado_base(tendencias)
    color, oscuro, palabra = {
        "compatible": (COLOR_NIVEL["sin_senal"], "#1b6b3a", "COMPATIBLE"),
        "se aleja": (COLOR_NIVEL["indicio_moderado"], "#b35c00", "SE ALEJA"),
    }.get(corto, (COLOR_NIVEL["sin_datos"], "#555555", "SIN DATOS"))
    ax.add_patch(plt.Rectangle((0.02, 0.04), 0.96, 0.92, transform=ax.transAxes,
                               facecolor=color, alpha=0.15, edgecolor=color, lw=2))
    ax.text(0.5, 0.86, "ESTADO BASE", ha="center", fontsize=12, color="#555", transform=ax.transAxes)
    ax.text(0.5, 0.68, palabra, ha="center", fontsize=32, fontweight="bold", color=oscuro,
            transform=ax.transAxes)
    ax.text(0.5, 0.57, "con su estado neutral" if corto == "compatible" else "de su estado neutral",
            ha="center", fontsize=12, color="#555", transform=ax.transAxes)
    lineas = []
    if tendencias:
        lineas.append(f"Desviación global: {tendencias['desviacion_global']:.1f}")
    if w2v:
        z = f" (z = {w2v['z']:+.1f})" if w2v.get("z") is not None else ""
        lineas.append(f"wav2vec2: {ETIQUETA_W2V.get(w2v['nivel'], w2v['nivel'])}{z}")
        for d, v in (w2v.get("probabilidades") or {}).items():
            lineas.append(f"P({NOMBRE_TARJETA[d].lower()}) = {v:.2f}")
    lineas.append(f"Respuestas con habla: {n_respuestas}/{len(PREGUNTAS)}")
    ax.text(0.5, 0.42, "\n".join(lineas), ha="center", va="top", fontsize=12, color="#333",
            linespacing=1.6, transform=ax.transAxes)

    # --- C. evolución por sesión
    ax = fig.add_subplot(gs[1, :])
    ax.set_title("Evolución por sesión (índice de cada estado)", fontsize=13, loc="left")
    ult = evals[-SESIONES_EN_GRAFICA:]
    if ult:
        xs = np.arange(len(ult))
        for e in ORDEN_ESTADOS:
            ys = [s["tendencias"]["estados"][e]["indice"] for s in ult]
            ys = [np.nan if v is None else max(0.0, v) for v in ys]  # historiales antiguos
            ax.plot(xs, ys, "-o", color=COLOR_ESTADO[e], lw=2, label=NOMBRE_TARJETA[e])
            techo = ult[-1]["tendencias"]["estados"][e]["techo_neutral"]
            if techo is not None:
                ax.axhline(techo, color=COLOR_ESTADO[e], ls="--", lw=1, alpha=0.6)
        ax.set_ylim(bottom=-0.05)
        ax.set_xticks(xs)
        ax.set_xticklabels(_etiquetas_sesion(ult), fontsize=8)
        ax.set_ylabel("Parecido con el estado (0 = nada)")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper left", fontsize=9, title="línea discontinua = techo neutral",
                  title_fontsize=8)
    else:
        _sin_datos(ax, "Aún no hay evaluaciones con las que dibujar la evolución.")

    fig.savefig(destino, dpi=150)
    return fig


def graficar_resumen(destino: Path):
    """Mapa de calor con el último nivel de cada astronauta (filas) y estado (columnas)."""
    from matplotlib.colors import ListedColormap
    filas = []
    for a in listar_astronautas():
        evals = [s for s in cargar_log(rutas_astronauta(a)[1])
                 if s.get("modo") == "evaluacion" and s.get("tendencias")]
        filas.append((a, evals[-1] if evals else None))
    if not filas:
        return None
    M = np.full((len(filas), len(ORDEN_ESTADOS)), np.nan)
    for i, (_, ult) in enumerate(filas):
        if ult:
            for j, e in enumerate(ORDEN_ESTADOS):
                M[i, j] = VALOR_NIVEL.get(ult["tendencias"]["estados"][e]["nivel"], np.nan)
    fig, ax = plt.subplots(figsize=(8, 1.6 + 0.9 * len(filas)), constrained_layout=True)
    cmap = ListedColormap([COLOR_NIVEL[n] for n in ("sin_senal", "indicio_debil",
                                                     "indicio_moderado", "indicio_marcado")])
    ax.imshow(np.ma.masked_invalid(M), cmap=cmap, vmin=-0.5, vmax=3.5, aspect="auto")
    for i, (_, ult) in enumerate(filas):
        for j, e in enumerate(ORDEN_ESTADOS):
            txt = ETIQUETA_CORTA[ult["tendencias"]["estados"][e]["nivel"]] if ult else "-"
            ax.text(j, i, txt, ha="center", va="center", fontsize=12, fontweight="bold", color="#222")
    ax.set_xticks(range(len(ORDEN_ESTADOS)))
    ax.set_xticklabels([NOMBRE_TARJETA[e] for e in ORDEN_ESTADOS], fontsize=12)
    ax.set_yticks(range(len(filas)))
    ax.set_yticklabels([f"{a}\n({estado_base(u['tendencias'])[0] if u else 'sin datos'})"
                        for a, u in filas], fontsize=11)
    ax.xaxis.tick_top()
    ax.set_title("Resumen de astronautas (última evaluación)", fontsize=14, pad=34)
    fig.supxlabel("Orientativo: no es un diagnóstico.", fontsize=9, color="#666")
    fig.savefig(destino, dpi=150)
    return fig


# =============================================================== 8. Orquestación general
def sesion(carpeta: Path, astronauta: str = "astronauta_1", modo: str = "evaluacion",
           modelo_texto: ModeloTexto | None = None,
           phq9: int | None = None, gad7: int | None = None, pss10: int | None = None,
           embedder: Wav2VecEmbedder | None = None) -> Informe:
    """
    astronauta: identificador; cada uno tiene su propia línea base neutral y su historial.
    modo="calibracion": las 4 preguntas, en reposo; la sesión entra en la línea base neutral.
    modo="evaluacion":  las mismas 4 preguntas; se compara con la línea base y NO la modifica.
    phq9 / gad7 / pss10 (opcionales): puntuación del cuestionario del mismo día; se guardan junto a
    los rasgos y los embeddings para poder validar o entrenar más adelante con etiquetas reales.
    """
    if modo not in ("calibracion", "evaluacion"):
        raise ValueError("modo debe ser 'calibracion' o 'evaluacion'")
    preguntas = PREGUNTAS
    carpeta.mkdir(parents=True, exist_ok=True)
    carpeta_audios = carpeta / "00_audios"
    carpeta_transcripcion = carpeta / "01_transcripcion"
    carpeta_fourier = carpeta / "02_graficas_fourier"
    wavs: list[Path] = []

    # 1. Captura: se conserva un WAV independiente para cada una de las 4 preguntas.
    for i, pregunta in enumerate(preguntas):
        print(f"\nPregunta {i + 1}/{len(preguntas)}: {pregunta}")
        wavs.append(grabar(SEGUNDOS_POR_RESPUESTA, carpeta_audios / f"pregunta_{i + 1}.wav"))
    (carpeta_audios / "preguntas.json").write_text(
        json.dumps({f"pregunta_{i + 1}.wav": p for i, p in enumerate(preguntas)},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. Módulo textual
    print("\n========== MÓDULO 1: TRANSCRIPCIÓN ==========")
    datos_texto = analizar_transcripcion(wavs, carpeta_transcripcion, preguntas)
    texto_total = datos_texto["texto_completo"]
    rasgos_texto = rasgos_texto_lexicos(texto_total)
    scores = (modelo_texto.puntuar(texto_total)
              if modelo_texto and texto_total and modo == "evaluacion" else None)

    # 3. Módulo acústico: gráficas de Fourier + rasgos
    print("\n========== MÓDULO 2: ANÁLISIS FOURIER (gráficas) ==========")
    datos_fourier = analizar_fourier(wavs, carpeta_fourier, preguntas)

    # 4. Media de características acústicas. Solo cuentan las respuestas con habla.
    con_habla = [bool(r["transcripcion"].strip()) for r in datos_texto["resultados"]]
    n_respuestas = sum(con_habla)
    filas_audio = [
        {**r["caracteristicas_fourier_y_prosodia"], **r["caracteristicas_opensmile_egemaps"]}
        for r, hay in zip(datos_fourier["resultados"], con_habla) if hay
    ]
    claves = {k for fila in filas_audio for k in fila}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        audio_medio = {k: media_segura([fila.get(k) for fila in filas_audio]) for k in claves}

    # 5. Línea base NEUTRAL de ESTE astronauta y tendencias.
    print("\n========== MÓDULO 3: TENDENCIAS FRENTE AL ESTADO NEUTRAL ==========")
    ruta_base, ruta_log = rutas_astronauta(astronauta)
    base = LineaBase(ruta_base)
    log = cargar_log(ruta_log)
    n_hist = len(base.historial)
    suficiente = n_respuestas >= MIN_RESPUESTAS_PARA_BASE
    desv, tendencias, extra = {}, None, []
    guardada = False

    if modo == "calibracion":
        if suficiente:
            base.guardar_sesion(audio_medio)
            guardada = True
            extra = comprobar_calibracion(base.historial)
        else:
            extra = [f"Calibración NO guardada: solo {n_respuestas} respuesta(s) con habla "
                     f"(mínimo {MIN_RESPUESTAS_PARA_BASE})."]
    elif audio_medio:
        desv = base.desviaciones(audio_medio)
        tendencias = evaluar_tendencias(audio_medio, base, log)

    # 6. wav2vec2: embedding de la voz de cada respuesta con habla (media de las 4) y comparación
    #    con los embeddings neutrales de ESTE astronauta.
    print("\n========== MÓDULO 4: WAV2VEC2 ==========")
    w2v, emb = None, None
    ruta_emb = ruta_w2v(astronauta)
    sesiones_w2v = cargar_log(ruta_emb)
    if n_respuestas > 0:
        embedder = embedder or Wav2VecEmbedder()
        embs = [embedder.embedding(_cargar(w)[0]) for w, hay in zip(wavs, con_habla) if hay]
        emb = np.mean(embs, axis=0)
        neutrales_w2v = [np.array(s["embedding"]) for s in sesiones_w2v if s["modo"] == "calibracion"]
        if modo == "evaluacion":
            w2v = evaluar_w2v(emb, neutrales_w2v)
            print(f"  wav2vec2: {w2v['nivel']}"
                  + (f" (z = {w2v['z']:+.1f})" if w2v["z"] is not None else ""))
        if modo == "evaluacion" or guardada:
            guardar_en_log(ruta_emb, sesiones_w2v, {
                "fecha": datetime.now().isoformat(timespec="seconds"), "modo": modo,
                "phq9": phq9, "gad7": gad7, "pss10": pss10,
                "embedding": [round(float(v), 5) for v in emb],
            })
    else:
        print("  Sin habla en ninguna respuesta: no se calcula wav2vec2.")

    n_neutrales = len(base.historial)
    informe = construir_informe(scores, rasgos_texto, desv, n_neutrales, n_respuestas, tendencias, w2v)
    informe.avisos += extra + avisos_cuestionarios(phq9, gad7)

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    if audio_medio:
        guardar_en_log(ruta_log, log, {
            "fecha": datetime.now().isoformat(timespec="seconds"), "modo": modo,
            "n_respuestas": n_respuestas, "phq9": phq9, "gad7": gad7, "pss10": pss10,
            "tendencias": tendencias,
            "w2v": w2v,
            "rasgos": audio_medio,
        })

    # 7. Valoración en texto (se imprime y se guarda) + datos en JSON para quien los necesite.
    ficha = (tarjeta_calibracion(astronauta, fecha, n_neutrales, guardada, extra)
             if modo == "calibracion"
             else tarjeta_astronauta(astronauta, fecha, tendencias, n_respuestas, n_neutrales,
                                     phq9, gad7, w2v))
    if modo == "evaluacion":
        fig_res = graficar_resultados(astronauta, fecha, tendencias, w2v, log, n_respuestas,
                                      carpeta / "resultados.png")
        if not MOSTRAR_GRAFICAS:
            plt.close(fig_res)
    (carpeta / "informe.json").write_text(
        json.dumps(limpiar_nan(asdict(informe)), ensure_ascii=False, indent=2), encoding="utf-8")
    (carpeta / "rasgos_audio_medios.json").write_text(
        json.dumps(limpiar_nan(audio_medio), ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + ficha)
    if modo == "evaluacion":
        print(f"\nGráfico de resultados: {carpeta / 'resultados.png'}")
    print(f"Audios WAV de las preguntas: {carpeta_audios}")
    print(f"Gráficas de Fourier (PNG): {carpeta_fourier}")
    return informe


if __name__ == "__main__":
    import sys
    ap = argparse.ArgumentParser(description="Señal de bienestar a partir de la voz (wav2vec2).")
    ap.add_argument("modo", choices=["calibracion", "evaluacion", "resumen", "entrenar"])
    ap.add_argument("astronauta", nargs="?", default="astronauta_1")
    ap.add_argument("--phq9", type=int, help="puntuación PHQ-9 del mismo día (opcional)")
    ap.add_argument("--gad7", type=int, help="puntuación GAD-7 del mismo día (opcional)")
    ap.add_argument("--pss10", type=int, help="puntuación PSS-10 (estrés percibido, opcional)")
    args = ap.parse_args()

    if args.modo == "resumen":
        print(resumen_todos())
        fig_resumen = graficar_resumen(CARPETA_DATOS / "resumen_astronautas.png")
        if fig_resumen is not None:
            print(f"\nGráfico guardado en: {CARPETA_DATOS / 'resumen_astronautas.png'}")
            if MOSTRAR_GRAFICAS:
                plt.show()
        sys.exit(0)
    if args.modo == "entrenar":
        print(entrenar_modelo_w2v())
        sys.exit(0)

    carpeta = (Path("sesiones") / _nombre_seguro(args.astronauta)
               / f"{args.modo}_{datetime.now():%Y%m%d_%H%M%S}")
    sesion(carpeta, astronauta=args.astronauta, modo=args.modo,
           phq9=args.phq9, gad7=args.gad7, pss10=args.pss10)
    if MOSTRAR_GRAFICAS:
        print("\nMostrando el gráfico de resultados. Cierra la ventana para terminar.")
        plt.show()