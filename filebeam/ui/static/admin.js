// Admin page: poll tunnel status, surface live URL + change warnings,
// wire up copy buttons, tunnel controls, and drag-drop uploads.
(function () {
  const $ = (id) => document.getElementById(id);
  const urlEl = $("public-url");
  const stateEl = $("url-state");
  const copyBtn = $("copy-url");
  const warnEl = $("url-warning");
  let lastUrl = null;

  function currentPublicUrl() {
    return urlEl.dataset.url || null;
  }

  async function poll() {
    try {
      const r = await fetch("/status");
      const s = await r.json();
      stateEl.textContent = "Tunnel: " + s.state + (s.backend ? " (" + s.backend + ")" : "");
      stateEl.className = "state " + (s.state === "RUNNING" ? "running" : (s.state === "ERROR" ? "error" : ""));

      if (s.public_url) {
        urlEl.textContent = s.public_url;
        urlEl.dataset.url = s.public_url;
        copyBtn.disabled = false;
        // Warn on a change *after* we already had a URL this session.
        if (lastUrl && lastUrl !== s.public_url) {
          warnEl.hidden = false;
        }
        lastUrl = s.public_url;
      } else {
        urlEl.textContent = s.error ? ("error: " + s.error) : "—";
        copyBtn.disabled = true;
      }
      // Server also tracks a change (e.g. reconnect we missed).
      if (s.previous_url) warnEl.hidden = false;
    } catch (e) { /* admin server momentarily busy */ }
  }

  copyBtn?.addEventListener("click", () => copy(currentPublicUrl(), copyBtn));
  $("ack-url")?.addEventListener("click", async () => {
    warnEl.hidden = true;
    await fetch("/url/ack", { method: "POST" });
  });

  // Tunnel controls
  $("start-tunnel")?.addEventListener("click", async () => {
    const backend = $("backend-select").value;
    stateEl.textContent = "Starting…";
    const fd = new FormData(); fd.append("backend", backend);
    const r = await fetch("/tunnel/start", { method: "POST", body: fd });
    const j = await r.json();
    if (!j.ok) stateEl.textContent = "Error: " + j.error;
    poll();
  });
  $("stop-tunnel")?.addEventListener("click", async () => {
    await fetch("/tunnel/stop", { method: "POST" });
    lastUrl = null; warnEl.hidden = true; poll();
  });

  // Backend description helper
  const descEl = $("backend-desc");
  const sel = $("backend-select");
  function showDesc() {
    const b = (window.BACKENDS || []).find((x) => x.name === sel.value);
    descEl.textContent = b ? b.description : "";
  }
  sel?.addEventListener("change", showDesc); showDesc();

  // Copy share links: token appended to the live public URL.
  document.querySelectorAll(".copy-link").forEach((btn) => {
    btn.addEventListener("click", () => {
      const base = currentPublicUrl();
      if (!base) { alert("Start sharing first to get a public URL."); return; }
      copy(base.replace(/\/$/, "") + "/l/" + btn.dataset.token, btn);
    });
  });

  function copy(text, btn) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      const old = btn.textContent; btn.textContent = "✓ copied";
      setTimeout(() => (btn.textContent = old), 1200);
    });
  }

  // Drag-drop uploads per folder
  document.querySelectorAll(".dropzone").forEach((dz) => {
    const fid = dz.dataset.folder;
    const input = document.querySelector('.file-input[data-folder="' + fid + '"]');
    dz.addEventListener("click", () => input.click());
    input.addEventListener("change", () => uploadFiles(fid, input.files, dz));
    ["dragover", "dragenter"].forEach((ev) =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("hover"); }));
    ["dragleave", "drop"].forEach((ev) =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("hover"); }));
    dz.addEventListener("drop", (e) => uploadFiles(fid, e.dataTransfer.files, dz));
  });

  async function uploadFiles(folderId, files, dz) {
    const label = dz.textContent;
    for (const file of files) {
      dz.textContent = "↑ " + file.name;
      const fd = new FormData(); fd.append("file", file);
      await fetch("/folders/" + folderId + "/upload", { method: "POST", body: fd });
    }
    dz.textContent = "✓ done"; setTimeout(() => (dz.textContent = label), 1500);
  }

  poll();
  setInterval(poll, 3000);
})();
