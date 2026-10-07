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
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body,
  });
  if (res.status === 428 && !opts._confirmed) {
    // A security-sensitive change: show what each one risks and ask before resending.
    let d = {};
    try { d = (await res.json()).detail || {}; } catch (_) {}
    const items = d.confirm || [];
    const text = items.map((c) => `• ${c.key}: ${JSON.stringify(c.from)} → ${JSON.stringify(c.to)}\n  ${c.risk}`).join("\n\n");
    if (!window.confirm(`${d.message || "Confirm these changes."}\n\n${text}\n\nMake these changes?`)) {
      throw new Error("Not changed.");
    }
    return api(path, { ...opts, _confirmed: true,
      headers: { ...(opts.headers || {}), "X-Confirm": items.map((c) => c.key).join(",") } });
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(typeof detail === "string" ? detail : (detail.message || JSON.stringify(detail)));
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
const loaders = { trust: loadTrust, nudges: loadNudges, decisions: loadDecisions, memory: loadMemory, models: loadModels, settings: loadSettings,
  approvals: loadApprovals, activity: loadActivity, connectors: loadConnectors };
document.querySelectorAll(".tab").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".panel").forEach((p) =>
      p.classList.toggle("active", p.id === `tab-${btn.dataset.tab}`));
    Promise.resolve(loaders[btn.dataset.tab]?.()).catch((err) => {
      const b = $("#banner");
      b.textContent = `Couldn't load ${btn.dataset.tab}: ${err.message || err}. Try reloading the page (Cmd+Shift+R).`;
      b.classList.remove("hidden");
    });
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

/* Minimal, safe markdown: everything is HTML-escaped first, then a few patterns
   (bold, italic, code, headings, lists) are turned into tags. */
function md(text) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,!?:;]|$)/g, "$1<em>$2</em>");
  const out = [];
  let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of String(text).split("\n")) {
    const line = raw.trimEnd();
    let m;
    if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) {
      if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; }
      out.push(`<li>${inline(m[1])}</li>`);
    } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; }
      out.push(`<li>${inline(m[1])}</li>`);
    } else if ((m = line.match(/^#{1,6}\s+(.*)$/))) {
      close(); out.push(`<div class="md-h">${inline(m[1])}</div>`);
    } else if (!line.trim()) {
      close(); out.push('<div class="md-gap"></div>');
    } else {
      close(); out.push(`<div>${inline(line)}</div>`);
    }
  }
  close();
  return out.join("");
}

function setBubble(bubble, role, text) {
  if (role === "assistant") bubble.innerHTML = md(text);
  else bubble.textContent = text;
}

function fmtItemTime(start, end, allDay) {
  const d = new Date(start);
  const day = d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  if (allDay) return `${day} (all day)`;
  const t = (x) => new Date(x).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return `${day} ${t(start)}${end ? "–" + t(end) : ""}`;
}

function itemText(it) {
  if (it.title && it.start) {
    const tags = [it.recurring && "repeats", it.status === "pending" && "invitation",
                  it.status === "declined" && "declined", it.status === "tentative" && "tentative"].filter(Boolean);
    const cal = [it.calendar, it.account].filter(Boolean).join(" · ");
    return `${fmtItemTime(it.start, it.end, it.all_day)}  ${it.title}${it.location ? " @ " + it.location : ""}`
      + (tags.length ? ` (${tags.join(", ")})` : "") + (cal ? `  [${cal}]` : "");
  }
  if (it.url && it.title !== undefined) return `${it.title} — ${it.site || it.url}`;
  if (it.app && it.last_text !== undefined) {
    return `${it.last_at ? fmtItemTime(it.last_at) + "  " : ""}${it.app} · ${it.name}${it.group ? " (group)" : ""}: `
      + `${it.last_from_me ? "You: " : ""}${it.last_text.slice(0, 120)}${it.unread ? `  [${it.unread} unread]` : ""}`;
  }
  if (it.sender !== undefined && it.text !== undefined) return `${fmtItemTime(it.at)}  ${it.sender}: ${it.text.slice(0, 160)}`;
  if (it.subject !== undefined) return `${it.received ? fmtItemTime(it.received) + "  " : ""}${it.from}: ${it.subject}`;
  if (it.title !== undefined) return `${it.title}${it.due ? " (due " + fmtItemTime(it.due) + ")" : ""}${it.list ? "  [" + it.list + "]" : ""}`;
  if (it.path) return it.path;
  if (it.name) return `${it.name}${it.emails?.length ? " · " + it.emails.join(", ") : ""}${it.phones?.length ? " · " + it.phones.join(", ") : ""}`;
  return JSON.stringify(it);
}

function toolResultView(ev) {
  const label = `${ev.ok ? "✓" : "✗"} ${ev.display}`;
  if (ev.data && !Array.isArray(ev.data) && ev.data.shot) {
    // Live view of the agent's browser after this step; click to enlarge.
    const wrap = el("span", { class: "tool-step" });
    const img = el("img", { class: "shot", alt: `Browser: ${ev.data.title || ""}`, title: "Click to enlarge",
                            src: `data:image/jpeg;base64,${ev.data.shot}` });
    img.addEventListener("click", () => wrap.classList.toggle("big"));
    wrap.append(el("span", { class: `chip tool ${ev.ok ? "" : "low"}`, title: ev.tool }, label), img);
    return wrap;
  }
  if (!Array.isArray(ev.data) || !ev.data.length) {
    return el("span", { class: `chip tool ${ev.ok ? "" : "low"}`, title: ev.tool }, label);
  }
  return el("details", { class: "tool-data" },
    el("summary", { class: "chip tool", title: `${ev.tool}: click to see every item` }, label),
    el("ul", {}, ev.data.map((it) => el("li", {}, itemText(it)))));
}

function addMessage(role, text, decision) {
  $(".empty")?.remove();
  const bubble = el("div", { class: "bubble" });
  setBubble(bubble, role, text);
  const meta = el("div", { class: "meta" });
  if (decision) meta.append(...decisionChips(decision));
  const node = el("div", { class: `msg ${role}` }, bubble, meta);
  messagesEl.append(node);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return { node, bubble, meta };
}

function showEmpty() {
  const tries = ["I'm vegetarian and I prefer window seats", "What's on my calendar today?",
                 "Remind me to call mom at 6pm", "What's the newest file in my Downloads?"];
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

const TIER_LABEL = { read: "reads", draft: "creates", write: "changes", danger: "deletes / irreversible" };

async function readSSE(res, onEvent) {
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
      if (chunk.startsWith("data: ")) onEvent(JSON.parse(chunk.slice(6)));
    }
  }
}

function approvalCard(ap, onDecided) {
  const scope = el("select", { "aria-label": "Approval scope" },
    ap.allowed_scopes.map((sc) => el("option", { value: sc.id }, sc.label)));
  const approve = el("button", { class: "primary" }, "Approve");
  const decline = el("button", { class: "secondary" }, "Decline");
  const status = el("span", { class: "muted" });
  const card = el("div", { class: `approval tier-${ap.tier}` },
    el("div", { class: "approval-head" },
      el("span", { class: `badge tier-${ap.tier}` }, `${ap.tier} · ${TIER_LABEL[ap.tier] || ""}`),
      el("strong", {}, ap.summary)),
    ap.reason ? el("div", { class: "approval-why muted" }, `Why it asks: ${ap.reason}`) : null,
    // The full payload, open by default: you approve exactly what will be sent or changed.
    el("details", { open: "" }, el("summary", {}, `What exactly happens (${ap.tool})`),
      el("pre", { class: "approval-preview" }, ap.preview || JSON.stringify(ap.args, null, 2))),
    el("div", { class: "row approval-actions" }, scope, approve, decline, status));
  const go = async (yes) => {
    approve.disabled = decline.disabled = scope.disabled = true;
    status.textContent = yes ? "Approved" : "Declined";
    await onDecided(ap, yes, scope.value);
  };
  approve.addEventListener("click", () => go(true));
  decline.addEventListener("click", () => go(false));
  if (ap.status && ap.status !== "pending") {
    approve.disabled = decline.disabled = scope.disabled = true;
    status.textContent = ap.status;
  }
  return card;
}

async function decideApproval(ap, yes, scope) {
  const bot = addMessage("assistant", "…");
  const res = await fetch(`/api/approvals/${ap.id}/decide`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approve: yes, scope }),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    bot.bubble.textContent = "(not run)";
    bot.node.append(el("div", { class: "error" }, msg));
    return;
  }
  await streamInto(res, bot, null);
  refreshPendingBadge();
}

function handleEvent(ev, ctx) {
  const { bot, user } = ctx;
  if (ev.type === "decision" && user) user.meta.append(...decisionChips(ev.decision));
  else if (ev.type === "memory_saved")
    bot.meta.append(el("span", { class: "chip mem", title: "Saved to memory" },
      `${ev.updated ? "updated" : "remembered"}: ${ev.memory.text}`));
  else if (ev.type === "recalled")
    bot.meta.append(el("span", { class: "chip mem", title: ev.memories.map((m) => m.text).join("\n") },
      `recalled ${ev.memories.length} memor${ev.memories.length === 1 ? "y" : "ies"}`));
  else if (ev.type === "tool_start")
    bot.meta.append(el("span", { class: "chip tool", title: ev.tool }, `${ev.summary}…`));
  else if (ev.type === "tool_result")
    bot.meta.append(toolResultView(ev));
  else if (ev.type === "approval_required") {
    ctx.paused = true;
    bot.node.insertBefore(approvalCard(ev.approval, decideApproval), bot.meta);
    refreshPendingBadge();
  } else if (ev.type === "reset") {
    ctx.got = ""; bot.bubble.textContent = "…";
  } else if (ev.type === "token") {
    ctx.got += ev.text; setBubble(bot.bubble, "assistant", ctx.got);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  } else if (ev.type === "error") bot.node.append(el("div", { class: "error" }, ev.message));
  else if (ev.type === "done" && ev.model) {
    bot.meta.append(el("span", { class: "chip" }, ev.model));
    if (window.readAloud && voiceCanSpeak()) {
      const btn = el("button", { class: "ghost read-aloud", title: "Read this reply aloud" }, "🔊");
      btn.addEventListener("click", () => window.readAloud(ctx.got));
      bot.meta.append(btn);
    }
  }
}

function voiceCanSpeak() {
  const v = window.voiceInfo && window.voiceInfo();
  return Boolean(v && v.enabled && v.tts && v.tts.available);
}

async function streamInto(res, bot, user) {
  const ctx = { bot, user, got: "", paused: false };
  try {
    await readSSE(res, (ev) => handleEvent(ev, ctx));
  } catch (err) {
    bot.node.append(el("div", { class: "error" }, String(err.message || err)));
  }
  if (!ctx.got) bot.bubble.textContent = ctx.paused ? "I need your OK before I do this:" : "(no reply)";
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return ctx;
}

let sending = false;
async function send() {
  const text = input.value.trim();
  if (!text || sending) return null;
  let result = null;
  sending = true;
  $("#send").disabled = true;
  input.value = "";
  autosize();
  const user = addMessage("user", text);
  const bot = addMessage("assistant", "…");
  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const ctx = await streamInto(res, bot, user);
    result = { text: ctx.got, paused: ctx.paused };
  } catch (err) {
    bot.bubble.textContent = "(no reply)";
    bot.node.append(el("div", { class: "error" }, String(err.message || err)));
  } finally {
    sending = false;
    $("#send").disabled = false;
    input.focus();
  }
  return result;
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
  loadChannelStatus();
  loadGmailStatus();
  loadCloudStatus();
  loadPeers();
  loadPhone();
  document.querySelectorAll(".agent-name-inline").forEach((n) => { n.textContent = settings.agent_name; });
  const form = $("#settings-form");
  try {
    const vs = await api("/api/voice/status");
    $("#tts-voice").replaceChildren(el("option", { value: "" }, "System default"),
      ...vs.tts.voices.map((v) => el("option", { value: v }, v)));
  } catch (_) {}
  for (const [k, v] of Object.entries(settings)) {
    const f = form.elements[k];
    if (!f) continue;
    if (f.type === "checkbox") f.checked = Boolean(v); else f.value = v;
  }
}

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const values = {};
  for (const k of Object.keys(settings)) {
    const f = form.elements[k];
    if (f) values[k] = f.type === "checkbox" ? f.checked : f.value;
  }
  try {
    settings = await api("/api/settings", { method: "PUT", body: values });
    $("#settings-status").textContent = "Saved.";
    $("#agent-name").textContent = settings.agent_name;
    window.loadVoiceStatus?.();
  } catch (err) { $("#settings-status").textContent = err.message; }
  setTimeout(() => ($("#settings-status").textContent = ""), 3000);
});

/* ── nudges ───────────────────────────────────────────────────────────── */
const KIND_ICON = { brief: "☀️", event: "📅", reminder: "⏰", followup: "✉️", dream: "🌙", peer: "🤝", security: "🛡️" };

async function refreshNudgeBadge() {
  try {
    const { new: n } = await api("/api/nudges?limit=50");
    const b = $("#nudge-badge");
    b.textContent = n;
    b.classList.toggle("hidden", !n);
  } catch (_) {}
}

function when(ts) {
  const d = new Date(ts * 1000);
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
}

async function loadNudges() {
  const [{ items }, jobs] = await Promise.all([api("/api/nudges"), api("/api/jobs")]);
  $("#job-list").replaceChildren(
    ...(jobs.enabled ? [] : [el("div", { class: "card status-warn" }, "The agent won't reach out on its own: proactivity is off in Settings.")]),
    ...jobs.jobs.map((j) => {
      const btn = el("button", { class: "ghost", onclick: async () => {
        btn.disabled = true; btn.textContent = "Running…";
        try { await api(`/api/jobs/${j.name}/run`, { method: "POST" }); }
        catch (err) { alert(err.message); }
        loadNudges(); refreshNudgeBadge();
      } }, "Run now");
      return el("div", { class: "card job" },
        el("div", {}, el("strong", {}, j.title),
          el("div", { class: "muted" }, `Next: ${j.next_run ? when(j.next_run) : "—"}`
            + (j.last_run ? ` · last: ${when(j.last_run)} (${j.last_status})` : ""))),
        btn);
    }));
  $("#nudge-list").replaceChildren(...(items.length ? items.map((n) => el("div", { class: `card nudge kind-${n.kind}` },
      el("div", { class: "card-row" },
        el("span", {}, `${KIND_ICON[n.kind] || "•"} `, el("strong", {}, n.title), " ",
          el("span", { class: "badge" }, n.label),
          n.kind !== "brief" && n.kind !== "dream" ? el("span", { class: "urgency", title: `urgency ${n.urgency}/5` }, "●".repeat(n.urgency)) : null),
        el("span", { class: "muted" }, when(n.created_at))),
      n.body ? el("div", { class: "nudge-body" }, n.body) : null,
      n.data?.silent_reason ? el("div", { class: "muted small" }, `Not notified: ${n.data.silent_reason}`) : null,
      el("div", { class: "row nudge-actions" },
        n.data?.peer_inbox_id ? el("button", { class: "ghost", onclick: async () => {
          const text = prompt(`Your answer to ${n.title}:\n\n${n.body}`);
          if (!text) return;
          try { await api(`/api/peers/inbox/${n.data.peer_inbox_id}/reply`, { method: "POST", body: { text } });
            await api(`/api/nudges/${n.id}/dismiss`, { method: "POST" }); } catch (err) { alert(err.message); }
          loadNudges(); refreshNudgeBadge();
        } }, "Reply") : null,
        el("button", { class: "ghost", onclick: () => {
          input.value = `About "${n.title}" (${n.body.split("\n")[0]}): `;
          document.querySelector("button[data-tab=chat]").click(); input.focus(); autosize();
        } }, "Ask about this"),
        el("button", { class: "ghost", onclick: async () => { await api(`/api/nudges/${n.id}/snooze`, { method: "POST", body: { hours: 1 } }); loadNudges(); refreshNudgeBadge(); } }, "Snooze 1 h"),
        el("button", { class: "ghost", onclick: async () => { await api(`/api/nudges/${n.id}/dismiss`, { method: "POST" }); loadNudges(); refreshNudgeBadge(); } }, "Dismiss"))))
    : [el("p", { class: "muted" }, "Nothing yet. Press Run now on a job above to try it.")]));
}

/* ── approvals ────────────────────────────────────────────────────────── */
async function refreshPendingBadge() {
  try {
    const pending = await api("/api/approvals?status=pending");
    const b = $("#pending-badge");
    b.textContent = pending.length;
    b.classList.toggle("hidden", !pending.length);
  } catch (_) {}
}

async function loadApprovals() {
  const [pending, history, grants] = await Promise.all([
    api("/api/approvals?status=pending"), api("/api/approvals?limit=50"), api("/api/grants")]);
  $("#approvals-pending").replaceChildren(...(pending.length
    ? pending.map((ap) => approvalCard(ap, async (a, yes, scope) => {
        document.querySelector("button[data-tab=chat]").click();
        await decideApproval(a, yes, scope);
        refreshPendingBadge();
      }))
    : [el("p", { class: "muted" }, "Nothing is waiting for you.")]));
  $("#grants").replaceChildren(...(grants.length ? grants.map((g) => el("div", { class: "card card-row" },
      el("span", {}, el("strong", {}, g.tool), " · ", g.label,
        g.expires_at ? ` (until ${new Date(g.expires_at * 1000).toLocaleTimeString()})` : ""),
      el("button", { class: "ghost", onclick: async () => { await api(`/api/grants/${g.id}`, { method: "DELETE" }); loadApprovals(); } }, "Revoke")))
    : [el("p", { class: "muted" }, "No standing permissions. Every change asks first.")]));
  const done = history.filter((a) => a.status !== "pending");
  $("#approvals-history").replaceChildren(...(done.length ? done.map((a) => el("div", { class: "card card-row" },
      el("span", {}, el("span", { class: `badge tier-${a.tier}` }, a.tier), " ", a.summary),
      el("span", { class: `status-${a.status === "approved" ? "ok" : a.status === "denied" ? "fail" : "warn"}` },
        a.status + (a.scope && a.scope !== "once" ? ` (${a.scope})` : ""))))
    : [el("p", { class: "muted" }, "No decisions yet.")]));
  refreshPendingBadge();
}

/* ── activity (audit log) ─────────────────────────────────────────────── */
async function loadActivity() {
  const [rows, v] = await Promise.all([api("/api/audit?limit=200"), api("/api/audit/verify")]);
  const banner = $("#audit-verify");
  banner.className = `card ${v.ok ? "status-ok" : "status-fail"}`;
  banner.textContent = v.ok
    ? `Audit chain intact: ${v.count} entr${v.count === 1 ? "y" : "ies"}, each sealed with the previous entry's hash.`
    : `Audit chain BROKEN at entry ${v.broken_at}: the log was modified outside the app.`;
  $("#audit-list").replaceChildren(...(rows.length ? rows.map((r) => el("div", { class: "card" },
      el("div", { class: "card-row" },
        el("span", {}, el("strong", {}, r.kind.replaceAll("_", " ")), r.tool ? ` · ${r.tool}` : "",
          r.tier ? " " : "", r.tier ? el("span", { class: `badge tier-${r.tier}` }, r.tier) : ""),
        el("span", { class: "muted" }, new Date(r.ts * 1000).toLocaleString())),
      r.detail ? el("div", { class: "muted" }, `${r.outcome ? r.outcome + " · " : ""}${r.detail}`) : null,
      r.args ? el("details", {}, el("summary", {}, "Arguments"), el("pre", {}, JSON.stringify(r.args, null, 2))) : null))
    : [el("p", { class: "muted" }, "Nothing has happened yet.")]));
}

/* ── connectors ───────────────────────────────────────────────────────── */
async function loadConnectors() {
  const cons = await api("/api/connectors");
  if (!settings.file_roots) settings = await api("/api/settings");
  $("#connector-list").replaceChildren(...cons.map((c) => {
    const toggle = el("input", { type: "checkbox", "aria-label": `Enable ${c.name}` });
    toggle.checked = c.enabled;
    toggle.disabled = !c.available;
    toggle.addEventListener("change", async () => {
      settings = await api("/api/settings", { method: "PUT", body: { [c.setting]: toggle.checked } });
      loadConnectors();
    });
    const result = el("span", { class: "muted" });
    const test = c.testable && c.active ? el("button", { class: "ghost", onclick: async () => {
      test.disabled = true; result.className = "muted"; result.textContent = "Testing… (allow the macOS prompt if one appears)";
      try {
        const r = await api(`/api/connectors/${c.id}/test`, { method: "POST" });
        result.className = r.ok ? "status-ok" : "status-fail"; result.textContent = r.message;
      } catch (err) { result.className = "status-fail"; result.textContent = err.message; }
      test.disabled = false;
    } }, "Test") : null;
    return el("div", { class: "card" },
      el("div", { class: "card-row" },
        el("label", { class: "row" }, toggle, el("strong", {}, c.name)),
        el("div", { class: "row" }, c.note ? el("span", { class: "status-warn" }, c.note) : null, test)),
      el("div", { class: "muted" }, c.about),
      c.tools.length ? el("div", { class: "meta" }, c.tools.map((t) =>
        el("span", { class: `badge tier-${t.tier}`, title: TIER_LABEL[t.tier] }, `${t.name} · ${t.tier}`))) : null,
      result);
  }));
  $("#file-roots").value = settings.file_roots || "";
  loadSkills();
}

async function loadSkills() {
  const info = await api("/api/skills");
  $("#skills-folder").textContent = `Folder: ${info.folder}. Create one in Terminal with: localagent skill new my-skill`
    + (info.sandbox ? "" : " (script skills need macOS's sandbox and won't run on this computer)");
  $("#skill-list").replaceChildren(...(info.skills.length ? info.skills.map((s) => el("div", { class: "card" },
    el("div", { class: "card-row" }, el("strong", {}, s.name),
      el("span", { class: `badge tier-${s.tier}` }, `${s.tool} · ${s.tier}${s.network ? " · network" : ""}`)),
    el("div", { class: "muted" }, s.description || ""),
    s.problems.length ? el("div", { class: "status-fail small" }, "Not loaded: " + s.problems.join("; ")) : null))
    : [el("div", { class: "muted small" }, "No skills yet.")]));
}

$("#roots-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  settings = await api("/api/settings", { method: "PUT", body: { file_roots: $("#file-roots").value } });
  loadConnectors();
});

async function loadPhone() {
  try {
    const p = await api("/api/phone");
    $("#phone-status").textContent = !p.enabled ? "Off."
      : `${p.listening ? `Listening on 127.0.0.1:${p.port}` : "Not listening (restart the agent)"} · token ${p.has_token ? "saved" : "missing"} · PIN ${p.has_pin ? "set" : "missing (calls are refused)"}`
        + (p.webhook ? ` · Twilio "A call comes in" webhook: ${p.webhook}` : " · add the public URL");
  } catch (_) {}
}
$("#phone-token-save").addEventListener("click", async () => {
  try { await api("/api/phone/token", { method: "PUT", body: { token: $("#phone-token").value.trim() } }); $("#phone-token").value = ""; }
  catch (err) { $("#phone-status").textContent = err.message; return; }
  loadPhone();
});

$("#phone-pin-save").addEventListener("click", async () => {
  try { await api("/api/phone/pin", { method: "PUT", body: { pin: $("#phone-pin").value.trim() } }); $("#phone-pin").value = ""; }
  catch (err) { $("#phone-status").textContent = err.message; return; }
  loadPhone();
});

async function loadPeers() {
  const box = $("#peers-box");
  let p;
  try { p = await api("/api/peers"); } catch (_) { return; }
  if (!p.enabled) { box.replaceChildren(el("p", { class: "muted small" }, "Off. Tick the box and Save to pair agents.")); return; }
  const code = el("textarea", { class: "invite-code hidden", readonly: "", rows: "3" });
  const accept = el("input", { placeholder: "Paste a friend's invite code (la1-…)" });
  const status = el("span", { class: "muted small" });
  box.replaceChildren(
    el("div", { class: "muted small" }, `This agent: ${p.me.name} at ${p.me.addr} · ${p.listening ? "listening" : "not listening (restart the agent)"} · fingerprint ${p.me.fingerprint}`),
    el("div", { class: "row", style: "margin-top:8px;flex-wrap:wrap" },
      el("button", { type: "button", class: "secondary", onclick: async () => {
        try { const r = await api("/api/peers/invite", { method: "POST" }); code.value = r.code; code.classList.remove("hidden"); code.select();
          status.textContent = "Send this code to your friend (it works once, for 7 days)."; } catch (err) { status.textContent = err.message; }
      } }, "Create an invite"), status),
    code,
    el("div", { class: "inline-form" }, accept, el("button", { type: "button", class: "secondary", onclick: async () => {
      try { const peer = await api("/api/peers/accept", { method: "POST", body: { code: accept.value } });
        status.textContent = `Paired with ${peer.owner || peer.name}'s agent.`; loadPeers(); } catch (err) { status.textContent = err.message; }
    } }, "Accept")),
    ...p.peers.map((x) => el("div", { class: "card" },
      el("div", { class: "card-row" }, el("strong", {}, `${x.owner || x.name}'s agent (${x.name})`),
        el("button", { type: "button", class: "ghost", onclick: async () => {
          if (!confirm(`Unpair ${x.name}?`)) return;
          await api(`/api/peers/${x.id}`, { method: "DELETE" }); loadPeers();
        } }, "Remove")),
      el("div", { class: "muted small" }, x.addr),
      el("div", { class: "row small", style: "margin:6px 0;flex-wrap:wrap" },
        el("span", {}, `Safety code: `, el("strong", { class: "safety-code" }, x.safety_code)),
        x.verified ? el("span", { class: "badge tier-read" }, "verified")
          : el("button", { type: "button", class: "secondary", onclick: async () => {
              if (!confirm(`Does ${x.owner || x.name} see exactly ${x.safety_code} on their screen? `
                + "Check together in person or on a call, not by text.")) return;
              await api(`/api/peers/${x.id}/verify`, { method: "POST" }); loadPeers();
            } }, "They match")),
      x.verified ? null : el("div", { class: "muted small" },
        "Not verified yet: nothing is answered for this agent automatically, and you can't ask it things."),
      ...Object.entries(p.scopes).map(([k, label]) => {
        const cb = el("input", { type: "checkbox" }); cb.checked = x.scopes.includes(k);
        cb.addEventListener("change", async () => {
          const scopes = Object.keys(p.scopes).filter((s) => (s === k ? cb.checked : x.scopes.includes(s)));
          x.scopes = (await api(`/api/peers/${x.id}`, { method: "PUT", body: { scopes } })).scopes;
        });
        return el("label", { class: "check" }, cb, ` ${label}`);
      }))),
    ...p.waiting.map((w) => {
      const reply = el("input", { placeholder: "Your answer" });
      return el("div", { class: "card nudge kind-peer" },
        el("div", {}, el("strong", {}, `${w.owner || w.name}'s agent asks: `), w.text),
        el("div", { class: "inline-form" }, reply, el("button", { type: "button", class: "secondary", onclick: async () => {
          await api(`/api/peers/inbox/${w.id}/reply`, { method: "POST", body: { text: reply.value } }); loadPeers();
        } }, "Send answer")));
    }));
}

async function loadCloudStatus() {
  try {
    const c = await api("/api/cloud");
    $("#cloud-status").textContent = !c.installed ? "Cloud add-on missing: pipx inject localaiagent anthropic"
      : c.has_key ? `Key saved (${c.vault.startsWith("file") ? "file" : "Keychain"})` : "No key yet";
    $("#cloud-key-remove").classList.toggle("hidden", !c.has_key);
  } catch (_) {}
}

$("#cloud-key-save").addEventListener("click", async () => {
  try {
    await api("/api/cloud/key", { method: "PUT", body: { key: $("#cloud-key").value.trim() } });
    $("#cloud-key").value = "";
  } catch (err) { $("#cloud-status").textContent = err.message; return; }
  loadCloudStatus();
});
$("#cloud-key-remove").addEventListener("click", async () => {
  await api("/api/cloud/key", { method: "PUT", body: { key: "" } }).catch(() => null);
  loadCloudStatus();
});

async function loadGmailStatus() {
  try {
    const g = await api("/api/gmail");
    $("#gmail-client-id").value = g.client_id || "";
    $("#gmail-client-secret").placeholder = g.has_secret ? "(saved; type to replace)" : "paste the client secret";
    $("#gmail-status").textContent = g.connected ? `Connected as ${g.account}` : "Not connected";
    $("#gmail-disconnect").classList.toggle("hidden", !g.connected);
  } catch (_) {}
}

$("#gmail-connect").addEventListener("click", async () => {
  $("#gmail-status").textContent = "Saving…";
  try {
    const body = { client_id: $("#gmail-client-id").value.trim() };
    const secret = $("#gmail-client-secret").value.trim();
    if (secret) body.client_secret = secret;
    await api("/api/gmail/client", { method: "PUT", body });
    $("#gmail-client-secret").value = "";
    $("#gmail-status").textContent = "Finish signing in in the new tab, then come back here.";
    window.open("/api/gmail/login", "_blank");
    const until = Date.now() + 5 * 60 * 1000;
    const poll = setInterval(async () => {
      const g = await api("/api/gmail").catch(() => null);
      if ((g && g.connected) || Date.now() > until) { clearInterval(poll); loadGmailStatus(); }
    }, 2000);
  } catch (err) { $("#gmail-status").textContent = err.message; }
});

$("#gmail-disconnect").addEventListener("click", async () => {
  await api("/api/gmail/disconnect", { method: "POST" }).catch(() => null);
  loadGmailStatus();
});

async function loadChannelStatus() {
  try {
    const c = (await api("/api/channels")).imessage;
    $("#channel-status").textContent = !c.available ? "Needs macOS."
      : !c.enabled ? "Off." : `Status: ${c.status}${c.error ? " — " + c.error : ""}`;
  } catch (_) {}
}

$("#channel-test").addEventListener("click", async () => {
  $("#channel-status").textContent = "Sending…";
  try {
    const r = await api("/api/channels/imessage/test", { method: "POST" });
    $("#channel-status").textContent = r.message;
  } catch (err) { $("#channel-status").textContent = err.message; }
});

$("#forget-screen").addEventListener("click", async () => {
  try {
    const r = await api("/api/screen", { method: "DELETE" });
    $("#screen-status").textContent = `Forgot ${r.deleted} snapshot(s).`;
  } catch (err) { $("#screen-status").textContent = err.message; }
});

/* ── boot ─────────────────────────────────────────────────────────────── */
async function boot() {
  try {
    [settings, questions] = await Promise.all([api("/api/settings"), api("/api/questions")]);
    $("#agent-name").textContent = settings.agent_name;
    document.title = `${settings.agent_name} · LocalAIAgent`;
  } catch (_) {}
  await loadHistory();
  refreshPendingBadge();
  refreshNudgeBadge();
  setInterval(() => { refreshNudgeBadge(); refreshPendingBadge(); }, 60000);
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

/* ── trust & transparency ─────────────────────────────────────────────── */
const PRESETS = [
  ["observer", "Observer", "Looks things up and answers. Never creates, sends or changes anything."],
  ["assistant", "Assistant", "Also prepares drafts (emails, events, forms) for you to finish. Never sends."],
  ["agent", "Agent", "Also acts: sends, books, changes, always with your approval for anything that leaves or can't be undone."],
];
const whenTs = (ts) => (ts ? new Date(ts * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "never");
let trustCache = null;

function renderIndicators(o) {
  const ind = [];
  if (o.paused) ind.push(el("span", { class: "ind paused", title: "Paused: read-only, nothing runs in the background" }, "⏸ paused"));
  const on = Object.fromEntries(o.capabilities.map((c) => [c.id, c.enabled]));
  if (on.wake) ind.push(el("span", { class: "ind", title: "Listening for the wake word while this tab is open" }, "🎙"));
  if (on.screen) ind.push(el("span", { class: "ind", title: "Screen context is on" }, "👁"));
  if (on.cloud) ind.push(el("span", { class: "ind", title: "Cloud model allowed (each request asks)" }, "☁️"));
  if (on.phone) ind.push(el("span", { class: "ind", title: "Phone line answering" }, "📞"));
  if (on.peers) ind.push(el("span", { class: "ind", title: "Friends' agents can reach this computer" }, "🤝"));
  $("#indicators").replaceChildren(...ind);
  const btn = $("#pause-btn");
  btn.textContent = o.paused ? "▶ Resume" : "⏸ Pause";
  btn.classList.toggle("on", o.paused);
}

async function refreshTrustBits() {
  try { trustCache = await api("/api/trust"); renderIndicators(trustCache); } catch (_) { return; }
  // New install: personal connectors start off. Point to where they're switched on, once.
  let seen = null;
  try { seen = localStorage.getItem("la-trust-intro"); } catch (_) {}
  const personal = ["mail", "messages", "contacts", "apps"];
  const anyOn = trustCache.capabilities.some((c) => personal.includes(c.id) && (c.enabled || c.last_used));
  if (!seen && !anyOn && trustCache.capabilities.some((c) => c.id === "mail" && c.available)) {
    const b = $("#banner");
    b.replaceChildren("Welcome! Mail, Messages, Contacts and Mac apps are off until you choose. ",
      el("button", { type: "button", class: "secondary", onclick: () => {
        try { localStorage.setItem("la-trust-intro", "1"); } catch (_) {}
        b.classList.add("hidden"); document.querySelector("button[data-tab=trust]").click();
      } }, "Choose what I can help with"));
    b.classList.remove("hidden");
  }
}

$("#pause-btn").addEventListener("click", async () => {
  const paused = !(trustCache && trustCache.paused);
  trustCache = await api("/api/trust/pause", { method: "POST", body: { paused } });
  renderIndicators(trustCache);
  if (document.querySelector("#tab-trust.active")) renderTrust(trustCache);
});

function trustRange() {
  const q = new URLSearchParams();
  if ($("#trust-since").value) q.set("since", $("#trust-since").value);
  if ($("#trust-until").value) q.set("until", $("#trust-until").value);
  return q;
}

const RISK_DOT = { low: "🟢", medium: "🟠", high: "🔴" };

async function toggleCapability(c, enable) {
  let forget = false;
  if (!enable && ["screen", "gmail", "cloud", "phone", "peers", "imessage_channel"].includes(c.id)) {
    forget = confirm(`Also delete what the agent keeps for ${c.name} (sign-ins, keys, pairings, cached text)?`);
  }
  const r = await api(`/api/trust/capability/${c.id}`, { method: "POST", body: { enabled: enable, forget } });
  if (r.forgotten?.length) alert(`Deleted: ${r.forgotten.join(", ")}`);
  renderTrust(r);
  window.loadVoiceStatus?.();          // the wake word and voice react to these switches at once
  return r;
}

function capRow(c) {
  const toggle = el("input", { type: "checkbox", "aria-label": `Turn ${c.name} on or off` });
  toggle.checked = c.enabled;
  toggle.disabled = !c.available;
  toggle.addEventListener("change", async () => {
    try { await toggleCapability(c, toggle.checked); } catch (err) { toggle.checked = !toggle.checked; alert(err.message); }
  });
  const perms = c.permissions.map((p) => p.link
    ? el("a", { href: p.link, title: "Open this page of System Settings" }, p.name) : p.name);
  return el("div", { class: `cap-row ${c.enabled ? "on" : "off"}` },
    el("label", { class: "cap-switch" }, toggle),
    el("details", { class: "cap-details" },
      el("summary", {},
        el("span", { class: "cap-name" }, c.name),
        el("span", { class: `risk ${c.risk}`, title: `${c.risk} risk` }, `${RISK_DOT[c.risk] || ""} ${c.risk}`),
        el("span", { class: "cap-meta" }, c.available ? (c.last_used ? `used ${whenTs(c.last_used)}` : "never used")
          : "needs a Mac", c.note && c.available ? ` · ${c.note}` : "")),
      el("dl", { class: "cap-facts" },
        el("dt", {}, "Reads"), el("dd", {}, c.reads),
        el("dt", {}, "Can leave this computer"), el("dd", {}, c.leaves),
        el("dt", {}, "Risk"), el("dd", {}, c.risk_text),
        el("dt", {}, "Safeguards"), el("dd", {}, c.safeguards),
        perms.length ? el("dt", {}, "System permission") : null,
        perms.length ? el("dd", {}, ...perms.flatMap((x, i) => (i ? [", ", x] : [x]))) : null)));
}

function renderTrust(o) {
  trustCache = o;
  renderIndicators(o);
  const attention = o.posture.filter((p) => p.ok === false);
  const presets = el("div", { class: "segmented", role: "radiogroup", "aria-label": "Trust preset" },
    PRESETS.map(([id, name, about]) => {
      const b = el("button", { type: "button", class: o.autonomy === id ? "on" : "", title: about,
        role: "radio", "aria-checked": String(o.autonomy === id) }, name);
      b.addEventListener("click", async () => renderTrust(await api("/api/trust/autonomy", { method: "PUT", body: { autonomy: id } })));
      return b;
    }));
  const about = PRESETS.find(([id]) => id === o.autonomy)?.[2] || "";
  $("#trust-status").replaceChildren(
    el("div", { class: "status-line" },
      el("span", { class: "status-big" }, o.paused ? "⏸ Paused: I only answer you here, read-only."
        : attention.length ? `⚠ ${attention.length} thing${attention.length === 1 ? "" : "s"} need${attention.length === 1 ? "s" : ""} your attention`
        : "✅ All good"),
      el("button", { type: "button", class: o.paused ? "primary" : "secondary", onclick: async () => {
        renderTrust(await api("/api/trust/pause", { method: "POST", body: { paused: !o.paused } }));
      } }, o.paused ? "▶ Resume" : "⏸ Pause")),
    attention.length ? el("ul", { class: "attention" }, attention.map((p) =>
      el("li", {}, el("strong", {}, p.name), ` — ${p.detail}`, p.fix ? el("div", { class: "muted small" }, `Fix: ${p.fix}`) : null))) : null,
    el("div", { class: "preset-row" }, el("span", { class: "muted small" }, "What I may do:"), presets,
      el("span", { class: "muted small preset-about" }, about)));

  const on = o.capabilities.filter((c) => c.enabled);
  const off = o.capabilities.filter((c) => !c.enabled);
  $("#trust-caps").replaceChildren(
    el("h3", {}, `On (${on.length})`), ...(on.length ? on.map(capRow) : [el("p", { class: "muted small" }, "Nothing is on.")]),
    el("h3", {}, `Off (${off.length})`), ...off.map(capRow));

  const failing = o.posture.filter((p) => p.ok !== true);
  const passing = o.posture.filter((p) => p.ok === true);
  const checkRow = (p) => el("div", { class: "card check-row" },
    el("span", { class: "mark" }, p.ok === true ? "✅" : p.ok === false ? "⚠️" : "❔"),
    el("div", {}, el("strong", {}, p.name), el("div", { class: "muted small" }, p.detail),
      p.fix ? el("div", { class: "small" }, `Fix: ${p.fix}`) : null));
  $("#trust-posture").replaceChildren(...failing.map(checkRow),
    passing.length ? el("details", { class: "passed" }, el("summary", {}, `${passing.length} checks passed`), ...passing.map(checkRow)) : null);

  $("#trust-week").textContent = `${o.egress_7d} thing${o.egress_7d === 1 ? "" : "s"} left this computer in the last 7 days `
    + `(see Activity). ${on.length} of ${o.capabilities.filter((c) => c.available).length} capabilities on. `
    + `Secrets kept in ${o.vault}. Version ${o.version}.`;

  $("#trust-grants").replaceChildren(...(o.grants.length ? o.grants.map((g) => el("div", { class: "card card-row" },
    el("span", {}, el("strong", {}, g.tool), " · ", g.label,
      g.expires_at ? el("span", { class: "muted small" }, ` · until ${whenTs(g.expires_at)}`) : null),
    el("button", { type: "button", class: "ghost", onclick: async () => {
      await api(`/api/grants/${g.id}`, { method: "DELETE" }); loadTrust();
    } }, "Revoke"))) : [el("p", { class: "muted small" }, "None. Everything that needs your OK will ask.")]));
}

/* sub-tabs inside Trust */
function showTrustSub(name) {
  document.querySelectorAll("#tab-trust .subtab").forEach((b) => b.classList.toggle("active", b.dataset.sub === name));
  document.querySelectorAll("#tab-trust .subpanel").forEach((p) => p.classList.toggle("active", p.dataset.sub === name));
  try { localStorage.setItem("la-trust-sub", name); } catch (_) {}
}
document.querySelectorAll("#tab-trust .subtab").forEach((b) => b.addEventListener("click", () => showTrustSub(b.dataset.sub)));
try { const sub = localStorage.getItem("la-trust-sub"); if (sub) showTrustSub(sub); } catch (_) {}

/* Ask about privacy & security */
const ASK_EXAMPLES = ["What did you send last week?", "What can you access?", "Who can control you?",
  "Is my data encrypted?", "Anything need my attention?"];
$("#trust-ask-chips").replaceChildren(...ASK_EXAMPLES.map((q) => el("button", { type: "button", class: "chip-btn",
  onclick: () => { $("#trust-ask").value = q; askTrust(q); } }, q)));

async function askTrust(q) {
  const box = $("#trust-answer");
  box.classList.remove("hidden");
  box.replaceChildren(el("p", { class: "muted small" }, "Looking at your records…"));
  try {
    const r = await api("/api/trust/ask", { method: "POST", body: { question: q } });
    box.replaceChildren(
      Object.assign(el("div", { class: "answer-text md" }), { innerHTML: md(r.answer) }),
      r.actions.length ? el("div", { class: "row answer-actions" }, r.actions.map((a) => el("button", {
        type: "button", class: "secondary", onclick: async () => {
          try { await toggleCapability(trustCache.capabilities.find((c) => c.id === a.capability), a.enabled); askTrust(q); }
          catch (err) { alert(err.message); }
        } }, a.label))) : null,
      el("details", { class: "based-on" }, el("summary", {}, r.source === "records" ? "Based on your records" : "Based on your records (worded by the local model)"),
        el("ul", {}, r.facts.map((f) => el("li", {}, f)))));
  } catch (err) { box.replaceChildren(el("p", { class: "error-text" }, err.message)); }
}
$("#trust-ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#trust-ask").value.trim();
  if (q) askTrust(q);
});

async function loadEgress() {
  const rows = await api(`/api/trust/egress?${trustRange()}`);
  $("#trust-egress").replaceChildren(...(rows.length ? rows.slice(0, 100).map((e) => el("div", { class: "card egress-row" },
    el("span", { class: "muted" }, whenTs(e.ts)),
    el("span", {}, el("strong", {}, e.what), " → ", e.to,
      e.approved === true ? el("span", { class: "badge tier-read" }, " you approved") : e.approved === false && e.tier !== "read" && e.tier !== "draft"
        ? el("span", { class: "badge tier-write" }, " standing permission") : null),
    e.content ? el("span", { class: "content" }, e.content.slice(0, 300)) : null))
    : [el("p", { class: "muted small" }, "Nothing left this computer in this period.")]));
}

async function loadTrust() {
  renderTrust(await api("/api/trust"));
  await loadEgress();
}

$("#trust-run-checks").addEventListener("click", async () => {
  const btn = $("#trust-run-checks");
  const box = $("#trust-checks");
  btn.disabled = true;
  btn.textContent = "Checking…";
  box.replaceChildren(el("p", { class: "muted small" }, "Checking your activity log…"));
  try {
    const r = await api(`/api/trust/checks?${trustRange()}`);
    const icon = { critical: "⛔", high: "⚠️", medium: "⚠️", info: "ℹ️", ok: "✅" };
    box.replaceChildren(
      el("p", { class: "small" }, el("strong", {}, "Checked "), `${r.entries} log entries and ${r.egress} outgoing item(s)`
        + (r.seconds != null ? ` in ${r.seconds} s` : "") + ". ", el("span", { class: "muted" }, r.not_covered)),
      ...r.findings.map((f) => el("div", { class: `card finding ${f.severity}` },
        el("div", {}, `${icon[f.severity] || "•"} `, el("strong", {}, f.title), el("span", { class: "muted small" }, ` · ${f.severity}`)),
        f.detail ? el("div", { class: "small" }, f.detail) : null,
        f.items.length ? el("ul", {}, f.items.map((i) => el("li", {}, i))) : null)));
    loadEgress();
  } catch (err) {
    box.replaceChildren(el("p", { class: "error-text" }, `Couldn't run the checks: ${err.message}`));
  } finally {
    btn.disabled = false;
    btn.textContent = "Run checks";
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
});

$("#trust-download").addEventListener("click", () => {
  const q = trustRange();
  if (!$("#trust-redact").checked) {
    if (!confirm("This record will contain your personal data as-is: email addresses, phone numbers, names, "
      + "message text. Only share it with someone you trust. Continue?")) return;
    q.set("raw", "true"); q.set("confirm_raw", "yes");
  }
  const a = el("a", { href: `/api/trust/export?${q}`, download: "" });
  document.body.append(a); a.click(); a.remove();
});

refreshTrustBits();
setInterval(refreshTrustBits, 60000);
