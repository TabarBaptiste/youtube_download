(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const el = {
    form: $("form"), url: $("url"), paste: $("paste"), submit: $("submit"), error: $("error"),
    preview: $("preview"), previewThumb: $("preview-thumb"), previewTitle: $("preview-title"),
    previewSub: $("preview-sub"),
    vformat: $("vformat"), quality: $("quality"), aformat: $("aformat"), bitrate: $("bitrate"),
    fieldVformat: $("field-vformat"), fieldQuality: $("field-quality"),
    fieldAformat: $("field-aformat"), fieldBitrate: $("field-bitrate"),
    thumb: $("thumb"), subs: $("subs"), wrapSubs: $("wrap-subs"), playlist: $("playlist"),
    jobsSection: $("jobs-section"), jobs: $("jobs"), clear: $("clear"), tpl: $("job-tpl"),
  };

  const STORAGE_KEY = "ytdl.jobs";
  const ACTIVE = new Set(["queued", "downloading", "processing"]);
  let mode = "video";
  let poller = null;
  let pollRate = 0;
  // Renseigné depuis /api/health : le serveur décide si les jobs sont partagés.
  let shareJobs = false;

  // ----------------------------------------------------------------- utils --

  const api = async (path, options = {}) => {
    const res = await fetch(path, {
      headers: options.body ? { "Content-Type": "application/json" } : undefined,
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || data.detail || `Erreur ${res.status}`);
    return data;
  };

  const showError = (msg) => {
    el.error.textContent = msg;
    el.error.classList.toggle("hidden", !msg);
  };

  const humanSize = (bytes) => {
    if (!bytes) return "";
    const units = ["o", "Ko", "Mo", "Go"];
    let v = bytes, i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
    return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
  };

  const humanDuration = (s) => {
    if (!s) return "";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
             : `${m}:${String(sec).padStart(2, "0")}`;
  };

  // Suivi local des jobs lancés par ce navigateur, utilisé hors mode partagé.
  const storedIds = () => {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || []; } catch { return []; }
  };
  const storeIds = (ids) => localStorage.setItem(STORAGE_KEY, JSON.stringify(ids.slice(0, 30)));
  const rememberId = (id) => storeIds([id, ...storedIds().filter((x) => x !== id)]);
  const forgetId = (id) => storeIds(storedIds().filter((x) => x !== id));

  // --------------------------------------------------------- mode & options --

  const applyMode = () => {
    const audio = mode === "audio";
    el.fieldVformat.classList.toggle("hidden", audio);
    el.fieldQuality.classList.toggle("hidden", audio);
    el.fieldAformat.classList.toggle("hidden", !audio);
    el.fieldBitrate.classList.toggle("hidden", !audio || el.aformat.value === "wav");
    el.wrapSubs.classList.toggle("hidden", audio);
  };

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      mode = tab.dataset.mode;
      applyMode();
    });
  });

  el.aformat.addEventListener("change", applyMode);

  el.paste.addEventListener("click", async () => {
    try {
      el.url.value = (await navigator.clipboard.readText()).trim();
      el.url.dispatchEvent(new Event("input"));
    } catch {
      el.url.focus();
    }
  });

  // ------------------------------------------------------------- aperçu URL --

  let infoTimer = null;
  let lastPreviewed = "";

  el.url.addEventListener("input", () => {
    clearTimeout(infoTimer);
    showError("");
    const url = el.url.value.trim();
    if (!/^https?:\/\/\S+$/.test(url)) {
      el.preview.classList.add("hidden");
      lastPreviewed = "";
      return;
    }
    if (url === lastPreviewed) return;
    infoTimer = setTimeout(() => loadPreview(url), 500);
  });

  async function loadPreview(url) {
    try {
      const info = await api("/api/info", { method: "POST", body: JSON.stringify({ url }) });
      if (el.url.value.trim() !== url) return;
      lastPreviewed = url;

      el.previewThumb.hidden = !info.thumbnail;
      if (info.thumbnail) el.previewThumb.src = info.thumbnail;
      el.previewTitle.textContent = info.title || "Sans titre";
      el.previewSub.textContent = [
        info.uploader,
        info.isPlaylist ? `${info.itemCount} vidéos` : humanDuration(info.duration),
      ].filter(Boolean).join(" · ");
      el.preview.classList.remove("hidden");

      if (info.isPlaylist) {
        el.playlist.checked = true;
      }
      syncQualityOptions(info.qualities);
    } catch (err) {
      el.preview.classList.add("hidden");
      showError(err.message);
    }
  }

  function syncQualityOptions(qualities) {
    if (!Array.isArray(qualities) || !qualities.length) return;
    const previous = el.quality.value;
    el.quality.innerHTML = '<option value="best">Maximale</option>';
    qualities.forEach((h) => {
      const opt = document.createElement("option");
      opt.value = h;
      opt.textContent = `${h}p${h === "2160" ? " (4K)" : h === "1440" ? " (2K)" : ""}`;
      el.quality.appendChild(opt);
    });
    el.quality.value = [...el.quality.options].some((o) => o.value === previous) ? previous : "best";
  }

  // ------------------------------------------------------------------ jobs --

  const renderJob = (job) => {
    let node = el.jobs.querySelector(`[data-id="${job.id}"]`);
    if (!node) {
      node = el.tpl.content.firstElementChild.cloneNode(true);
      node.dataset.id = job.id;
      node.querySelector(".job-close").addEventListener("click", () => removeJob(job.id));
      node.querySelector(".job-cancel").addEventListener("click", () => cancelJob(job.id));
      el.jobs.prepend(node);
    }

    node.dataset.status = job.status;
    const thumb = node.querySelector(".job-thumb");
    if (job.thumbnail) { thumb.src = job.thumbnail; thumb.hidden = false; }

    node.querySelector(".job-title").textContent = job.title || job.url;
    node.querySelector(".bar-fill").style.width = `${job.progress}%`;
    node.querySelector(".job-pct").textContent = `${Math.round(job.progress)} %`;

    const stage = node.querySelector(".job-stage");
    const rate = node.querySelector(".job-rate");
    const link = node.querySelector(".dl");
    const cancel = node.querySelector(".job-cancel");

    if (job.status === "error") {
      stage.textContent = job.error || "Échec";
      stage.style.color = "var(--err)";
    } else {
      stage.textContent = [job.stage, job.format?.toUpperCase()].filter(Boolean).join(" · ");
      stage.style.color = "";
    }

    rate.textContent = job.status === "done"
      ? humanSize(job.filesize)
      : [job.speed, job.eta && `${job.eta} restantes`].filter(Boolean).join(" · ");

    const done = job.status === "done";
    link.classList.toggle("hidden", !done);
    if (done) {
      link.href = job.downloadUrl;
      link.setAttribute("download", job.filename || "");
      link.textContent = job.filename?.endsWith(".zip") ? "Enregistrer le ZIP" : "Enregistrer";
    }
    cancel.classList.toggle("hidden", !ACTIVE.has(job.status));

    el.jobsSection.classList.remove("hidden");
  };

  async function removeJob(id) {
    forgetId(id);
    el.jobs.querySelector(`[data-id="${id}"]`)?.remove();
    if (!el.jobs.children.length) el.jobsSection.classList.add("hidden");
    try { await api(`/api/jobs/${id}`, { method: "DELETE" }); } catch { /* déjà nettoyé */ }
  }

  async function cancelJob(id) {
    try { await api(`/api/jobs/${id}/cancel`, { method: "POST" }); } catch (err) { showError(err.message); }
  }

  // Mode partagé : la liste vient du serveur, donc tous les appareils voient
  // les mêmes jobs, y compris ceux lancés ailleurs.
  async function pollShared() {
    let jobs;
    try { jobs = await api("/api/jobs"); } catch { return; }

    const seen = new Set(jobs.map((j) => j.id));
    el.jobs.querySelectorAll("[data-id]").forEach((node) => {
      if (!seen.has(node.dataset.id)) node.remove();
    });

    // Le serveur trie du plus récent au plus ancien ; renderJob empile en tête,
    // on parcourt donc à l'envers pour retrouver cet ordre à l'écran.
    [...jobs].reverse().forEach(renderJob);

    if (!el.jobs.children.length) el.jobsSection.classList.add("hidden");

    // Cadence rapide tant qu'un téléchargement tourne, lente sinon : il faut
    // continuer à interroger pour voir arriver les jobs des autres appareils.
    setRate(jobs.some((j) => ACTIVE.has(j.status)) ? 800 : 4000);
  }

  // Mode privé : on n'interroge que les jobs dont ce navigateur a gardé l'id.
  async function pollOwn() {
    const ids = storedIds();
    if (!ids.length) { stopPolling(); return; }

    const results = await Promise.all(ids.map(async (id) => {
      try { return await api(`/api/jobs/${id}`); }
      catch { forgetId(id); el.jobs.querySelector(`[data-id="${id}"]`)?.remove(); return null; }
    }));

    results.filter(Boolean).forEach(renderJob);
    if (!el.jobs.children.length) el.jobsSection.classList.add("hidden");

    // Rien en cours : inutile de continuer, aucun job ne peut surgir ailleurs.
    if (results.some((j) => j && ACTIVE.has(j.status))) setRate(800);
    else stopPolling();
  }

  const poll = () => (shareJobs ? pollShared() : pollOwn());

  const setRate = (ms) => {
    if (pollRate === ms && poller) return;
    pollRate = ms;
    if (poller) clearInterval(poller);
    poller = setInterval(poll, ms);
  };

  const stopPolling = () => {
    if (poller) clearInterval(poller);
    poller = null;
    pollRate = 0;
  };

  const startPolling = () => setRate(800);

  // ---------------------------------------------------------------- submit --

  el.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const url = el.url.value.trim();
    if (!url) return;

    const payload = mode === "audio"
      ? { url, format: el.aformat.value, audioBitrate: el.bitrate.value }
      : { url, format: el.vformat.value, quality: el.quality.value, embedSubs: el.subs.checked };

    payload.embedThumbnail = el.thumb.checked;
    payload.playlist = el.playlist.checked;

    el.submit.disabled = true;
    el.submit.textContent = "Lancement…";
    try {
      const job = await api("/api/download", { method: "POST", body: JSON.stringify(payload) });
      rememberId(job.id);
      renderJob(job);
      startPolling();
    } catch (err) {
      showError(err.message);
    } finally {
      el.submit.disabled = false;
      el.submit.textContent = "Télécharger";
    }
  });

  el.clear.addEventListener("click", async () => {
    // En mode partagé la vue fait référence, sinon on s'en tient à ses propres ids.
    const ids = shareJobs
      ? [...el.jobs.querySelectorAll("[data-id]")].map((n) => n.dataset.id)
      : storedIds();
    await Promise.all(ids.map(removeJob));
  });

  // Reprise de l'état après un rechargement de page.
  (async () => {
    applyMode();

    // Le mode de partage est décidé par le serveur ; en cas d'échec on reste sur
    // le comportement privé, qui n'expose jamais les jobs des autres.
    try { shareJobs = (await api("/api/health")).shareJobs === true; } catch { /* défaut */ }

    // poll() règle lui-même sa cadence, ou s'arrête s'il n'y a rien à suivre.
    await poll();

    const shared = new URLSearchParams(location.search).get("url");
    if (shared) { el.url.value = shared; el.url.dispatchEvent(new Event("input")); }
  })();

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
})();
