/* atlas web — vanilla js, no build step. */

const $ = (s) => document.querySelector(s);

const state = {
  sessions: [],
  current: null,
  mode: "coach",
  modes: [],
  models: [],
  defaultModel: "",
  baseUrl: "",
  sending: false,
  controller: null,
  filter: "",
};

let lifecycleTimer = null;

function lifecycleHeartbeat() {
  fetch("/api/lifecycle", { method: "POST", keepalive: true }).catch(() => {});
}

function startLifecycle() {
  if (lifecycleTimer) clearInterval(lifecycleTimer);
  lifecycleHeartbeat();
  lifecycleTimer = setInterval(lifecycleHeartbeat, 3000);
}

window.addEventListener("pagehide", () => {
  if (lifecycleTimer) {
    clearInterval(lifecycleTimer);
    lifecycleTimer = null;
  }
  navigator.sendBeacon("/api/lifecycle/close", new Blob(["{}"], {
    type: "application/json",
  }));
});

// Safari and Firefox may restore the page from back/forward cache without
// running boot() again. Reclaim the server lease when that happens.
window.addEventListener("pageshow", (event) => {
  if (event.persisted) startLifecycle();
});

/* ---------------------------------------------------------------- utils */

const esc = (s) =>
  s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function md(text) {
  const parts = esc(text).split(/```/);
  return parts
    .map((part, i) => {
      if (i % 2) return `<pre><code>${part.replace(/^[a-z]*\n/, "")}</code></pre>`;
      return part
        .replace(/`([^`\n]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    })
    .join("");
}

const ago = (iso) => {
  const then = new Date(iso.replace(" ", "T") + "Z").getTime();
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.round(mins / 60)}h`;
  return `${Math.round(mins / 1440)}d`;
};

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

/* ---------------------------------------------------------------- render */

function renderSessions() {
  const nav = $("#sessions");
  const q = state.filter.toLowerCase();
  const list = state.sessions.filter(
    (s) => !q || s.title.toLowerCase().includes(q) || s.mode.includes(q),
  );

  nav.innerHTML = "";
  if (!list.length) {
    nav.innerHTML = `<div class="empty" style="padding:8px 4px">no chats${q ? " match" : " yet"}</div>`;
    return;
  }

  for (const s of list) {
    const el = document.createElement("div");
    el.className = "chat" + (s.id === state.current ? " active" : "");
    el.innerHTML = `
      <div class="name">${esc(s.title)}</div>
      <button class="kill" title="delete">✕</button>
      <div class="meta">${s.mode} · ${s.turns} msg · ${ago(s.updated)}</div>`;
    el.onclick = (e) => {
      if (e.target.classList.contains("kill")) return;
      openSession(s.id);
      $("#sidebar").classList.remove("open");
    };
    el.querySelector(".name").ondblclick = () => renameSession(s);
    el.querySelector(".kill").onclick = (e) => {
      e.stopPropagation();
      removeSession(s);
    };
    nav.appendChild(el);
  }
}

function renderStats(data) {
  $("#stats").innerHTML = `
    <span>notes <b>${data.notes}</b></span>
    <span>chats <b>${data.sessions}</b></span>
    <span>turns <b>${data.turns}</b></span>
    <span>${data.frontier ? "frontier on" : "local only"}</span>`;
  $("#model").textContent = `${data.model} · ${data.where}`;
  state.modes = data.modes || [];
  const select = $("#mode");
  select.innerHTML = state.modes
    .map((m) => `<option ${m === state.mode ? "selected" : ""}>${m}</option>`)
    .join("");
}

function bubble(role, text = "") {
  const holder = document.createElement("article");
  holder.className = `msg ${role}`;
  holder.innerHTML = `<div class="who">${role === "user" ? "you" : "atlas"}</div>
                      <div class="body"></div>`;
  const body = holder.querySelector(".body");
  body.innerHTML = md(text);
  $("#messages").appendChild(holder);
  scrollDown();
  return { holder, body, text };
}

function toolLine(name, result) {
  const el = document.createElement("div");
  el.className = "tool";
  el.innerHTML = `<b>${esc(name)}</b> → ${esc(result)}`;
  $("#messages").appendChild(el);
  scrollDown();
}

function scrollDown() {
  const box = $("#messages");
  const near = box.scrollHeight - box.scrollTop - box.clientHeight < 200;
  if (near || state.sending) box.scrollTop = box.scrollHeight;
}

/* ---------------------------------------------------------------- actions */

async function refreshSessions() {
  const { sessions } = await api("/api/sessions");
  state.sessions = sessions;
  renderSessions();
}

async function refreshStats() {
  renderStats(await api("/api/stats"));
}

function renderModels(info) {
  state.models = info.models || [];
  state.defaultModel = info.model || "";
  state.baseUrl = info.base_url || "";

  const select = $("#model-pick");
  const chosen = select.value;
  select.innerHTML =
    `<option value="">default · ${esc(state.defaultModel)}</option>` +
    state.models.map((m) => `<option>${esc(m)}</option>`).join("");
  if (state.models.includes(chosen)) select.value = chosen;

  const list = $("#cfg-models");
  if (list) list.innerHTML = state.models.map((m) => `<option>${esc(m)}</option>`).join("");
}

async function refreshModels() {
  renderModels(await api("/api/models"));
}

async function newChat() {
  const { id } = await api("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ mode: state.mode, model: $("#model-pick").value || undefined }),
  });
  await refreshSessions();
  await openSession(id);
  $("#input").focus();
}

async function openSession(id) {
  const { session, messages } = await api(`/api/sessions/${id}`);
  state.current = id;
  state.mode = session.mode;
  $("#title").textContent = session.title;
  $("#mode-chip").textContent = session.mode;
  $("#mode").value = session.mode;
  $("#model-pick").value = session.model || "";

  const box = $("#messages");
  box.innerHTML = "";
  if (!messages.length) {
    box.innerHTML = `<div class="empty">
      Ask anything. It remembers across chats.<br>
      <kbd>enter</kbd> send · <kbd>shift</kbd>+<kbd>enter</kbd> newline · <kbd>⌘K</kbd> new chat
    </div>`;
  }
  for (const m of messages) bubble(m.role, m.content);
  renderSessions();
  $("#input").focus();
}

async function renameSession(s) {
  const title = prompt("rename chat", s.title);
  if (!title || title === s.title) return;
  await api(`/api/sessions/${s.id}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
  await refreshSessions();
  if (s.id === state.current) $("#title").textContent = title;
}

async function removeSession(s) {
  if (!confirm(`delete "${s.title}"? this cannot be undone.`)) return;
  try {
    await api(`/api/sessions/${s.id}`, { method: "DELETE" });
  } catch (e) {
    alert(e.message);
    return;
  }
  await refreshSessions();
  await refreshStats();
  if (s.id === state.current) {
    state.current = null;
    if (state.sessions.length) await openSession(state.sessions[0].id);
    else await newChat();
  }
}

/* ---------------------------------------------------------------- streaming */

async function send(text) {
  if (state.sending) return;
  if (!state.current) await newChat();

  state.sending = true;
  $("#stop").hidden = false;
  $("#send").hidden = true;
  $("#status").textContent = "thinking";
  $("#status").classList.add("live");
  document.querySelector(".empty")?.remove();

  bubble("user", text);
  const reply = bubble("assistant", "");
  reply.body.classList.add("caret");

  state.controller = new AbortController();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.current,
        message: text,
        mode: state.mode,
      }),
      signal: state.controller.signal,
    });

    if (!res.ok || !res.body) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `http ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        handleEvent(block, reply);
      }
    }
  } catch (err) {
    if (err.name !== "AbortError") {
      reply.body.innerHTML = `<span style="color:var(--danger)">${esc(err.message)}</span>`;
    }
  } finally {
    reply.body.classList.remove("caret");
    state.sending = false;
    state.controller = null;
    $("#stop").hidden = true;
    $("#send").hidden = false;
    $("#status").textContent = "";
    $("#status").classList.remove("live");
    await refreshSessions();
    await refreshStats();
  }
}

function parseEvent(block) {
  let name = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return null;
  try {
    return { name, data: JSON.parse(data) };
  } catch {
    return null;
  }
}

function handleEvent(block, reply) {
  const parsed = parseEvent(block);
  if (!parsed) return;
  const event = parsed.name;
  const payload = parsed.data;

  if (event === "delta") {
    reply.text += payload.text;
    reply.body.innerHTML = md(reply.text);
    scrollDown();
  } else if (event === "tool") {
    toolLine(payload.name, payload.result);
  } else if (event === "error") {
    reply.body.innerHTML = `<span style="color:var(--danger)">${esc(payload.message)}</span>`;
  } else if (event === "done") {
    reply.text = payload.text;
    reply.body.innerHTML = md(reply.text);
    $("#title").textContent = $("#title").textContent === "new chat"
      ? payload.text.slice(0, 60)
      : $("#title").textContent;
  }
}

/* ---------------------------------------------------------------- events */

$("#composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#input");
  const text = input.value.trim();
  if (!text || state.sending) return;
  input.value = "";
  input.style.height = "auto";
  await send(text);
});

$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("#composer").requestSubmit();
  }
  if (e.key === "Escape" && state.sending) {
    state.controller?.abort();
  }
});

$("#input").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, innerHeight * 0.4) + "px";
});

$("#new-chat").onclick = newChat;
$("#menu").onclick = () => $("#sidebar").classList.toggle("open");

$("#filter").oninput = (e) => {
  state.filter = e.target.value;
  renderSessions();
};

$("#mode").onchange = async (e) => {
  state.mode = e.target.value;
  $("#mode-chip").textContent = state.mode;
  if (state.current) {
    await api(`/api/sessions/${state.current}`, {
      method: "PATCH",
      body: JSON.stringify({ mode: state.mode }),
    });
    await refreshSessions();
  }
};

$("#model-pick").onchange = async (e) => {
  const model = e.target.value || "";
  if (!state.current) return;
  await api(`/api/sessions/${state.current}`, {
    method: "PATCH",
    body: JSON.stringify({ model }),
  });
  await refreshSessions();
};

/* ---------------------------------------------------------------- settings */

const dlg = $("#configure");

$("#settings").onclick = async () => {
  const info = await api("/api/models");
  renderModels(info);
  $("#cfg-url").value = info.base_url;
  $("#cfg-model").value = info.model;
  $("#cfg-key").value = "";
  $("#cfg-status").textContent = info.reachable
    ? `${info.models.length} model${info.models.length === 1 ? "" : "s"} found`
    : "not reachable — check the endpoint";
  dlg.showModal();
};

$("#cfg-cancel").onclick = () => dlg.close();

$("#cfg-pull-btn").onclick = async () => {
  const name = $("#cfg-pull").value.trim();
  if (!name) return;
  const status = $("#cfg-status");
  const button = $("#cfg-pull-btn");
  button.disabled = true;
  status.textContent = `pulling ${name}…`;

  try {
    const res = await fetch("/api/models/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: name }),
    });
    if (!res.ok || !res.body) throw new Error(`http ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const event = parseEvent(block);
        if (!event) continue;
        if (event.name === "pull") {
          const d = event.data;
          const pct = d.total ? ` ${Math.round((100 * d.completed) / d.total)}%` : "";
          status.textContent = `${d.status}${pct}`;
        } else if (event.name === "error") {
          status.textContent = event.data.message;
        } else if (event.name === "done") {
          status.textContent = `${event.data.model} installed`;
          renderModels({ ...event.data, base_url: $("#cfg-url").value });
          $("#cfg-model").value = event.data.model;
        }
      }
    }
  } catch (err) {
    status.textContent = err.message;
  } finally {
    button.disabled = false;
  }
};

$("#config-form").onsubmit = async (e) => {
  e.preventDefault();
  $("#cfg-status").textContent = "saving…";
  try {
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        base_url: $("#cfg-url").value.trim(),
        api_key: $("#cfg-key").value.trim(),
        model: $("#cfg-model").value.trim(),
      }),
    });
    await refreshModels();
    await refreshStats();
    dlg.close();
  } catch (err) {
    $("#cfg-status").textContent = err.message;
  }
};

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    newChat();
  }
});

/* ---------------------------------------------------------------- boot */

(async function boot() {
  startLifecycle();
  await refreshStats();
  await refreshModels();
  await refreshSessions();
  if (state.sessions.length) await openSession(state.sessions[0].id);
  else await newChat();
  if (location.hash === "#settings") $("#settings").click();
})();
