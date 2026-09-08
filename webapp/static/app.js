const $ = (id) => document.getElementById(id);
const logEl = $("log");
let busy = false;

// ── tabs ──────────────────────────────────────
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "resume") loadResume();
    if (btn.dataset.tab === "subs") searchSubs();
    if (btn.dataset.tab === "history") loadHistory();
  });
});

// ── logging ───────────────────────────────────
function addLog(message, level = "info") {
  const line = document.createElement("div");
  line.className = level;
  line.textContent = message;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

function setProgress(fraction, label) {
  $("progressBar").style.width = `${(fraction * 100).toFixed(1)}%`;
  $("progressLabel").textContent = label || (fraction ? `${(fraction * 100).toFixed(0)}%` : "Idle");
}

function setBusy(state) {
  busy = state;
  document.querySelectorAll(".btn").forEach((b) => {
    if (b.id !== "btnStop") b.disabled = state;
  });
  $("btnStop").classList.toggle("hidden", !state);
  $("btnStop").disabled = false;
}

$("btnStop").addEventListener("click", () => {
  $("btnStop").disabled = true;
  post("/api/stop", {});
});

// ── websocket ─────────────────────────────────
function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  let ping;
  ws.onopen = () => {
    ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
  };
  ws.onmessage = (ev) => {
    const e = JSON.parse(ev.data);
    if (e.kind === "log") addLog(e.message, e.level);
    else if (e.kind === "progress") setProgress(e.fraction, e.label);
    else if (e.kind === "item") addLog(`[${e.index}/${e.total}] ${e.title}`, "item");
    else if (e.kind === "state") setBusy(e.busy);
    else if (e.kind === "done") {
      setProgress(0, "Idle");
      const activeTab = document.querySelector(".tab.active").dataset.tab;
      if (activeTab === "subs") searchSubs();
      if (activeTab === "history") loadHistory();
    }
  };
  ws.onclose = () => {
    clearInterval(ping);
    setTimeout(connect, 1500);
  };
}
connect();

// ── api helper ────────────────────────────────
async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json();
  if (data.ok === false) addLog(data.error || "Request failed", "error");
  return data;
}

// ── status pills ──────────────────────────────
async function loadStatus() {
  const s = await (await fetch("/api/status")).json();
  $("statusPills").innerHTML = [
    ["FFmpeg", s.ffmpeg],
    ["Cookies", s.cookies],
    ["Gemini key", s.gemini],
  ]
    .map(([label, on]) => `<span class="pill ${on ? "on" : "off"}">${on ? "●" : "○"} ${label}</span>`)
    .join("");

  $("dlQuality").innerHTML = s.qualities
    .map((q) => `<option value="${q.key}" ${q.key === "2" ? "selected" : ""}>${q.label}</option>`)
    .join("");
  $("downloadDir").textContent = `Saving to ${s.download_dir}`;
  setBusy(s.busy);
}
loadStatus();

// ── download ──────────────────────────────────
$("btnSizes").addEventListener("click", async () => {
  const url = $("dlUrl").value.trim();
  if (!url) return addLog("Enter a URL first.", "warn");
  addLog("Estimating sizes…", "info");
  const { sizes } = await post("/api/sizes", { url });
  [...$("dlQuality").options].forEach((opt) => {
    const size = sizes[opt.value];
    opt.textContent = opt.textContent.split("  —  ")[0] + (size && size !== "?" ? `  —  ${size}` : "");
  });
  addLog("Sizes updated in the quality list.", "success");
});

$("dlPlaylist").addEventListener("change", async (e) => {
  const preview = $("playlistPreview");
  const url = $("dlUrl").value.trim();
  if (!e.target.checked || !url) return preview.classList.add("hidden");
  preview.classList.remove("hidden");
  preview.textContent = "Reading playlist…";
  const info = await post("/api/playlist-info", { url });
  preview.textContent = info.ok
    ? `📃 ${info.title} — ${info.count} videos`
    : "Could not read this playlist.";
});

$("btnDownload").addEventListener("click", async () => {
  const url = $("dlUrl").value.trim();
  if (!url) return addLog("Enter a URL first.", "warn");
  await post("/api/download", {
    url,
    quality: $("dlQuality").value,
    is_playlist: $("dlPlaylist").checked,
    with_transcript: $("dlTranscript").checked,
  });
});

// ── resume ────────────────────────────────────
async function loadResume() {
  const { playlists } = await (await fetch("/api/saved-progress")).json();
  const box = $("resumeList");
  if (!playlists.length) {
    box.innerHTML = `<p class="empty">No saved playlist progress yet.</p>`;
    return;
  }
  box.innerHTML = playlists
    .map(
      (p) => `
      <div class="card">
        <div class="card-main">
          <div class="card-title">${p.recent[p.recent.length - 1] || p.url}</div>
          <div class="card-sub">${p.done} done · ${p.quality_label} · ${p.url.slice(0, 60)}</div>
        </div>
        <button class="btn" data-resume="${encodeURIComponent(p.url)}">Resume</button>
      </div>`
    )
    .join("");
  box.querySelectorAll("[data-resume]").forEach((btn) =>
    btn.addEventListener("click", () =>
      post("/api/resume", { url: decodeURIComponent(btn.dataset.resume) })
    )
  );
}
$("btnRefreshResume").addEventListener("click", loadResume);

// ── transcript / tweet ────────────────────────
$("btnTranscript").addEventListener("click", () => {
  const url = $("exUrl").value.trim();
  if (!url) return addLog("Enter a URL first.", "warn");
  post("/api/transcript", { url });
});

$("btnTweet").addEventListener("click", () => {
  const url = $("exUrl").value.trim();
  if (!url) return addLog("Enter a URL first.", "warn");
  post("/api/tweet", { url });
});

// ── instagram ─────────────────────────────────
$("btnInstagram").addEventListener("click", () => {
  const urls = $("igUrls").value.split("\n").map((u) => u.trim()).filter(Boolean);
  if (!urls.length) return addLog("Enter at least one reel URL.", "warn");
  post("/api/instagram", { urls });
});

// ── subtitles ─────────────────────────────────
async function searchSubs() {
  const q = encodeURIComponent($("subQuery").value.trim());
  const { videos } = await (await fetch(`/api/videos?q=${q}`)).json();
  const box = $("subsList");
  if (!videos.length) {
    box.innerHTML = `<p class="empty">No downloaded videos matched.</p>`;
    return;
  }
  box.innerHTML = videos
    .map(
      (v, i) => `
      <div class="card">
        <div class="card-main">
          <div class="card-title">${v.title || v.video_id}</div>
          <div class="card-sub">${v.folder.split(/[\\/]/).pop()}</div>
        </div>
        <div class="row" style="margin:0;gap:10px;align-items:center">
          <span class="badge ${v.has_arabic ? "ok" : "missing"}">${v.has_arabic ? "has Arabic" : "missing"}</span>
          <button class="btn" data-sub="${i}">Fetch</button>
        </div>
      </div>`
    )
    .join("");
  box.querySelectorAll("[data-sub]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const v = videos[+btn.dataset.sub];
      post("/api/fetch-subtitle", { video_id: v.video_id, folder: v.folder });
    })
  );
}
$("btnSearchSubs").addEventListener("click", searchSubs);
$("subQuery").addEventListener("keydown", (e) => e.key === "Enter" && searchSubs());

// ── history ───────────────────────────────────
const KIND_LABEL = {
  video: "Video", playlist: "Playlist", transcript: "Transcript",
  tweet: "X thread", instagram: "Instagram", subtitle: "Subtitle",
};
const STATUS_DOT = { success: "●", failed: "●", cancelled: "◐" };

async function loadHistory() {
  const { entries } = await (await fetch("/api/history")).json();
  const box = $("historyList");
  if (!entries.length) {
    box.innerHTML = `<p class="empty">Nothing downloaded yet.</p>`;
    return;
  }
  box.innerHTML = entries
    .map((e) => {
      const when = new Date(e.time).toLocaleString(undefined, {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
      });
      return `
      <div class="card">
        <div class="card-main">
          <div class="card-title">
            <span class="kind-tag">${KIND_LABEL[e.kind] || e.kind}</span>
            &nbsp;${e.title || "(untitled)"}
          </div>
          <div class="card-sub">${when}${e.detail ? " · " + e.detail : ""}</div>
        </div>
        <span class="status-dot ${e.status}" title="${e.status}">${STATUS_DOT[e.status] || "●"}</span>
      </div>`;
    })
    .join("");
}
$("btnRefreshHistory").addEventListener("click", loadHistory);
