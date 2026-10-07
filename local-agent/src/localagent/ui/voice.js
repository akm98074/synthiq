"use strict";
/* Voice: push-to-talk / click-to-talk, conversation mode, spoken replies.
   Audio is captured in the browser, downsampled to 16 kHz mono WAV and
   transcribed on this Mac; replies are spoken with macOS `say`. */

const micBtn = $("#mic");
const voiceStatus = $("#voice-status");
const convToggle = $("#conversation");
const voice = { status: null, rec: null, pressAt: 0, speaking: false, clearTimer: null, busy: false };
const wakeToggle = $("#wake");

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
  wakeToggle.parentElement.classList.toggle("hidden", !enabled);
  $("#avatar-toggle").parentElement.classList.toggle("hidden", !enabled || !voice.status?.tts.available);
  avatar.show(Boolean(enabled && voice.status?.avatar && voice.status?.tts.available));
  $("#avatar-name").textContent = (window.settings && window.settings.agent_name) || $("#agent-name").textContent;
  if (voice.status?.wake) {
    $("#wake-text").textContent = voice.status.wake.phrase;
    wakeToggle.checked = voice.status.wake.enabled;
    if (enabled && voice.status.wake.enabled && voice.status.stt.available) wake.start(); else wake.stop();
    if (voice.status.wake.enabled && !enabled) setVoiceState("The wake word needs voice: turn on Voice in Settings.", "error", true);
    else if (voice.status.wake.enabled && !voice.status.stt.available) {
      setVoiceState(`The wake word can't listen yet: ${voice.status.stt.reason}`, "error", true);
    }
  }
  if (enabled && !voice.status.stt.available) {
    micBtn.title = voice.status.stt.reason;
    micBtn.classList.add("unavailable");
  } else {
    micBtn.title = "Hold to talk, or click to start and click again to send (Space works too)";
    micBtn.classList.remove("unavailable");
  }
}
window.loadVoiceStatus = loadVoiceStatus;
window.voiceInfo = () => voice.status;

/* ── speaking: macOS `say` on the Mac, or (with the face) played here with lip-sync ── */
async function speakText(text) {
  voice.speaking = true;
  let finished = false;
  try {
    if (voice.status?.avatar) {
      finished = await avatar.speak(text);
    } else {
      const r = await fetch("/api/voice/speak", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }) });
      finished = (await r.json()).finished;
    }
  } catch (_) {}
  voice.speaking = false;
  return finished;
}

window.readAloud = async (text) => {
  if (!text) return;
  await stopSpeaking();
  setVoiceState("Speaking… click the mic to interrupt", "speaking");
  await speakText(text);
  setVoiceState("");
};

const avatar = {
  box: $("#avatar"), mouth: $("#av-mouth"), eyes: document.querySelectorAll(".av-eye"),
  ctx: null, src: null, raf: 0, playing: false, done: null, level: 0,
  SHAPES: [[16, 1.5], [15, 4], [14, 7], [13, 10], [12, 13]],
  show(on) {
    this.box.classList.toggle("hidden", !on);
    $("#avatar-toggle").checked = on;
  },
  setLevel(level) {
    this.level = this.level * 0.5 + level * 0.5;             // smooth between frames
    const i = Math.min(4, Math.round(this.level * 4));
    const [rx, ry] = this.SHAPES[i];
    this.mouth.setAttribute("rx", rx); this.mouth.setAttribute("ry", ry);
    this.box.dataset.level = String(i);
  },
  async speak(text) {
    const r = await fetch("/api/voice/audio", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }) });
    if (!r.ok) return false;
    const data = await r.arrayBuffer();
    this.ctx = this.ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (this.ctx.state === "suspended") await this.ctx.resume();
    const buffer = await this.ctx.decodeAudioData(data);
    const src = this.ctx.createBufferSource();
    const analyser = this.ctx.createAnalyser();
    analyser.fftSize = 1024;
    src.buffer = buffer;
    src.connect(analyser); analyser.connect(this.ctx.destination);
    const samples = new Float32Array(analyser.fftSize);
    this.src = src; this.playing = true;
    this.box.classList.add("talking");
    const frame = () => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const v of samples) sum += v * v;
      this.setLevel(Math.min(1, Math.sqrt(sum / samples.length) * 6));
      this.raf = requestAnimationFrame(frame);
    };
    return new Promise((resolve) => {
      this.done = resolve;
      src.onended = () => this.finish(true);
      src.start();
      frame();
    });
  },
  finish(ok) {
    cancelAnimationFrame(this.raf);
    this.playing = false;
    this.box.classList.remove("talking");
    this.level = 0; this.setLevel(0);
    const d = this.done; this.done = null;
    if (d) d(ok);
  },
  stop() {
    if (!this.playing) return;
    const src = this.src; this.src = null;
    this.finish(false);
    try { src.onended = null; src.stop(); } catch (_) {}
  },
};
window.avatar = avatar;
setInterval(() => {                                           // blink now and then
  if (avatar.box.classList.contains("hidden") || Math.random() < 0.5) return;
  avatar.eyes.forEach((e) => e.setAttribute("ry", "1"));
  setTimeout(() => avatar.eyes.forEach((e) => e.setAttribute("ry", "7")), 130);
}, 2500);

$("#avatar-toggle").addEventListener("change", async (e) => {
  try { await api("/api/settings", { method: "PUT", body: { avatar_enabled: e.target.checked } }); } catch (_) {}
  await loadVoiceStatus();
});

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
  if (avatar.playing) { avatar.stop(); return; }
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
  voice.busy = true;
  try { await finishTurn(rec, nothingHeard); } finally { voice.busy = false; }
}

async function finishTurn(rec, nothingHeard) {
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
  await askAndSpeak(result.text);
}

async function askAndSpeak(text) {
  input.value = text;
  const out = await send();
  if (!out) return;
  if (!voice.status?.speak_replies || !voice.status?.tts.available) return;
  const say = out.paused ? "I need your OK on screen before I do that." : out.text;
  if (!say) return;
  setVoiceState("Speaking… click the mic to interrupt", "speaking");
  const finished = await speakText(say);
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

/* ── wake word ──────────────────────────────────────────────────────────
   While enabled, the mic stays open. Each short burst of speech (0.35–6 s) is sent to
   /api/voice/wake; nothing is kept. Bursts are ignored while the agent is listening,
   working or speaking, so it never wakes itself. */
const wake = {
  on: false, stream: null, ctx: null, node: null, inflight: false, failed: "", heard: "", heardTimer: null,
  async start() {
    if (this.on) return;
    this.failed = "";
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch (err) {
      setVoiceState(`Microphone blocked (${err.name || err.message}); the wake word needs it.`, "error", true);
      return;
    }
    this.on = true;
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    this.ctx.onstatechange = () => this.showState();
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.node = this.ctx.createScriptProcessor(4096, 1, 1);
    const rate = this.ctx.sampleRate;
    const blockMs = 4096 / rate * 1000;
    let noise = 0.01, chunks = [], speechMs = 0, silenceMs = 0, preroll = [];
    this.node.onaudioprocess = (e) => {
      const d = new Float32Array(e.inputBuffer.getChannelData(0));
      if (voice.rec || voice.busy || voice.speaking || sending || this.inflight) { chunks = []; speechMs = 0; return; }
      let sum = 0;
      for (let i = 0; i < d.length; i++) sum += d[i] * d[i];
      const rms = Math.sqrt(sum / d.length);
      const loud = rms > Math.max(0.015, noise * 3);
      if (!loud && !chunks.length) {
        noise = noise * 0.95 + rms * 0.05;              // track the room's background level
        preroll = [d];                                  // keep the block before speech starts
        return;
      }
      if (!chunks.length) chunks = [...preroll];
      chunks.push(d);
      if (loud) { speechMs += blockMs; silenceMs = 0; } else { silenceMs += blockMs; }
      const total = chunks.length * blockMs;
      if (silenceMs >= 450 || total >= 6000) {
        const burst = chunks; const spoke = speechMs;
        chunks = []; speechMs = 0; silenceMs = 0;
        if (spoke >= 250) this.check(burst, rate);
      }
    };
    src.connect(this.node);
    this.node.connect(this.ctx.destination);
    // Browsers keep audio started without a click suspended, and then no sound reaches us at all.
    // resume() only succeeds after a user gesture, so try now and again on the first click or key.
    await Promise.race([this.ctx.resume().catch(() => {}), new Promise((ok) => setTimeout(ok, 300))]);
    if (this.ctx.state !== "running") {
      const kick = () => { if (this.ctx && this.ctx.state !== "closed") this.ctx.resume().catch(() => {}); };
      document.addEventListener("pointerdown", kick, { once: true, capture: true });
      document.addEventListener("keydown", kick, { once: true, capture: true });
    }
    this.showState();
  },
  phrase() { return $("#wake-text").textContent; },
  showState() {
    if (!this.on || voice.rec || voice.busy) return;
    if (this.ctx?.state === "running") setVoiceState(`Listening for “${this.phrase()}”`, "", true);
    else setVoiceState(`Click anywhere on this page to start listening for “${this.phrase()}”`, "", true);
  },
  async stop() {
    if (!this.on) return;
    this.on = false;
    try { this.node.disconnect(); } catch (_) {}
    this.stream.getTracks().forEach((t) => t.stop());
    await this.ctx.close();
    if (/^(Listening for|Click anywhere on this page to start listening|Heard “)/.test(voiceStatus.textContent)) setVoiceState("");
  },
  async check(burst, rate) {
    this.inflight = true;
    try {
      const wav = encodeWav(downsample(burst, rate, 16000), 16000);
      const r = await fetch("/api/voice/wake", { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav });
      const res = await r.json().catch(() => ({}));
      if (!r.ok) {
        // Say why instead of silently never waking (wake word off, paused, speech model missing…).
        this.failed = `Wake word: ${res.detail || `error ${r.status}`}`;
        if (r.status === 409) this.stop();
        return;
      }
      this.failed = "";
      if (!res.wake) {
        if (res.heard) this.heard = res.heard;
        return;
      }
      chime();
      document.body.classList.add("woke");
      setTimeout(() => document.body.classList.remove("woke"), 1200);
      if (res.command) {
        voice.busy = true;
        try { await askAndSpeak(res.command); } finally { voice.busy = false; }
      } else {
        await startListening(true);
      }
    } catch (err) {
      this.failed = `Wake word: couldn't reach the agent (${err.message})`;
    } finally {
      this.inflight = false;
      if (this.failed) setVoiceState(this.failed, "error", true);
      else if (this.heard && this.on && !voice.rec) {
        // Show what it heard for a moment, so a near miss ("Hey Harry") is visible, then go back to listening.
        setVoiceState(`Heard “${this.heard.slice(0, 60)}”, not “${this.phrase()}”`, "", true);
        this.heard = "";
        clearTimeout(this.heardTimer);
        this.heardTimer = setTimeout(() => this.showState(), 2500);
      } else this.showState();
    }
  },
};
window.wakeListener = wake;

function chime() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = "sine"; o.frequency.setValueAtTime(660, ctx.currentTime);
    o.frequency.setValueAtTime(880, ctx.currentTime + 0.09);
    g.gain.setValueAtTime(0.15, ctx.currentTime); g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
    o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.3);
    setTimeout(() => ctx.close(), 500);
  } catch (_) {}
}

wakeToggle.addEventListener("change", async () => {
  try {
    await api("/api/settings", { method: "PUT", body: { wake_word_enabled: wakeToggle.checked } });
  } catch (err) { setVoiceState(err.message, "error", true); }
  await loadVoiceStatus();
});

loadVoiceStatus();
