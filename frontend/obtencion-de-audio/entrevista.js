// Entrevista de audio (cada 3 días por defecto) y vídeo opcional de signos físicos de fatiga.
// La grabación solo vive en la memoria del navegador hasta enviarse. No se guarda en el
// dispositivo ni se reproduce de vuelta. El servidor la procesa en RAM y la descarta.
import { api, card, h } from "../assets/core.js";

async function record(kind, seconds, status) {
  const stream = await navigator.mediaDevices.getUserMedia(kind === "audio" ? { audio: true } : { video: { width: 320 }, audio: false });
  const type = kind === "audio" ? "audio/webm" : "video/webm";
  const rec = new MediaRecorder(stream, MediaRecorder.isTypeSupported(type) ? { mimeType: type } : {});
  const chunks = [];
  rec.ondataavailable = (e) => chunks.push(e.data);
  const done = new Promise((resolve) => { rec.onstop = resolve; });
  rec.start();
  let left = seconds;
  status.textContent = `Grabando… ${left} s`;
  const t = setInterval(() => { left--; status.textContent = `Grabando… ${left} s`; if (left <= 0) rec.stop(); }, 1000);
  const stop = () => { if (rec.state === "recording") rec.stop(); };
  await done; clearInterval(t);
  stream.getTracks().forEach((tr) => tr.stop());
  const blob = new Blob(chunks, { type: rec.mimeType.split(";")[0] || type });
  chunks.length = 0;
  return { blob, stop };
}

async function send(kind, blob, questionId, status) {
  status.textContent = "Enviando para procesar en memoria…";
  const headers = { "Content-Type": blob.type, "X-Media-Kind": kind };
  if (questionId) headers["X-Question-Id"] = String(questionId);
  const res = await api("/ingest/media", { method: "POST", body: blob, headers, raw: true });
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const s = await api(`/ingest/media/${res.job_id}`);
    if (s.status !== "queued") {
      status.textContent = s.status === "completed" ? "Procesado. La grabación ya no existe en ningún sitio." :
        `No se pudo procesar (${s.error_code}). La grabación se ha descartado.`;
      return;
    }
  }
  status.textContent = "Sigue en cola; puedes cerrar esta vista.";
}

export async function renderInterview(root) {
  const info = await api("/checkin/today");
  const iv = info.interview;
  const status = h("p", { class: "muted" });
  root.append(card("Entrevista de audio",
    h("p", { class: "muted small" }, iv.due ? `Hoy toca la entrevista (cada ${iv.interval_days} días).` :
      `La próxima entrevista toca dentro de unos días (cada ${iv.interval_days}). Puedes responder igualmente.`),
    h("p", { style: "font-size:1.15rem" }, `«${iv.question}»`),
    h("p", { class: "muted small" }, "Pregunta abierta y neutra. Habla con naturalidad durante unos 45 segundos."),
    h("button", { onclick: async (e) => {
      e.target.disabled = true;
      try { const { blob } = await record("audio", 45, status); await send("audio", blob, iv.question_id, status); }
      catch (err) { status.textContent = err.message; }
      e.target.disabled = false;
    } }, "Grabar respuesta (45 s)"), status));

  const vstatus = h("p", { class: "muted" });
  root.append(card("Comprobación de fatiga por vídeo (opcional)",
    h("p", { class: "muted small" }, "Solo detecta signos físicos (ojos cerrados, parpadeo lento). No infiere emociones."),
    h("button", { class: "ghost", onclick: async (e) => {
      e.target.disabled = true;
      try { const { blob } = await record("video", 20, vstatus); await send("video", blob, null, vstatus); }
      catch (err) { vstatus.textContent = err.message; }
      e.target.disabled = false;
    } }, "Grabar 20 s de vídeo"), vstatus));
}
