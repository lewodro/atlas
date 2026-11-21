/* Atlas UI — vanilla JS. No build step, no framework, no fake data. */

const $ = (s) => document.querySelector(s);
const icon = (id) => `<svg><use href="#i-${id}"/></svg>`;

const saved = (key, fallback) => {
  try { return localStorage.getItem(`atlas.${key}`) ?? fallback; } catch { return fallback; }
};
const rememberLocal = (key, value) => {
  try { localStorage.setItem(`atlas.${key}`, String(value)); } catch { /* private mode */ }
};

const state = {
  sessions: [],
  current: null,
  mode: "agent",
  modes: [],
  models: [],
  runtimes: [],
  defaultModel: "",
  baseUrl: "",
  modelChoice: "",
  profileId: "default",
  profileName: "Personal",
  sending: false,
  controller: null,
  filter: "",
  memories: [],
  categories: [],
  view: "chat",
  stats: null,
  theme: "atlas",
  accent: "",
  usageOpen: false,
  usagePos: "right",
  tools: [],
  skills: [],
  artifacts: [],
  workspace: null,
  toolActivity: [],
};

/* lifecycle lease (the server stops itself when the last tab closes) */
let lease = null;
function heartbeat() {
  fetch("/api/lifecycle", { method: "POST", keepalive: true }).catch(() => {});
}
function startLease() {
  if (lease) clearInterval(lease);
  heartbeat();
  lease = setInterval(heartbeat, 3000);
}
window.addEventListener("pagehide", () => {
  if (lease) { clearInterval(lease); lease = null; }
  navigator.sendBeacon("/api/lifecycle/close", new Blob(["{}"], { type: "application/json" }));
});
window.addEventListener("pageshow", (e) => { if (e.persisted) startLease(); });

/* ---------------------------------------------------------------- utils */

const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function md(text) {
  return esc(text).split(/```/).map((part, i) => {
    if (i % 2) return `<pre><code>${part.replace(/^[a-z]*\n/, "")}</code></pre>`;
    return part
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  }).join("");
}

function ago(iso) {
  const then = new Date(String(iso).replace(" ", "T") + "Z").getTime();
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.round(mins / 60)}h`;
  return `${Math.round(mins / 1440)}d`;
}

function friendlyModel(id) {
  if (!id) return "Default model";
  let name = id.split("/").pop().replace(/[-_:]/g, " ");
  name = name.replace(/(\d+(?:\.\d+)?)b\b/gi, "$1B");
  return name.replace(/\s+/g, " ").trim().replace(/\b\w/g, (c) => c.toUpperCase());
}

function friendlyMode(mode) {
  return { coach: "Coach", tutor: "Tutor", review: "Review", debug: "Debug", plan: "Plan" }[mode] || mode;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

/* ----------------------------------------------------- custom dropdown */

function makeSelect(root, config = {}) {
  const trigger = root.querySelector(".select-trigger");
  const valueEl = root.querySelector(".select-value");
  const menu = root.querySelector(".select-menu");
  let options = [];
  let value = config.value ?? "";

  function labelFor(v) {
    return options.find((o) => o.value === v)?.label || config.placeholder || "Select";
  }

  function paint() {
    menu.innerHTML = options.map((o, i) => `
      <button type="button" role="option" aria-selected="${o.value === value}"
              class="select-option ${o.value === value ? "selected" : ""}" data-i="${i}">
        <span class="tick">${icon("check")}</span>
        <span class="o-label">${esc(o.label)}</span>
        ${o.meta ? `<span class="o-meta">${esc(o.meta)}</span>` : ""}
      </button>`).join("");
    menu.querySelectorAll(".select-option").forEach((item) => {
      item.onclick = () => choose(options[Number(item.dataset.i)].value);
    });
  }

  function open() {
    paint();
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    (menu.querySelector(".selected") || menu.querySelector(".select-option"))?.focus();
  }
  function close() {
    menu.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  }
  function choose(next) {
    value = next;
    valueEl.textContent = labelFor(next);
    close();
    trigger.focus();
    paint();
    config.onChange?.(next);
  }

  trigger.onclick = () => (menu.hidden ? open() : close());
  trigger.onkeydown = (e) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault(); open();
    }
  };
  menu.onkeydown = (e) => {
    const items = [...menu.querySelectorAll(".select-option")];
    const at = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(at + 1) % items.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(at - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === "Escape") { e.preventDefault(); close(); trigger.focus(); }
  };
  document.addEventListener("click", (e) => {
    if (!root.contains(e.target)) close();
  });

  return {
    setOptions(list, keep = true) {
      options = list;
      if (!keep || !options.some((o) => o.value === value)) value = list[0]?.value ?? "";
      valueEl.textContent = labelFor(value);
      paint();
    },
    setValue(next) { value = next; valueEl.textContent = labelFor(next); paint(); },
    get value() { return value; },
    open,
    close,
  };
}

/* ---------------------------------------------------------- navigation */

const selects = {};

function setView(name) {
  state.view = name;
  $("#chat-view").hidden = name !== "chat";
  $("#workspace-view").hidden = name === "chat";
  document.body.dataset.view = name;

  document.querySelectorAll(".primary-nav .nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === name);
  });

  const titles = {
    tools: ["Tools", "Capabilities available to Atlas on this machine."],
    skills: ["Skills", "Instruction workflows Atlas loads only when needed."],
    artifacts: ["Artifacts", "Files and outputs Atlas creates or works on."],
    memory: ["Memory", "What Atlas remembers about you, in plain language."],
    usage: ["Usage", "What Atlas has actually done on this machine."],
  };
  if (titles[name]) {
    $("#workspace-title").textContent = titles[name][0];
    $("#workspace-subtitle").textContent = titles[name][1];
  }
  $("#memory-controls").hidden = name !== "memory";
  $("#workspace-actions").innerHTML = name === "memory"
    ? `<button class="text-btn" id="mem-export">${icon("download")} Export</button>` : "";
  if (name === "memory") $("#mem-export").onclick = exportMemories;

  if (name === "tools") renderTools();
  if (name === "skills") renderSkills();
  if (name === "artifacts") renderArtifacts();
  if (name === "memory") refreshMemories();
  if (name === "usage") renderUsage();
  $("#sidebar").classList.remove("open");
}

document.querySelectorAll(".primary-nav .nav-item").forEach((item) => {
  item.onclick = () => setView(item.dataset.view);
});
$("#composer-tools").onclick = () => setView("tools");
$("#settings").onclick = () => openSettings();
$("#header-settings").onclick = () => openSettings();
$("#menu").onclick = () => $("#sidebar").classList.toggle("open");
$("#collapse").onclick = () => {
  if (innerWidth <= 760) $("#sidebar").classList.toggle("open");
  else $("#app").classList.toggle("collapsed");
};

/* ---------------------------------------------------------------- chat */

function renderSessions() {
  const box = $("#sessions");
  const q = state.filter.toLowerCase();
  const list = state.sessions.filter((s) =>
    !q || s.title.toLowerCase().includes(q) || s.mode.includes(q));

  box.innerHTML = "";
  if (!list.length) {
    box.innerHTML = `<div class="empty-note">No chats${q ? " match your search" : " yet"}.</div>`;
    return;
  }
  for (const s of list) {
    const row = document.createElement("div");
    row.className = "chat-row" + (s.id === state.current ? " active" : "");
    row.innerHTML = `
      <span class="name">${esc(s.title)}</span>
      <span class="meta">${ago(s.updated)}</span>
      <button class="kill" title="Delete chat">${icon("close")}</button>`;
    row.onclick = () => { openSession(s.id); $("#sidebar").classList.remove("open"); };
    row.querySelector(".name").ondblclick = () => renameSession(s);
    row.querySelector(".kill").onclick = (e) => { e.stopPropagation(); removeSession(s); };
    box.appendChild(row);
  }
}

function welcome() {
  const name = state.profileName.split(" ")[0] || "there";
  return `<div class="welcome">
    <h2>Hello, ${esc(name)}</h2>
    <p>What are we working on?</p>
    <div class="suggestions">
      <button class="suggestion" data-prompt="Help me plan the next step on a project">${icon("folder")}Work on a project</button>
      <button class="suggestion" data-prompt="Quiz me on a topic I am studying">${icon("spark")}Study something</button>
      <button class="suggestion" data-prompt="Inspect the repository I have been working in">${icon("git")}Inspect a repository</button>
      <button class="suggestion" data-prompt="What do you remember about me?">${icon("memory")}Recall my memory</button>
    </div>
  </div>`;
}

function paintWelcome() {
  const box = $("#messages");
  if (box.querySelector(".msg")) return;
  box.innerHTML = welcome();
  box.querySelectorAll(".suggestion").forEach((card) => {
    card.onclick = () => {
      $("#input").value = card.dataset.prompt;
      $("#input").focus();
      $("#input").dispatchEvent(new Event("input"));
    };
  });
}

function bubble(role, text = "") {
  boxlessRemoveWelcome();
  const holder = document.createElement("article");
  holder.className = `msg ${role}`;
  holder.innerHTML = `<div class="who">${role === "user" ? "You" : "Atlas"}</div><div class="body"></div>`;
  holder.querySelector(".body").innerHTML = md(text);
  $("#messages").appendChild(holder);
  scrollDown();
  return { holder, body: holder.querySelector(".body"), text };
}
function boxlessRemoveWelcome() { $("#messages .welcome")?.remove(); }

const TOOL_LABELS = {
  remember: "Saved a memory",
  search_notes: "Searched memories",
  recent_activity: "Checked recent activity",
  forget_memory: "Forgot a memory",
  list_memories: "Listed memories",
  update_memory: "Updated a memory",
};

function toolLine(name, result) {
  const el = document.createElement("details");
  el.className = "tool-call";
  el.innerHTML = `
    <summary><span class="pulse"></span><span>${esc(TOOL_LABELS_EXTRA[name] || TOOL_LABELS[name] || `Used ${name}`)}</span>${icon("chevron")}</summary>
    <pre>${esc(result)}</pre>`;
  $("#messages").appendChild(el);
  scrollDown();
}

const CATEGORY_LABELS = {
  identity: "Identity", education: "Education", preferences: "Preferences",
  learning: "Learning", communication: "Communication", projects: "Projects",
  "last-seat": "Last Seat", atlas: "Atlas", tennis: "Tennis", goals: "Goals",
};

const TOOL_LABELS_EXTRA = {
  web_search: "Searched the web",
  web_fetch: "Fetched a page",
  filesystem: "Used the workspace",
  git_status: "Checked Git status",
  git_diff: "Read the diff",
  git_log: "Read commit history",
  terminal: "Ran a terminal command",
  file_manager: "Managed workspace files",
};
function memoryLine(payload) {
  const el = document.createElement("details");
  el.className = "memory-hint";
  const items = (payload.categories || []).map((c) =>
    `<li>${esc(CATEGORY_LABELS[c] || c)}</li>`).join("");
  el.innerHTML = `<summary>${icon("memory")} Used ${payload.count} ${payload.count === 1 ? "memory" : "memories"}</summary><ul>${items}</ul>`;
  $("#messages").appendChild(el);
  scrollDown();
}

function scrollDown() {
  const box = $("#messages");
  if (box.scrollHeight - box.scrollTop - box.clientHeight < 220 || state.sending) {
    box.scrollTop = box.scrollHeight;
  }
}

async function refreshSessions() {
  state.sessions = (await api("/api/sessions")).sessions;
  renderSessions();
  if (state.view === "usage") renderUsage();
  if (state.usageOpen) renderUsagePanel();
}

async function refreshStats() {
  const data = await api("/api/stats");
  state.stats = data;
  state.modes = data.modes || [];
  selects.mode?.setOptions(state.modes.map((m) => ({ value: m, label: friendlyMode(m) })));
  selects.mode?.setValue(state.mode);
  $("#activity-label").textContent = data.frontier ? "Frontier" : "Local";
  $("#runtime-label").textContent = data.where ? data.where.split(" @ ")[0] : "Local runtime";
  renderUsagePanel();
  if (state.view === "usage") renderUsage();
  return data;
}

async function refreshRuntimes() {
  try {
    state.runtimes = (await api("/api/runtimes")).runtimes || [];
  } catch { state.runtimes = []; }
  if (state.view === "tools") renderTools();
  renderModelOptions();
}

function renderModelOptions() {
  const options = [
    { value: "", label: `Default · ${friendlyModel(state.defaultModel)}`, meta: "profile default" },
    ...state.models.map((m) => {
      const runtime = state.runtimes.find((r) => r.models?.includes(m));
      return { value: m, label: friendlyModel(m), meta: runtime ? `${runtime.name} · local` : "openai compatible" };
    }),
  ];
  selects.model?.setOptions(options);
  selects.model?.setValue(state.modelChoice);
}

async function refreshModels() {
  const info = await api("/api/models");
  state.models = info.models || [];
  state.defaultModel = info.model || "";
  state.baseUrl = info.base_url || "";
  renderModelOptions();
  return info;
}

async function refreshProfiles() {
  const data = await api("/api/profiles");
  state.profiles = data.profiles;
  state.profileId = data.active;
  const active = data.profiles.find((p) => p.id === data.active);
  state.profileName = active?.name || "Personal";
  selects.profile?.setOptions(data.profiles.map((p) => ({
    value: p.id,
    label: p.name,
    meta: p.active ? "active" : `${p.memories} memories`,
  })));
  selects.profile?.setValue(data.active);
  $("#profile-avatar").textContent = (state.profileName[0] || "P").toUpperCase();
}

async function newChat() {
  const { id } = await api("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ mode: state.mode, model: state.modelChoice || undefined }),
  });
  await refreshSessions();
  await openSession(id);
}

async function openSession(id) {
  const { session, messages } = await api(`/api/sessions/${id}`);
  state.current = id;
  state.mode = session.mode;
  state.modelChoice = session.model || "";
  $("#title").textContent = session.title || "New chat";
  selects.mode?.setValue(state.mode);
  selects.model?.setValue(state.modelChoice);

  const box = $("#messages");
  box.innerHTML = "";
  if (messages.length) messages.forEach((m) => bubble(m.role, m.content));
  else paintWelcome();
  renderSessions();
  $("#input").focus();
}

async function renameSession(s) {
  const title = prompt("Rename chat", s.title);
  if (!title || title === s.title) return;
  await api(`/api/sessions/${s.id}`, { method: "PATCH", body: JSON.stringify({ title }) });
  await refreshSessions();
  if (s.id === state.current) $("#title").textContent = title;
}

async function removeSession(s) {
  if (!confirm(`Delete "${s.title}"? This cannot be undone.`)) return;
  try { await api(`/api/sessions/${s.id}`, { method: "DELETE" }); }
  catch (e) { alert(e.message); return; }
  await refreshSessions();
  await refreshStats();
  if (s.id === state.current) {
    state.current = null;
    if (state.sessions.length) await openSession(state.sessions[0].id);
    else await newChat();
  }
}

/* ------------------------------------------------------------- sending */

async function send(text) {
  if (state.sending) return;
  if (!state.current) await newChat();

  state.sending = true;
  $("#stop").hidden = false;
  $("#send").hidden = true;
  bubble("user", text);
  const reply = bubble("assistant", "");
  reply.body.classList.add("caret");

  state.controller = new AbortController();
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.current, message: text, mode: state.mode }),
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
    await refreshSessions();
    await refreshStats();
  }
}

function parseEvent(block) {
  let name = "message", data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return null;
  try { return { name, data: JSON.parse(data) }; } catch { return null; }
}

function skillLine(name) {
  const el = document.createElement("div");
  el.className = "tool";
  el.innerHTML = `${icon("spark")} <b>${esc(name)}</b> skill loaded`;
  $("#messages").appendChild(el);
  scrollDown();
}

function permissionLine(payload) {
  const el = document.createElement("div");
  el.className = "permission-card";
  el.innerHTML = `
    <div><b>${esc(payload.tool)}</b> wants permission</div>
    <code>${esc(payload.preview || "")}</code>
    <div class="permission-actions">
      <button type="button" data-allow="true">Allow</button>
      <button type="button" data-allow="false">Deny</button>
    </div>`;
  el.querySelectorAll("button").forEach((button) => {
    button.onclick = async () => {
      await api("/api/tools/permission", {
        method: "POST",
        body: JSON.stringify({ token: payload.token, allow: button.dataset.allow === "true" }),
      });
      el.remove();
    };
  });
  $("#messages").appendChild(el);
  scrollDown();
}

function handleEvent(block, reply) {
  const event = parseEvent(block);
  if (!event) return;
  const { name, data } = event;
  if (name === "delta") {
    reply.text += data.text;
    reply.body.innerHTML = md(reply.text);
    scrollDown();
  } else if (name === "tool") {
    toolLine(data.name, data.result);
  } else if (name === "memory") {
    memoryLine(data);
  } else if (name === "error") {
    reply.body.innerHTML = `<span style="color:var(--danger)">${esc(data.message)}</span>`;
  } else if (name === "skill") {
    skillLine(data.name);
  } else if (name === "artifact") {
    const card = document.createElement("div");
    card.innerHTML = artifactCard(data);
    const holder = card.firstElementChild;
    holder.onclick = () => { setView("artifacts"); renderArtifactPreview(data); };
    $("#messages").appendChild(holder);
    scrollDown();
  } else if (name === "permission") {
    permissionLine(data);
  } else if (name === "done") {
    reply.text = data.text;
    reply.body.innerHTML = md(data.text);
    if ($("#title").textContent === "New chat") $("#title").textContent = data.text.slice(0, 54);
  }
}

/* ------------------------------------------------------------- memory */

const GROUPS = {
  "About you": ["identity", "education"],
  "Preferences": ["preferences", "communication", "learning"],
  "Projects": ["projects", "last-seat", "atlas", "games-renderer", "audio"],
  "Goals": ["goals", "ambitions", "decisions"],
  "Environment": ["temporary", "health", "programming", "dev-interests", "tennis", "tennis-goals", "memory-rules"],
};

async function refreshMemories() {
  const filter = selects.memCategory?.value || "";
  const data = await api("/api/memories" + (filter ? `?category=${encodeURIComponent(filter)}` : ""));
  state.memories = data.memories;
  state.categories = data.categories;
  selects.memCategory?.setOptions([
    { value: "", label: "All categories" },
    ...data.categories.map((c) => ({ value: c, label: c })),
  ]);
  selects.memCategory?.setValue(filter);
  selects.memAddCategory?.setOptions(data.categories.map((c) => ({ value: c, label: c })));
  selects.memAddCategory?.setValue("temporary");
  renderMemoryGroups();
}

function renderMemoryGroups() {
  const q = ($("#mem-filter")?.value || "").toLowerCase();
  const items = state.memories.filter((m) => !q || m.content.toLowerCase().includes(q));
  const grouped = new Map();
  items.forEach((m) => {
    const section = Object.keys(GROUPS).find((key) => GROUPS[key].includes(m.category)) || "Other";
    if (!grouped.has(section)) grouped.set(section, []);
    grouped.get(section).push(m);
  });
  const host = $("#workspace-body");
  if (!items.length) {
    host.innerHTML = `<div class="empty-state">${icon("memory")}<strong>No memories here yet</strong><span>Tell Atlas something durable and it will appear here in plain language.</span></div>`;
    return;
  }
  host.innerHTML = `<div class="memory-groups">${[...grouped].map(([section, rows]) => `
    <section class="memory-group">
      <h3>${esc(section)}</h3>
      ${rows.map((m) => `<div class="memory-item">
        <span class="text">${esc(m.content)}</span>
        <time>${esc((m.updated || "").slice(0, 10))}</time>
        <button data-id="${m.id}" title="Forget">${icon("close")}</button>
      </div>`).join("")}
    </section>`).join("")}</div>`;

  host.querySelectorAll(".memory-item button").forEach((button) => {
    button.onclick = async () => {
      if (!confirm("Forget this memory?")) return;
      await api(`/api/memories/${button.dataset.id}`, { method: "DELETE" });
      await refreshMemories();
      await refreshStats();
    };
  });
}

async function exportMemories() {
  const data = await api("/api/memories/export");
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `atlas-memories-${state.profileId}.json`;
  link.click();
}

/* --------------------------------------------------------------- tools */

const FUTURE_TOOLS = [
  { icon: "terminal", name: "Terminal", desc: "Sandboxed shell. Not implemented." },
  { icon: "git", name: "GitHub", desc: "Remote issues and pull requests. Local Git is already available." },
  { icon: "image", name: "Image generation", desc: "Create and edit images locally. Not implemented." },
  { icon: "code", name: "Code execution", desc: "Run generated code in a sandbox. Not implemented." },
  { icon: "database", name: "Last Seat MCP", desc: "Project tool server. Not implemented." },
  { icon: "plug", name: "Other MCP servers", desc: "Register external providers. Not implemented." },
];

const CATEGORY_ICON = {
  web: "globe", filesystem: "folder", git: "git", terminal: "terminal",
  skills: "spark", memory: "memory", general: "plug",
};

async function refreshTools() {
  try {
    state.tools = (await api("/api/tools")).tools || [];
  } catch { state.tools = []; }
  try {
    state.workspace = await api("/api/workspace");
  } catch { state.workspace = null; }
  try {
    state.toolActivity = (await api("/api/tools/activity")).activity || [];
  } catch { state.toolActivity = []; }
  if (state.view === "tools") renderTools();
  if (state.view === "usage") renderUsage();
}

async function configureTool(name) {
  if (name === "filesystem") {
    const current = state.workspace?.root || "";
    const path = prompt("Workspace folder Atlas may read and edit", current);
    if (!path) return;
    try {
      await api("/api/tools/config", {
        method: "POST", body: JSON.stringify({ workspace: path }),
      });
      await refreshTools();
    } catch (err) { alert(err.message); }
    return;
  }
  openSettings().then(() => selectSettingsTab("tools"));
}

function toolCard(t) {
  const configurable = ["filesystem", "web_search", "web_fetch"].includes(t.id);
  return `<article class="card">
    <div class="card-head">${icon(CATEGORY_ICON[t.category] || "plug")}<h3>${esc(t.id)}</h3></div>
    <p>${esc(t.description)}</p>
    <span class="pill ${t.available ? "" : "quiet"}">${t.available ? "Available" : "Not configured"}</span>
    <span class="pill quiet">${esc(t.permission)}</span>
    <div class="card-foot"><button class="text-btn" data-configure="${esc(t.id)}" ${configurable ? "" : "disabled"}>
      ${configurable ? "Configure" : "In use"}</button></div>
  </article>`;
}

function renderTools() {
  $("#tools-badge").textContent = String(state.tools.filter((t) => t.available).length);
  const ws = state.workspace || {};
  $("#workspace-body").innerHTML = `
    <div class="group-label">Available on this machine</div>
    <div class="card-grid">${state.tools.map(toolCard).join("")}</div>
    <div class="group-label">Workspace</div>
    <div class="card">
      <div class="card-head">${icon("folder")}<h3>${esc(ws.repo || (ws.configured ? "Folder workspace" : "No workspace"))}</h3></div>
      <p>${esc(ws.root || ws.error || "Configure a workspace to enable filesystem and Git tools.")}</p>
      <span class="pill ${ws.is_git ? "" : "quiet"}">${ws.is_git
        ? `${esc(ws.branch || "detached")} · ${ws.dirty ? "dirty" : "clean"} · ${ws.changed} changed`
        : "not a Git repository"}</span>
    </div>
    <div class="group-label">Coming next — not implemented</div>
    <div class="card-grid">${FUTURE_TOOLS.map((t) => `
      <article class="card">
        <div class="card-head">${icon(t.icon)}<h3>${esc(t.name)}</h3></div>
        <p>${esc(t.desc)}</p><span class="pill quiet">Not configured</span>
      </article>`).join("")}</div>`;

  $("#workspace-body").querySelectorAll("[data-configure]").forEach((button) => {
    if (button.dataset.configure) button.onclick = () => configureTool(button.dataset.configure);
  });
}

/* -------------------------------------------------------------- skills */

async function refreshSkills() {
  try {
    state.skills = (await api("/api/skills")).skills || [];
  } catch { state.skills = []; }
  if (state.view === "skills") renderSkills();
}

function renderSkills() {
  $("#workspace-body").innerHTML = state.skills.length ? `
    <div class="card-grid">${state.skills.map((s) => `
      <article class="card">
        <div class="card-head">${icon("spark")}<h3>${esc(s.name)}</h3></div>
        <p>${esc(s.description)}</p>
        <div class="settings-list">${s.tags.map((tag) => `<span>${esc(tag)}</span>`).join("")}</div>
        <div class="card-foot"><button class="text-btn" data-skill="${esc(s.id)}">View instructions</button></div>
      </article>`).join("")}</div>` : `
    <div class="empty-state">${icon("spark")}<strong>No skills installed</strong><span>Add skills in skills/&lt;id&gt;/SKILL.md.</span></div>`;

  $("#workspace-body").querySelectorAll("[data-skill]").forEach((button) => {
    button.onclick = async () => {
      const data = await api(`/api/skills/${encodeURIComponent(button.dataset.skill)}`);
      const skill = data.skill;
      $("#workspace-body").innerHTML = `<article class="card">
        <div class="card-head">${icon("spark")}<h3>${esc(skill.name)}</h3></div>
        <p>${esc(skill.description)}</p>
        <div class="settings-list">${(skill.tools || []).map((t) => `<span class="on">${esc(t)}</span>`).join("")}</div>
        <pre class="skill-body">${esc(skill.body)}</pre>
        <div class="card-foot"><button class="text-btn" id="skill-back">Back</button></div>
      </article>`;
      $("#skill-back").onclick = renderSkills;
    };
  });
}

/* ----------------------------------------------------------- artifacts */

function artifactIcon(kind) {
  if (kind === "image") return "image";
  if (["code", "markdown", "text", "json", "patch"].includes(kind)) return "code";
  return "file";
}

function artifactCard(a) {
  return `<div class="artifact-card">${icon(artifactIcon(a.kind))}
    <span class="a-name">${esc(a.title || a.name)}</span>
    <span class="pill">${esc(a.kind || a.type)}</span>
    <button class="text-btn" data-artifact="${esc(a.id)}">Open</button></div>`;
}

async function refreshArtifacts() {
  try {
    state.artifacts = (await api("/api/artifacts")).artifacts || [];
  } catch { state.artifacts = []; }
  if (state.view === "artifacts") renderArtifacts();
}

function renderArtifactList(items) {
  $("#workspace-body").innerHTML = `<div class="artifact-list">${items.map((a) => `
    <div class="artifact-row" data-artifact="${esc(a.id)}">
      ${icon(artifactIcon(a.kind))}
      <span class="a-name">${esc(a.title)}</span>
      <span class="a-meta">${esc(a.kind)}</span>
      <span class="a-meta">${new Date(a.created * 1000).toLocaleDateString()}</span>
    </div>`).join("")}</div>`;
  $("#workspace-body").querySelectorAll("[data-artifact]").forEach((row) => {
    row.onclick = () => {
      const item = items.find((a) => a.id === row.dataset.artifact);
      if (item) renderArtifactPreview(item);
    };
  });
}

function renderArtifactPreview(a) {
  const media = a.kind === "image" && a.path
    ? `<img class="artifact-image" src="/api/artifacts/${encodeURIComponent(a.id)}/content" alt="${esc(a.title)}" />`
    : `<pre>${esc(a.preview || "(no text preview)")}</pre>`;
  $("#workspace-body").innerHTML = `<div class="artifact-preview">
    <div class="card-head">${icon(artifactIcon(a.kind))}<h3>${esc(a.title)}</h3></div>
    <p class="unavailable">${esc(a.kind)} · ${esc(a.path || "stored locally")}</p>
    ${media}
    <div class="card-foot"><button class="text-btn" id="artifact-back">Back</button></div>
  </div>`;
  $("#artifact-back").onclick = renderArtifacts;
}

function renderArtifacts() {
  if (!state.artifacts.length) {
    $("#workspace-body").innerHTML = `<div class="empty-state">${icon("artifacts")}
      <strong>No artifacts yet</strong>
      <span>Files Atlas creates or works on will appear here with a preview.</span>
    </div>`;
    return;
  }
  renderArtifactList(state.artifacts);
}

/* ------------------------------------------------------- theme + usage */

const THEMES = [
  { id: "atlas", label: "Atlas", note: "near-black · cyan" },
  { id: "midnight", label: "Midnight", note: "pitch black · deep blue" },
  { id: "mono", label: "Mono", note: "black · white/gray" },
  { id: "forest", label: "Forest", note: "black · muted green" },
];

const ACCENTS = [
  { label: "Cyan", value: "#22d3a6" },
  { label: "Blue", value: "#5b8cff" },
  { label: "Green", value: "#5fbf87" },
  { label: "White", value: "#e8e8e8" },
];

function paintThemeChoices() {
  $("#theme-choices").innerHTML = THEMES.map((t) => `
    <button type="button" class="theme-card ${t.id === state.theme ? "active" : ""}" data-theme="${t.id}">
      <span class="preview"></span><span><b>${esc(t.label)}</b><br><small>${esc(t.note)}</small></span>
    </button>`).join("");
  $("#theme-choices").querySelectorAll("button").forEach((button) => {
    button.onclick = () => applyTheme(button.dataset.theme, "");
  });

  $("#accent-choices").innerHTML = ACCENTS.map((a) => `
    <button type="button" class="accent-dot ${a.value === state.accent ? "active" : ""}"
            data-accent="${a.value}" style="--dot:${a.value}"><i></i>${esc(a.label)}</button>`).join("");
  $("#accent-choices").querySelectorAll("button").forEach((button) => {
    button.onclick = () => applyTheme(state.theme, button.dataset.accent);
  });
}

function applyTheme(id, accent = "") {
  state.theme = id;
  state.accent = accent;
  document.documentElement.dataset.theme = id;
  if (accent) document.documentElement.style.setProperty("--accent", accent);
  else document.documentElement.style.removeProperty("--accent");
  rememberLocal("theme", id);
  rememberLocal("accent", accent);
  selects.theme?.setValue(id);
  paintThemeChoices();
}

/* usage is derived only from real API data */
const BLOCKS = "▁▂▃▄▅▆▇█";
function sparkline(values) {
  const peak = Math.max(1, ...values);
  return values.map((v) => BLOCKS[Math.round((v / peak) * (BLOCKS.length - 1))]).join("");
}
function miniRow(label, count, peak) {
  const width = 11;
  const filled = Math.round((count / Math.max(1, peak)) * width);
  return `<div class="mini-row"><span class="label">${esc(label)}</span>
    <span class="track"><b>${"█".repeat(filled)}</b>${"░".repeat(width - filled)}</span>
    <span class="count">${count}</span></div>`;
}

async function usageFacts() {
  const stats = state.stats || await api("/api/stats");
  const sessions = state.sessions.length ? state.sessions : (await api("/api/sessions")).sessions;
  const memories = state.memories.length ? state.memories : (await api("/api/memories")).memories;
  return { stats, sessions, memories };
}

function usageSummary(facts) {
  const { stats, sessions, memories } = facts;
  return [
    ["Model", friendlyModel(stats.model || state.defaultModel)],
    ["Runtime", stats.where || "not detected"],
    ["Chats", String(sessions.length)],
    ["Turns", String(stats.turns ?? "—")],
    ["Memories", String(memories.length)],
  ];
}

function toolActivityRows() {
  const rows = state.toolActivity || [];
  if (!rows.length) return '<p class="unavailable">no tool calls recorded yet</p>';
  const counts = {};
  let failed = 0;
  rows.forEach((r) => {
    counts[r.tool] = (counts[r.tool] || 0) + 1;
    if (!r.ok) failed += 1;
  });
  const peak = Math.max(1, ...Object.values(counts));
  return Object.entries(counts).sort((a, b) => b[1] - a[1])
    .map(([name, n]) => miniRow(name, n, peak)).join("")
    + `<p class="unavailable">${rows.length} calls · ${failed} failed · durations recorded</p>`;
}

async function renderUsage() {
  const facts = await usageFacts();
  const { sessions, memories } = facts;

  const days = Array(7).fill(0);
  sessions.forEach((row) => {
    const then = new Date(String(row.updated).replace(" ", "T") + "Z").getTime();
    const index = 6 - Math.floor((Date.now() - then) / 86400000);
    if (index >= 0 && index < 7) days[index] += 1;
  });

  const byModel = {};
  sessions.forEach((row) => {
    const key = row.model || state.defaultModel || "default";
    byModel[key] = (byModel[key] || 0) + 1;
  });
  const byCategory = {};
  memories.forEach((row) => {
    byCategory[row.category] = (byCategory[row.category] || 0) + 1;
  });

  const modelPeak = Math.max(1, ...Object.values(byModel));
  const catPeak = Math.max(1, ...Object.values(byCategory));

  $("#workspace-body").innerHTML = `
    <div class="usage-grid">
      <section class="usage-card">
        <h3>At a glance</h3>
        ${usageSummary(facts).map(([k, v]) => `<div class="up-row"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join("")}
      </section>
      <section class="usage-card">
        <h3>Chats by day</h3>
        <div class="spark">${sparkline(days)}</div>
        <p class="unavailable">last 7 days · by chat, not tokens</p>
        <h3 style="margin-top:18px">Model usage</h3>
        ${Object.entries(byModel).sort((a, b) => b[1] - a[1]).slice(0, 6)
          .map(([m, n]) => miniRow(friendlyModel(m), n, modelPeak)).join("") || '<p class="unavailable">no chats yet</p>'}
      </section>
      <section class="usage-card">
        <h3>Memory categories</h3>
        ${Object.entries(byCategory).sort((a, b) => b[1] - a[1]).slice(0, 7)
          .map(([c, n]) => miniRow(c, n, catPeak)).join("") || '<p class="unavailable">no memories yet</p>'}
      </section>
      <section class="usage-card">
        <h3>Tool activity</h3>
        ${toolActivityRows(facts)}
        <h3 style="margin-top:18px">Not instrumented</h3>
        <p class="unavailable">Tokens, tokens/s, prompt tokens, session duration, tool calls and generated artifacts are not exposed by the current runtime. No numbers are guessed.</p>
      </section>
    </div>`;
}

function renderUsagePanel() {
  const panel = $("#usage-panel");
  if (!state.stats || !panel) return;
  panel.className = `usage-panel ${state.usagePos}`;
  panel.hidden = !state.usageOpen;
  const rows = usageSummary({
    stats: state.stats,
    sessions: state.sessions,
    memories: state.memories,
  });
  $("#usage-panel-body").innerHTML = rows.map(([k, v], i) => `
    <div class="up-row"><span>${esc(k)}</span><span class="${i === 0 ? "accent" : ""}">${esc(v)}</span></div>`).join("");
}

function toggleUsagePanel(force) {
  state.usageOpen = force ?? !state.usageOpen;
  rememberLocal("usageOpen", state.usageOpen);
  renderUsagePanel();
  if (state.usageOpen) refreshMemories().then(renderUsagePanel).catch(() => {});
}

function cycleUsageDock() {
  const order = ["right", "bottom-right", "docked"];
  state.usagePos = order[(order.indexOf(state.usagePos) + 1) % order.length];
  rememberLocal("usagePos", state.usagePos);
  renderUsagePanel();
}

/* ------------------------------------------------------------- settings */

const dlg = $("#configure");
let runtimeCache = { at: 0, list: [] };

function fsAvailable() {
  return state.tools.find((t) => t.name === "filesystem")?.available || false;
}
function fsNote() {
  const fs = state.tools.find((t) => t.name === "filesystem");
  return fs?.workspace || fs?.error || "no workspace configured";
}

function selectSettingsTab(name) {
  document.querySelectorAll(".settings-tabs button").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".settings-panel").forEach((p) =>
    p.hidden = p.dataset.panel !== name);
  $("#cfg-save").hidden = name !== "models";
}

document.querySelectorAll(".settings-tabs button").forEach((button) => {
  button.onclick = () => {
    selectSettingsTab(button.dataset.tab);
    if (button.dataset.tab === "tools") {
      $("#settings-tools").innerHTML = state.tools.map((row) =>
        `<span class="${row.available ? "on" : ""}">${esc(row.id)} · ${esc(row.permission)}</span>`
      ).join("");
    }
  };
});

$("#settings-open-memory").onclick = () => { dlg.close(); setView("memory"); };
$("#usage-toggle").onclick = () => toggleUsagePanel();
$("#usage-close").onclick = () => toggleUsagePanel(false);
$("#usage-dock").onclick = cycleUsageDock;

async function renderRuntimes() {
  if (Date.now() - runtimeCache.at > 30000 || !runtimeCache.list.length) {
    runtimeCache = { at: Date.now(), list: (await api("/api/runtimes")).runtimes };
    state.runtimes = runtimeCache.list;
  }
  $("#cfg-runtimes").innerHTML = runtimeCache.list.map((r, i) => `
    <button type="button" class="runtime ${r.ok ? "" : "off"} ${r.active ? "active" : ""}" data-runtime="${i}">
      <b>${esc(r.name)}</b><small>${r.ok ? `${r.models.length} models` : "offline"}</small>
    </button>`).join("");
  $("#cfg-runtimes").querySelectorAll("button").forEach((button) => {
    button.onclick = async () => {
      const r = runtimeCache.list[Number(button.dataset.runtime)];
      const status = $("#cfg-status");
      status.textContent = `Connecting to ${r.name}…`;
      try {
        const info = await api(`/api/models?base_url=${encodeURIComponent(r.base_url)}`);
        $("#cfg-url").value = r.base_url;
        $("#cfg-key").value = "";
        $("#cfg-model").value = info.models[0] || "";
        status.textContent = r.ok
          ? `${r.name}: ${info.models.length} models available — save to connect`
          : `${r.name} is not running on ${r.base_url}`;
      } catch (err) { status.textContent = err.message; }
    };
  });
}

async function openSettings() {
  selectSettingsTab("appearance");
  const info = await api("/api/models");
  $("#cfg-url").value = info.base_url || "";
  $("#cfg-model").value = info.model || "";
  $("#cfg-key").value = "";
  $("#cfg-status").textContent = info.reachable
    ? `${info.models.length} models found` : "No local model server detected";
  await renderRuntimes();
  dlg.showModal();
}

$("#cfg-cancel").onclick = () => dlg.close();
$("#cfg-dismiss").onclick = () => dlg.close();

$("#cfg-pull-btn").onclick = async () => {
  const name = $("#cfg-pull").value.trim();
  if (!name) return;
  const status = $("#cfg-status"), button = $("#cfg-pull-btn");
  button.disabled = true;
  status.textContent = `Pulling ${name}…`;
  try {
    const res = await fetch("/api/models/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: name }),
    });
    if (!res.ok || !res.body) throw new Error(`http ${res.status}`);
    const reader = res.body.getReader(), decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const event = parseEvent(buffer.slice(0, cut));
        buffer = buffer.slice(cut + 2);
        if (!event) continue;
        if (event.name === "pull") {
          const d = event.data;
          status.textContent = `${d.status}${d.total ? ` ${Math.round(100 * d.completed / d.total)}%` : ""}`;
        } else if (event.name === "error") status.textContent = event.data.message;
        else if (event.name === "done") {
          status.textContent = `${event.data.model} installed`;
          $("#cfg-model").value = event.data.model;
          await refreshModels();
          runtimeCache.at = 0;
        }
      }
    }
  } catch (err) { status.textContent = err.message; }
  finally { button.disabled = false; }
};

$("#config-form").onsubmit = async (e) => {
  e.preventDefault();
  $("#cfg-status").textContent = "Saving…";
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
    runtimeCache.at = 0;
    await refreshRuntimes();
    dlg.close();
  } catch (err) { $("#cfg-status").textContent = err.message; }
};

/* --------------------------------------------------------------- events */

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
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); }
  if (e.key === "Escape" && state.sending) state.controller?.abort();
});
$("#input").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, innerHeight * 0.4) + "px";
});
$("#stop").onclick = () => state.controller?.abort();
$("#new-chat").onclick = () => { setView("chat"); newChat(); };
$("#filter").oninput = (e) => { state.filter = e.target.value; renderSessions(); };

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault(); setView("chat"); newChat();
  }
});

/* ----------------------------------------------------------------- boot */

(async function boot() {
  startLease();

  selects.theme = makeSelect($("#theme-select"), {
    placeholder: "Atlas",
    onChange: (id) => applyTheme(id, ""),
  });
  selects.theme.setOptions(THEMES.map((t) => ({ value: t.id, label: t.label })));
  state.usagePos = saved("usagePos", "right");
  state.usageOpen = saved("usageOpen", "false") === "true";
  const savedTheme = saved("theme", "atlas");
  applyTheme(THEMES.some((t) => t.id === savedTheme) ? savedTheme : "atlas", saved("accent", ""));

  selects.mode = makeSelect($("#mode-select"), {
    placeholder: "Coach",
    onChange: async (mode) => {
      state.mode = mode;
      if (!state.current) return;
      await api(`/api/sessions/${state.current}`, {
        method: "PATCH", body: JSON.stringify({ mode }),
      });
      await refreshSessions();
    },
  });

  selects.model = makeSelect($("#model-select"), {
    placeholder: "Model",
    onChange: async (model) => {
      state.modelChoice = model;
      if (!state.current) return;
      await api(`/api/sessions/${state.current}`, {
        method: "PATCH", body: JSON.stringify({ model }),
      });
      await refreshSessions();
    },
  });

  selects.profile = makeSelect($("#profile-select"), {
    placeholder: "Personal",
    onChange: async (id) => {
      await api("/api/profiles", {
        method: "POST", body: JSON.stringify({ action: "switch", id }),
      });
      location.reload();
    },
  });

  selects.memCategory = makeSelect($("#mem-filter-select"), {
    onChange: () => refreshMemories(),
  });
  selects.memAddCategory = makeSelect($("#mem-add-select"), {});

  $("#mem-filter").oninput = () => renderMemoryGroups();
  $("#mem-add-btn").onclick = async () => {
    const text = $("#mem-add-text").value.trim();
    if (!text) return;
    try {
      await api("/api/memories", {
        method: "POST",
        body: JSON.stringify({
          category: selects.memAddCategory.value || "temporary",
          content: text,
          confidence: 0.8,
        }),
      });
      $("#mem-add-text").value = "";
      await refreshMemories();
      await refreshStats();
    } catch (err) { alert(err.message); }
  };

  await refreshStats();
  await refreshProfiles();
  await refreshModels();
  refreshRuntimes().catch(() => {});
  refreshTools().catch(() => {});
  refreshSkills().catch(() => {});
  refreshArtifacts().catch(() => {});
  await refreshSessions();
  if (state.sessions.length) await openSession(state.sessions[0].id);
  else await newChat();

  if (state.usageOpen) refreshMemories().then(renderUsagePanel).catch(() => {});
  if (location.hash === "#new") newChat();
  const testMenu = new URLSearchParams(location.search).get("menu");
  if (testMenu === "model" || location.hash === "#model-menu") selects.model.open();
  if (testMenu === "mode" || location.hash === "#mode-menu") selects.mode.open();
  if (testMenu === "profile" || location.hash === "#profile-menu") selects.profile.open();
  if (location.hash === "#settings") openSettings();
  if (location.hash === "#tools") setView("tools");
  if (location.hash === "#artifacts") setView("artifacts");
  if (location.hash === "#usage") setView("usage");
  if (location.hash === "#memory") setView("memory");
})();
