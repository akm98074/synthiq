"use strict";
/* Voice: push-to-talk / click-to-talk, conversation mode, spoken replies.
   Audio is captured in the browser, downsampled to 16 kHz mono WAV and
   transcribed on this Mac; replies are spoken with macOS `say`. */

const micBtn = $("#mic");
const voiceStatus = $("#voice-status");
const convToggle = $("#conversation");
const voice = { status: null, rec: null, pressAt: 0, speaking: false, clearTimer: null };

function setVoiceState(text, cls = "", sticky = false) {
  clearTimeout(voice.clearTimer);
  voiceStatus.textContent = text;
  voiceStatus.className = `voice-status ${cls}`;
  micBtn.classList.toggle("recording", cls === "listening");
  micBtn.classList.toggle("speaking", cls === "speaking");
  if (text && !sticky && !["listening", "busy", "speaking"].includes(cls)) {
    voice.clearTimer = setTimeout(() => setVoiceState(""), 6000);
  }
}

async function loadVoiceStatus() {
  try { voice.status = await api("/api/voice/status"); } catch (_) { voice.status = null; }
  const enabled = Boolean(voice.status?.enabled);
  micBtn.classList.toggle("hidden", !enabled);
  convToggle.parentElement.classList.toggle("hidden", !enabled);
  if (enabled && !voice.status.stt.available) {
    micBtn.title = voice.status.stt.reason;
    micBtn.classList.add("unavailable");
  } else {
    micBtn.title = "Hold to talk, or click to start and click again to send (Space works too)";
    micBtn.classList.remove("unavailable");
  }
}
window.loadVoiceStatus = loadVoiceStatus;

function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE");
  str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

function downsample(chunks, from, to) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const all = new Float32Array(total);
  let off = 0;
  for (const c of chunks) { all.set(c, off); off += c.length; }
  if (from === to) return all;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(total / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio), end = Math.min(total, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += all[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

class Recorder {
  async start({ vad, onEnd }) {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.node = this.ctx.createScriptProcessor(4096, 1, 1);
    this.chunks = [];
    this.heard = false;
    this.noise = 0;
    const t0 = performance.now();
    let lastVoice = 0;
    this.node.onaudioprocess = (e) => {
      const d = e.inputBuffer.getChannelData(0);
      this.chunks.push(new Float32Array(d));
      let sum = 0;
      for (let i = 0; i < d.length; i++) sum += d[i] * d[i];
      const rms = Math.sqrt(sum / d.length);
      const t = performance.now() - t0;
      if (t < 300) { this.noise = Math.max(this.noise, rms); return; }
      if (rms > Math.max(0.012, this.noise * 2.5)) { this.heard = true; lastVoice = t; }
      if (vad && this.heard && t - lastVoice > 1200) onEnd(false);
      else if (vad && !this.heard && t > 8000) onEnd(true);
      else if (t > 60000) onEnd(false);
    };
    src.connect(this.node);
    this.node.connect(this.ctx.destination); // ScriptProcessor only runs when connected; its output is silent
  }

  async stop() {
    try { this.node.disconnect(); } catch (_) {}
    this.stream.getTracks().forEach((t) => t.stop());
    const rate = this.ctx.sampleRate;
    await this.ctx.close();
    return encodeWav(downsample(this.chunks, rate, 16000), 16000);
  }
}

async function stopSpeaking() {
  if (!voice.speaking) return;
  try { await fetch("/api/voice/stop", { method: "POST" }); } catch (_) {}
}

async function startListening(vad) {
  if (voice.rec || sending) return;
  if (!voice.status?.stt.available) {
    setVoiceState(voice.status?.stt.reason || "Voice input isn't available.", "error", true);
    return;
  }
  await stopSpeaking();                    // barge-in
  const rec = new Recorder();
  voice.rec = rec;
  try {
    await rec.start({ vad, onEnd: (nothing) => finishListening(nothing) });
  } catch (err) {
    voice.rec = null;
    setVoiceState(`Microphone blocked (${err.name || err.message}). Allow the microphone for this page in your browser's site settings.`, "error", true);
    return;
  }
  setVoiceState(vad ? "Listening… pause when you're done" : "Listening… click or release to send", "listening");
}

async function finishListening(nothingHeard = false) {
  const rec = voice.rec;
  if (!rec) return;
  voice.rec = null;
  const wav = await rec.stop();
  if (nothingHeard || !rec.heard) {
    setVoiceState("Didn't hear anything.");
    return;
  }
  setVoiceState("Transcribing…", "busy");
  let result;
  try {
    const r = await fetch("/api/voice/transcribe", { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav });
    result = await r.json();
    if (!r.ok) throw new Error(result.detail || r.statusText);
  } catch (err) {
    setVoiceState(`Couldn't transcribe: ${err.message}`, "error", true);
    return;
  }
  if (!result.text) { setVoiceState("Didn't catch that. Try again."); return; }
  setVoiceState(`Heard in ${(result.ms / 1000).toFixed(1)} s`);
  input.value = result.text;
  const out = await send();
  if (!out) return;
  if (!voice.status?.speak_replies || !voice.status?.tts.available) return;
  const say = out.paused ? "I need your OK on screen before I do that." : out.text;
  if (!say) return;
  setVoiceState("Speaking… click the mic to interrupt", "speaking");
  voice.speaking = true;
  let finished = false;
  try {
    const r = await fetch("/api/voice/speak", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: say }) });
    finished = (await r.json()).finished;
  } catch (_) {}
  voice.speaking = false;
  setVoiceState("");
  if (convToggle.checked && finished && !out.paused) startListening(true);
}

micBtn.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  if (voice.rec) { finishListening(); return; }
  voice.pressAt = performance.now();
  startListening(convToggle.checked);
});
micBtn.addEventListener("pointerup", () => {
  // Held longer than a tap: push-to-talk, so releasing sends.
  if (voice.rec && voice.pressAt && performance.now() - voice.pressAt > 450) finishListening();
  voice.pressAt = 0;
});

const typingTarget = (el) => el && (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable);
document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || e.repeat || typingTarget(document.activeElement)) return;
  if (!$("#tab-chat").classList.contains("active") || micBtn.classList.contains("hidden")) return;
  e.preventDefault();
  if (!voice.rec) startListening(false);
});
document.addEventListener("keyup", (e) => {
  if (e.code === "Space" && voice.rec && !typingTarget(document.activeElement)) { e.preventDefault(); finishListening(); }
});
convToggle.addEventListener("change", () => {
  try { localStorage.setItem("conversationMode", convToggle.checked ? "1" : "0"); } catch (_) {}
  if (!convToggle.checked) stopSpeaking();
});
try { convToggle.checked = localStorage.getItem("conversationMode") === "1"; } catch (_) {}

loadVoiceStatus();
