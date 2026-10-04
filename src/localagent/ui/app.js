"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
};

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  const type = res.headers.get("content-type") || "";
  return type.includes("json") ? res.json() : res.text();
}

const pct = (x) => `${Math.round(x * 100)}%`;
const LABELS = {
  chit_chat: "chit-chat", quick_answer: "quick answer", task: "task", schedule: "schedule",
  memory_write: "remember", memory_query: "recall", computer_action: "computer action",
};
let questions = [];
let settings = {};

/* ── tabs ─────────────────────────────────────────────────────────────── */
const loaders = { decisions: loadDecisions, memory: loadMemory, models: loadModels, settings: loadSettings };
document.querySelectorAll(".tab").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".panel").forEach((p) =>
      p.classList.toggle("active", p.id === `tab-${btn.dataset.tab}`));
    loaders[btn.dataset.tab]?.();
  }));

/* ── chat ─────────────────────────────────────────────────────────────── */
const messagesEl = $("#messages");
const input = $("#input");

function decisionChips(d) {
  const intent = d.answers.intent;
  const thr = settings.confidence_threshold ?? 0.6;
  const chips = [
    el("span", { class: `chip ${intent.confidence < thr ? "low" : ""}`, title: "Decision: intent" },
      `${LABELS[intent.label] || intent.label} · ${pct(intent.confidence)}`),
    el("span", { class: "chip", title: "Decision backend and latency" },
      `${d.backend} · ${Math.round(d.latency_ms)} ms`),
  ];
  if (d.answers.needs_memory_write?.label === "yes") chips.push(el("span", { class: "chip" }, "memorable"));
  return chips;
}

function addMessage(role, text, decision) {
  $(".empty")?.remove();
  const bubble = el("div", { class: "bubble" }, text);
  const meta = el("div", { class: "meta" });
  if (decision) meta.append(...decisionChips(decision));
  const node = el("div", { class: `msg ${role}` }, bubble, meta);
  messagesEl.append(node);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return { node, bubble, meta };
}

function showEmpty() {
  const tries = ["I'm vegetarian and I prefer window seats", "What do you know about me?",
                 "Draft a short thank-you note to my neighbor", "Remind me to call mom at 6pm"];
  messagesEl.append(el("div", { class: "empty" },
    el("h2", {}, `Hi, I'm ${settings.agent_name || "your agent"}.`),
    el("p", {}, "I run entirely on this Mac. Tell me about yourself and I'll remember it; every message shows how I decided to handle it."),
    el("div", { class: "suggestions" }, tries.map((t) =>
      el("button", { class: "ghost", onclick: () => { input.value = t; send(); } }, t)))));
}

async function loadHistory() {
  messagesEl.innerHTML = "";
  const msgs = await api("/api/messages?limit=100");
  if (!msgs.length) return showEmpty();
  for (const m of msgs) addMessage(m.role, m.content, m.decision);
}

let sending = false;
async function send() {
  const text = input.value.trim();
  if (!text || sending) return;
  sending = true;
  $("#send").disabled = true;
  input.value = "";
  autosize();
  const user = addMessage("user", text);
  const bot = addMessage("assistant", "…");
  let got = "";
  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
        if (!chunk.startsWith("data: ")) continue;
        const ev = JSON.parse(chunk.slice(6));
        if (ev.type === "decision") user.meta.append(...decisionChips(ev.decision));
        else if (ev.type === "memory_saved")
          bot.meta.append(el("span", { class: "chip mem", title: "Saved to memory" },
            `${ev.updated ? "updated" : "remembered"}: ${ev.memory.text}`));
        else if (ev.type === "recalled")
          bot.meta.append(el("span", { class: "chip mem", title: ev.memories.map((m) => m.text).join("\n") },
            `recalled ${ev.memories.length} memor${ev.memories.length === 1 ? "y" : "ies"}`));
        else if (ev.type === "token") {
          got += ev.text; bot.bubble.textContent = got;
          messagesEl.scrollTop = messagesEl.scrollHeight;
        } else if (ev.type === "error") bot.node.append(el("div", { class: "error" }, ev.message));
        else if (ev.type === "done" && ev.model) bot.meta.append(el("span", { class: "chip" }, ev.model));
      }
    }
  } catch (err) {
    bot.node.append(el("div", { class: "error" }, String(err.message || err)));
  } finally {
    if (!got) bot.bubble.textContent = "(no reply)";
    sending = false;
    $("#send").disabled = false;
    input.focus();
  }
}

function autosize() { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 200)}px`; }
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
});
$("#composer").addEventListener("submit", (e) => { e.preventDefault(); send(); });
$("#clear-chat").addEventListener("click", async () => {
  if (!confirm("Clear the conversation? Memories are kept.")) return;
  await api("/api/messages", { method: "DELETE" });
  loadHistory();
});

/* ── decisions ────────────────────────────────────────────────────────── */
function probsView(answer) {
  const entries = Object.entries(answer.probs).sort((a, b) => b[1] - a[1]);
  return el("div", { class: "probs" }, entries.flatMap(([label, p]) => [
    el("span", {}, LABELS[label] || label),
    el("div", { class: "bar" }, el("span", { style: `width:${(p * 100).toFixed(1)}%` })),
    el("span", { class: "muted" }, pct(p)),
  ]));
}

function decisionCard(d, withCorrection = true) {
  const card = el("div", { class: "card" },
    el("div", { class: "card-row" },
      el("span", { class: "text" }, d.text),
      el("span", { class: "muted" }, `${d.backend}${d.escalated ? " (escalated)" : ""} · ${Math.round(d.latency_ms)} ms`)));
  for (const [name, ans] of Object.entries(d.answers)) {
    card.append(el("div", { class: "qname" }, name.replaceAll("_", " ")));
    card.append(probsView(ans));
    const fixed = d.corrections?.[name];
    if (fixed) card.append(el("div", { class: "correct status-ok" }, `Corrected to: ${LABELS[fixed] || fixed}`));
    else if (withCorrection && d.id && name !== "complexity") {
      const q = questions.find((x) => x.name === name);
      const sel = el("select", {}, Object.keys(q?.options || {}).map((l) =>
        el("option", l === ans.label ? { value: l, selected: "" } : { value: l }, LABELS[l] || l)));
      const btn = el("button", { class: "ghost", onclick: async () => {
        btn.disabled = true;
        try {
          await api(`/api/decisions/${d.id}/correct`, { method: "POST", body: { question: name, label: sel.value } });
          loadDecisions();
        } catch (err) { alert(err.message); btn.disabled = false; }
      } }, "Save correction");
      card.append(el("div", { class: "correct" }, el("span", { class: "muted" }, "Correct label:"), sel, btn));
    }
  }
  if (d.notes?.length) card.append(el("div", { class: "muted", style: "font-size:12px;margin-top:6px" }, d.notes.join(" · ")));
  return card;
}

async function loadDecisions() {
  const list = $("#decision-list");
  const items = await api("/api/decisions?limit=50");
  list.replaceChildren(...(items.length ? items.map((d) => decisionCard(d))
    : [el("p", { class: "muted" }, "No decisions yet. Send a chat message first.")]));
}

$("#try-decide").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#try-text").value.trim();
  if (!text) return;
  const out = $("#try-result");
  out.textContent = "Deciding…";
  try { out.replaceChildren(decisionCard(await api("/api/decide", { method: "POST", body: { text } }), false)); }
  catch (err) { out.replaceChildren(el("p", { class: "error" }, err.message)); }
});

/* ── memory ───────────────────────────────────────────────────────────── */
async function loadMemory() {
  const list = $("#memory-list");
  const mems = await api("/api/memories");
  list.replaceChildren(...(mems.length ? mems.map(memoryCard)
    : [el("p", { class: "muted" }, "Nothing remembered yet. Tell your agent something about yourself in Chat, or add it here.")]));
  $("#identity").textContent = await api("/api/identity");
}

function memoryCard(m) {
  const text = el("span", { class: "text" }, m.text);
  const card = el("div", { class: "card" });
  const edit = el("button", { class: "ghost", onclick: async () => {
    const next = prompt("Edit memory", m.text);
    if (next && next.trim() && next !== m.text) {
      await api(`/api/memories/${m.id}`, { method: "PATCH", body: { text: next.trim() } });
      loadMemory();
    }
  } }, "Edit");
  const forget = el("button", { class: "ghost", onclick: async () => {
    if (!confirm(`Forget "${m.text}"?`)) return;
    await api(`/api/memories/${m.id}`, { method: "DELETE" });
    loadMemory();
  } }, "Forget");
  card.append(el("div", { class: "card-row" },
    el("div", {}, el("div", { class: "kind" }, m.kind), text),
    el("div", { class: "row" }, edit, forget)));
  return card;
}

$("#add-memory").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#mem-text").value.trim();
  if (!text) return;
  await api("/api/memories", { method: "POST", body: { text, kind: $("#mem-kind").value } });
  $("#mem-text").value = "";
  loadMemory();
});

/* ── models ───────────────────────────────────────────────────────────── */
async function loadModels() {
  const s = await api("/api/models");
  $("#ram").textContent = `RAM: ${s.ram.available_gb} GB free of ${s.ram.total_gb} GB (${s.ram.used_percent}% used)`;
  const list = $("#models");
  if (s.error) {
    list.replaceChildren(el("div", { class: "card status-fail" }, s.error));
  } else {
    const loaded = new Set(s.loaded.map((m) => m.name));
    list.replaceChildren(...s.configured.map((m) => {
      const name = m.name.includes(":") ? m.name : `${m.name}:latest`;
      const isLoaded = loaded.has(name) || loaded.has(m.name);
      const actions = el("div", { class: "row" });
      if (!m.installed) {
        const btn = el("button", { class: "secondary", onclick: () => pullModel(m.name, btn) }, "Download");
        actions.append(btn);
      } else if (isLoaded) {
        actions.append(el("button", { class: "ghost", onclick: async () => {
          await api("/api/models/unload", { method: "POST", body: { model: m.name } }); loadModels();
        } }, "Unload"));
      }
      return el("div", { class: "card" }, el("div", { class: "card-row" },
        el("div", {}, el("div", { class: "kind" }, m.role), el("span", { class: "text" }, m.name),
          el("div", { class: "muted" },
            `${m.installed ? "installed" : "not installed"}${isLoaded ? " · loaded in memory" : ""}` +
            (m.approx_gb ? ` · ~${m.approx_gb} GB` : ""))),
        actions));
    }));
  }
  const checks = await api("/api/doctor");
  $("#doctor").replaceChildren(...checks.map((c) => el("div", { class: "card card-row" },
    el("span", {}, c.name), el("span", { class: `status-${c.status}` }, c.detail))));
}

async function pullModel(name, btn) {
  btn.disabled = true;
  const res = await fetch("/api/models/pull", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: name }),
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const ev = JSON.parse(buf.slice(6, idx)); buf = buf.slice(idx + 2);
      if (ev.error) { alert(ev.error); break; }
      btn.textContent = ev.total && ev.completed ? `${Math.round(ev.completed / ev.total * 100)}%` : (ev.status || "…");
    }
  }
  loadModels();
}

/* ── settings ─────────────────────────────────────────────────────────── */
async function loadSettings() {
  settings = await api("/api/settings");
  const form = $("#settings-form");
  for (const [k, v] of Object.entries(settings)) if (form.elements[k]) form.elements[k].value = v;
}

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const values = {};
  for (const k of Object.keys(settings)) if (form.elements[k]) values[k] = form.elements[k].value;
  try {
    settings = await api("/api/settings", { method: "PUT", body: values });
    $("#settings-status").textContent = "Saved.";
    $("#agent-name").textContent = settings.agent_name;
  } catch (err) { $("#settings-status").textContent = err.message; }
  setTimeout(() => ($("#settings-status").textContent = ""), 3000);
});

/* ── boot ─────────────────────────────────────────────────────────────── */
async function boot() {
  try {
    [settings, questions] = await Promise.all([api("/api/settings"), api("/api/questions")]);
    $("#agent-name").textContent = settings.agent_name;
    document.title = `${settings.agent_name} · LocalAIAgent`;
  } catch (_) {}
  await loadHistory();
  try {
    const checks = await api("/api/doctor");
    const failing = checks.filter((c) => c.status === "fail");
    $("#status-dot").className = `dot ${failing.length ? "fail" : "ok"}`;
    if (failing.length) {
      const b = $("#banner");
      b.textContent = failing.map((c) => `${c.name}: ${c.detail}`).join(" · ");
      b.classList.remove("hidden");
    }
  } catch (_) { $("#status-dot").className = "dot fail"; }
  input.focus();
}
boot();
