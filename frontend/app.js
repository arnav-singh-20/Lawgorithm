/* ════════════════════════════════════════════════════════════════
   Lawgorithm frontend
   - upload (file / camera / sample) -> background job -> live progress
   - results: summary, verdict, risk filters, clause cards, document view
   - AI text translated on demand via /translate (with meaning check)
   - reviewer desk
   Every piece of model output is inserted as text, never as HTML.
   ════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  // Served by the FastAPI app itself; only fall back to localhost when the
  // file is opened straight from disk.
  const API = location.protocol === "file:" ? "http://localhost:8000" : "";
  const POLL_MS = 1500;
  const t = (k, v) => window.i18n.t(k, v);
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const state = {
    docType: "rental",
    file: null,
    pollTimer: null,
    doc: null,          // finished analysis (results view)
    filter: "all",
    layout: "cards",
    reviewItems: [],
    translateRun: 0,
    // what the server says about data handling (GET /config); safe defaults until loaded
    config: { ai_service: null, store_analyses: false, review_enabled: false, retention_minutes: 60, privacy_contact: null, dpdp_act_url: null },
  };

  /* ── tiny DOM builder (text-only children => XSS-safe) ───────── */
  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "text") el.textContent = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  // "{key}.one" is an optional singular form; languages without one use "{key}".
  function plural(key, n) {
    const hasOne = (window.STRINGS[window.i18n.lang] || {})[`${key}.one`];
    return t(n === 1 && hasOne ? `${key}.one` : key, { n });
  }

  /* ── API ─────────────────────────────────────────────────────── */
  async function api(path, options = {}) {
    let res;
    try {
      res = await fetch(API + path, options);
    } catch {
      throw new Error(t("err.network"));
    }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof body.detail === "string" ? body.detail : null;
      const err = new Error(detail || t("err.generic"));
      err.status = res.status;
      throw err;
    }
    return body;
  }

  /* ── toast ───────────────────────────────────────────────────── */
  let toastTimer;
  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 3800);
  }

  /* ════════════ theme ════════════ */
  function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem("lawgorithm.theme"); } catch { /* ignore */ }
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const fromUrl = new URLSearchParams(location.search).get("theme");
    setTheme(["light", "dark"].includes(fromUrl) ? fromUrl : saved || (prefersDark ? "dark" : "light"));
    $("#themeToggle").addEventListener("click", () => {
      const root = document.documentElement;
      root.classList.add("theme-anim");
      setTheme(root.dataset.theme === "dark" ? "light" : "dark", true);
      setTimeout(() => root.classList.remove("theme-anim"), 450);
    });
  }
  function setTheme(theme, persist) {
    document.documentElement.dataset.theme = theme;
    $('meta[name="theme-color"]').setAttribute("content", theme === "dark" ? "#0c0c10" : "#fff9f1");
    $("#themeToggle").setAttribute("aria-pressed", String(theme === "dark"));
    if (persist) { try { localStorage.setItem("lawgorithm.theme", theme); } catch { /* ignore */ } }
  }

  /* ════════════ language ════════════ */
  function initLanguage() {
    const grid = $("#langGrid");
    window.LANGUAGES.forEach(lang => {
      grid.append(h("button", {
        class: "lang-tile", lang: lang.code, dataset: { lang: lang.code },
        onclick: () => { window.i18n.setLang(lang.code); $("#langDialog").close(); },
      }, h("span", { class: "lang-native", text: lang.native }), h("span", { class: "lang-english", text: lang.english })));
    });
    $("#langButton").addEventListener("click", openLanguagePicker);

    document.addEventListener("langchange", () => {
      const meta = window.i18n.meta;
      $("#langButtonLabel").textContent = meta.native;
      $$(".lang-tile").forEach(b => b.classList.toggle("is-active", b.dataset.lang === meta.code));
      rerenderCurrentView();
    });

    // ?lang=hi in a shared link wins; otherwise the saved choice; on the
    // very first visit, ask once.
    const fromUrl = new URLSearchParams(location.search).get("lang");
    const saved = window.i18n.saved();
    const chosen = window.STRINGS[fromUrl] ? fromUrl : saved;
    window.i18n.setLang(chosen || "en");
    if (!chosen) openLanguagePicker();
  }
  function openLanguagePicker() {
    const dlg = $("#langDialog");
    if (!dlg.open) dlg.showModal();
    ($(".lang-tile.is-active", dlg) || $(".lang-tile", dlg)).focus();
  }

  /* ════════════ views + routing ════════════ */
  function showView(name) {
    $$(".view").forEach(v => { v.hidden = v.dataset.view !== name; });
    $$(".nav-link[data-view-link]").forEach(b => {
      b.classList.toggle("is-active", b.dataset.viewLink === name || (name !== "review" && b.dataset.viewLink === "home"));
    });
    window.scrollTo(0, 0);
  }

  function route() {
    stopPolling();
    const [, kind, id] = (location.hash || "").match(/^#\/(\w+)\/?([\w-]*)/) || [];
    if (kind === "job" && id) return resumeJob(id);
    if (kind === "document" && id) return openDocument(id);
    if (kind === "expert" && id) return openTicket(id);
    if (kind === "review" && state.config.expert_review_enabled) {
      const invite = (location.hash.match(/[?&]invite=([\w-]+)/) || [])[1];
      if (invite) {
        try { localStorage.setItem(KEY_STORE, invite); } catch { /* private mode: the link still works this once */ state.inviteKey = invite; }
        history.replaceState(null, "", "#/review");      // the key never stays visible in the address bar
      }
      showView("review");
      return loadExpertDesk();
    }
    if (kind === "review" && state.config.review_enabled) { showView("review"); return loadReview(); }
    if (kind === "privacy") { showView("privacy"); return renderPrivacy(); }
    if (["pricing", "terms", "refunds", "contact"].includes(kind)) { showView("info"); return renderInfo(kind); }
    showView("home");
  }

  function go(hash) {
    if (location.hash === hash) route(); else location.hash = hash;
  }

  function rerenderCurrentView() {
    applyConfigText();
    if (!$("#view-results").hidden && state.doc) renderResults(state.doc);
    else if (!$("#view-expert").hidden && state.ticket) renderTicket(state.ticket);
    else if (!$("#view-review").hidden && state.config.expert_review_enabled) renderExpertDesk();
    else if (!$("#view-review").hidden) renderReview();
    else if (!$("#view-privacy").hidden) renderPrivacy();
    else if (!$("#view-info").hidden && state.infoPage) renderInfo(state.infoPage);
    updatePayLabel();
  }

  /* ════════════ privacy / config ════════════ */
  async function loadConfig() {
    try {
      state.config = { ...state.config, ...(await api("/config")) };
    } catch { /* keep the conservative defaults */ }
    updateReviewNav();
    $("#footerPricing").hidden = $("#footerRefunds").hidden = !state.config.payments_enabled;
    updatePayLabel();
    applyConfigText();
  }

  // Text whose truth depends on where the data actually goes.
  function applyConfigText() {
    const c = state.config;
    $(".progress-note").textContent = c.ai_service
      ? t("progress.noteSafe", { minutes: c.retention_minutes })
      : t("progress.note");
  }

  function renderPrivacy() {
    const c = state.config;
    const vars = {
      service: c.ai_service || "",
      minutes: c.retention_minutes,
      contact: c.privacy_contact || t("privacy.noContact"),
      keep: c.expert_review_keep_days,
      max: c.expert_review_max_days,
    };
    // p9 (expert review) only when it actually exists on this server
    const items = [1, 2, 3, 4, 5, 9, 6, 7, 8].filter(n => n !== 9 || c.expert_review_enabled).map(n => {
      const key = n === 9 && c.reviewer_kind !== "legal" ? "privacy.p9.d.team" : `privacy.p${n}.d`;
      const body = n === 3 && !c.ai_service ? t("privacy.p3.local") : t(key, vars);
      const link = n === 7 && c.dpdp_act_url
        ? h("p", {}, h("a", { href: c.dpdp_act_url, target: "_blank", rel: "noopener noreferrer", text: `${t("privacy.p7.link")} ↗` }))
        : null;
      return h("li", {}, h("strong", { text: t(`privacy.p${n}.t`) }), h("p", { text: body }), link);
    });
    $("#privacyList").replaceChildren(...items);
  }

  /* ════════════ upload ════════════ */
  // The sample contracts live in frontend/samples/ -- the server recognises them
  // byte-for-byte, so trying a sample is always free (backend/payments).
  const SAMPLE_FILES = { rental: "rental.txt", employment: "employment.txt" };

  const ACCEPTED = /\.(pdf|jpe?g|png|docx|txt)$/i;

  function initUpload() {
    $$("[data-doc-type]").forEach(btn => btn.addEventListener("click", () => setDocType(btn.dataset.docType)));

    const input = $("#fileInput");
    input.addEventListener("change", () => input.files[0] && setFile(input.files[0]));
    $("#cameraInput").addEventListener("change", e => e.target.files[0] && setFile(e.target.files[0]));
    $("#clearFile").addEventListener("click", () => setFile(null));

    const zone = $("#dropzone");
    ["dragenter", "dragover"].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.add("is-dragging"); }));
    ["dragleave", "drop"].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.remove("is-dragging"); }));
    zone.addEventListener("drop", e => { const f = e.dataTransfer.files[0]; if (f) setFile(f); });

    $$("[data-sample]").forEach(btn => btn.addEventListener("click", async () => {
      const type = btn.dataset.sample;
      setDocType(type);
      let text;
      try { text = await (await fetch(`${API}/static/samples/${SAMPLE_FILES[type]}`)).text(); }
      catch { return showUploadError(t("err.network")); }
      setFile(new File([text], `sample_${type === "rental" ? "lease" : "job_offer"}.txt`, { type: "text/plain" }));
      state.isSample = true;
      updatePayLabel();
    }));

    $("#analyzeBtn").addEventListener("click", startAnalysis);
    $("#consentBox").addEventListener("change", updateAnalyzeEnabled);
  }

  function updateAnalyzeEnabled() {
    $("#analyzeBtn").disabled = !(state.file && $("#consentBox").checked);
  }

  function setDocType(type) {
    state.docType = type;
    $$("[data-doc-type]").forEach(b => {
      const on = b.dataset.docType === type;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-checked", String(on));
    });
  }

  function setFile(file) {
    hideUploadError();
    state.isSample = false;
    if (file && !ACCEPTED.test(file.name) && !(file.type || "").startsWith("image/")) {
      showUploadError(t("err.type"));
      file = null;
    }
    state.file = file;
    updatePayLabel();
    $("#fileChip").hidden = !file;
    $("#fileName").textContent = file ? file.name : "";
    updateAnalyzeEnabled();
    if (!file) { $("#fileInput").value = ""; $("#cameraInput").value = ""; }
  }

  function showUploadError(msg) { const el = $("#uploadError"); el.textContent = msg; el.hidden = false; }
  function hideUploadError() { $("#uploadError").hidden = true; }

  async function startAnalysis() {
    if (!state.file || !$("#consentBox").checked) return;
    const btn = $("#analyzeBtn");
    btn.disabled = true;
    hideUploadError();

    const form = new FormData();
    // camera photos often arrive as "image.jpg" or with no extension
    const name = ACCEPTED.test(state.file.name) ? state.file.name : `photo.${(state.file.type.split("/")[1] || "jpg").replace("jpeg", "jpg")}`;
    form.append("file", state.file, name);
    form.append("document_type", state.docType);
    form.append("consent", "true");   // DPDP: the box above was ticked

    if (needsPayment()) {
      const paid = await payWithRazorpay("analysis", state.file.name);
      if (!paid) { btn.disabled = false; return; }
      Object.entries(paid).forEach(([k, v]) => form.append(k, v));
    }

    try {
      const { job_id } = await api("/analyze-document/start", { method: "POST", body: form });
      go(`#/job/${job_id}`);
    } catch (err) {
      showUploadError(err.message);
      btn.disabled = false;
    }
  }

  /* ════════════ progress (job polling) ════════════ */
  function stopPolling() { clearTimeout(state.pollTimer); state.pollTimer = null; }

  function resumeJob(jobId) {
    showView("progress");
    $("#progressClauses").replaceChildren();
    renderedProgressIds.clear();
    setStage("queued", {});
    poll(jobId);
  }

  const renderedProgressIds = new Set();

  async function poll(jobId) {
    let job;
    try {
      job = await api(`/jobs/${jobId}`);
    } catch (err) {
      $("#progressCurrent").textContent = err.message;
      state.pollTimer = setTimeout(() => poll(jobId), POLL_MS * 3);
      return;
    }

    $("#progressFile").textContent = job.filename || "";
    setStage(job.stage, job);

    for (const clause of job.clauses) {
      const key = clause.clause_row_id || clause.clause_id;
      if (renderedProgressIds.has(key)) continue;
      renderedProgressIds.add(key);
      const card = clauseCard(clause, renderedProgressIds.size - 1);
      card.classList.add("is-flash");
      $("#progressClauses").append(card);
    }

    if (job.status === "done") {
      state.doc = normaliseJobResult(job.result);
      history.replaceState(null, "", `#/document/${job.result.document_id}`);
      showResults();
      loadPendingCount();
      return;
    }
    if (job.status === "failed") {
      go("#/");
      showUploadError([job.error || t("err.generic"),
        job.refunded ? t("pay.refunded", { price: state.config.price_analysis }) : ""].filter(Boolean).join(" "));
      updateAnalyzeEnabled();
      return;
    }
    state.pollTimer = setTimeout(() => poll(jobId), POLL_MS);
  }

  function setStage(stage, job) {
    const order = ["reading", "summarising", "clauses"];
    const idx = order.indexOf(stage === "done" ? "clauses" : stage);
    $$(".stepper li").forEach(li => {
      const i = order.indexOf(li.dataset.stage);
      li.classList.toggle("is-done", i < idx || stage === "done");
      li.classList.toggle("is-active", i === idx && stage !== "done");
    });

    const total = job.total || 0;
    const done = job.done || 0;
    $("#progressCount").textContent = total ? t("progress.count", { done, total }) : "";

    // reading 5%, summary 15%, clauses fill the rest
    let pct = 4;
    if (stage === "summarising") pct = 12;
    if (stage === "clauses") pct = 18 + (total ? (done / total) * 80 : 0);
    if (stage === "done") pct = 100;
    $("#progressFill").style.width = `${pct}%`;

    $("#progressCurrent").textContent =
      stage === "queued" ? t("progress.queued")
        : job.current_title ? t("progress.current", { title: job.current_title }) : "";
  }

  function normaliseJobResult(result) {
    return { ...result, clauses: result.clauses || [], failed_clauses: result.failed_clauses || [] };
  }

  /* ════════════ payments (Razorpay) ════════════ */
  const needsPayment = () => state.config.payments_enabled && state.config.price_analysis > 0 && !state.isSample;

  function updatePayLabel() {
    const cfg = state.config;
    const label = $("#analyzeLabel");
    const note = $("#priceNote");
    if (!label) return;
    label.textContent = needsPayment() ? t("pay.button", { price: cfg.price_analysis }) : t("upload.cta");
    const priced = cfg.payments_enabled && cfg.price_analysis > 0;
    note.hidden = !priced;
    if (priced) {
      note.replaceChildren(state.isSample ? t("pay.noteFreeSample") : t("pay.note", { price: cfg.price_analysis }), " ",
        h("a", { href: "#/pricing", text: t("footer.pricing") }));
    }
  }

  let razorpayScript = null;
  function loadRazorpay() {
    if (window.Razorpay) return Promise.resolve();
    razorpayScript = razorpayScript || new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = "https://checkout.razorpay.com/v1/checkout.js";
      el.onload = resolve;
      el.onerror = () => { razorpayScript = null; reject(new Error(t("err.network"))); };
      document.head.append(el);
    });
    return razorpayScript;
  }

  // Resolves with {razorpay_order_id, razorpay_payment_id, razorpay_signature}, or null if not paid.
  async function payWithRazorpay(purpose, description) {
    toast(t("pay.opening"));
    let order;
    try {
      await loadRazorpay();
      order = await api("/payments/order", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ purpose }),
      });
    } catch (err) {
      showUploadError(err.message);
      return null;
    }
    return new Promise(resolve => {
      let settled = false;
      const done = value => { if (!settled) { settled = true; resolve(value); } };
      const checkout = new window.Razorpay({
        key: order.key_id,
        order_id: order.order_id,
        amount: order.amount,
        currency: order.currency,
        name: state.config.business_name || "Lawgorithm",
        description: (description || "").slice(0, 60),
        theme: { color: "#E8962E" },
        handler: response => done({
          razorpay_order_id: response.razorpay_order_id,
          razorpay_payment_id: response.razorpay_payment_id,
          razorpay_signature: response.razorpay_signature,
        }),
        modal: { ondismiss: () => { toast(t("pay.cancelled")); done(null); } },
      });
      checkout.on("payment.failed", () => toast(t("pay.failed")));   // they can retry inside the checkout
      checkout.open();
    });
  }

  /* ════════════ results ════════════ */
  async function openDocument(id) {
    if (state.doc && state.doc.document_id === id) return showResults();
    // show the results shell straight away (no flash of the home page)
    showView("results");
    $("#resultsTitle").textContent = "";
    $("#verdict").replaceChildren();
    $("#summaryText").textContent = "";
    $("#keyTerms").replaceChildren();
    $("#clauseList").hidden = false;
    $("#docView").hidden = true;
    $("#clauseList").replaceChildren(...[0, 1, 2].map(() => h("div", { class: "clause-card skeleton", "aria-hidden": "true" })));
    try {
      const doc = await api(`/document/${id}`);
      state.doc = { ...doc, failed_clauses: [] };
      showResults();
    } catch (err) {
      go("#/");
      showUploadError(err.message);
    }
  }

  function showResults() {
    state.filter = "all";
    showView("results");
    renderResults(state.doc);
    translateResults(state.doc);
  }

  function renderResults(doc) {
    $("#resultsFile").textContent = doc.filename || "";
    $("#retentionNote").textContent = doc.stored ? "" : t("privacy.retention", { minutes: state.config.retention_minutes });
    $("#resultsTitle").textContent = t(doc.document_type === "employment" ? "results.title.employment" : "results.title.rental");

    // verdict: what to DO, decided by the server (backend/risk/decision.py)
    const counts = { red: 0, amber: 0, green: 0 };
    doc.clauses.forEach(c => { counts[c.risk_level] = (counts[c.risk_level] || 0) + 1; });
    const dd = documentDecision(doc);
    const n = dd.decision === "sign" ? 0 : dd.counts[dd.decision];
    $("#verdict").replaceChildren(
      h("div", { class: "verdict-main" },
        h("span", { class: `verdict-badge decision-${dd.decision}`, text: t(`docDecision.${dd.decision}.badge`) }),
        h("span", { text: dd.decision === "sign" ? t("docDecision.sign") : plural(`docDecision.${dd.decision}`, n) })),
      h("div", { class: "decision-counts" }, DECISION_ORDER.filter(d => dd.counts[d]).map(d =>
        h("span", { class: `decision-count decision-${d}` },
          h("span", { "aria-hidden": "true", text: DECISION_ICON[d] }), `${dd.counts[d]} ${t(`decisionCount.${d}`)}`))),
    );

    renderExpertPanel(doc);

    // summary card
    const summary = doc.document_summary;
    const summaryEl = $("#summaryText");
    summaryEl.textContent = summary ? summary.summary : t("results.noSummary");
    summaryEl.dataset.source = summary ? summary.summary : "";
    applyTranslation(summaryEl, $("#summaryNote"));

    $("#keyTerms").replaceChildren(...((summary && summary.key_terms) || []).slice(0, 8).map(kt =>
      h("div", { class: "key-term" }, h("dt", { text: kt.term }), h("dd", { text: kt.value }))));
    const states = doc.jurisdiction_states || [];
    $("#jurisdiction").textContent = states.length
      ? t("results.state", { states: states.join(", ") })
      : t("results.noState");

    // filters
    $("#countAll").textContent = doc.clauses.length;
    $("#countRed").textContent = counts.red;
    $("#countAmber").textContent = counts.amber;
    $("#countGreen").textContent = counts.green;
    $$(".filter").forEach(f => f.classList.toggle("is-active", f.dataset.filter === state.filter));
    $$("[data-layout]").forEach(b => {
      const on = b.dataset.layout === state.layout;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-checked", String(on));
    });

    renderRiskRing(counts, doc.clauses.length);
    renderActionPlan(doc);
    renderClauseList(doc);
    renderDocView(doc);
    $("#clauseList").hidden = state.layout !== "cards";
    $("#docView").hidden = state.layout !== "document";

    const failed = doc.failed_clauses || [];
    $("#failedList").textContent = failed.length
      ? t("results.failed", { titles: failed.map(f => f.clause_title).join(", ") }) : "";
  }

  function renderRiskRing(counts, total) {
    const ring = $("#riskRing");
    const pct = n => (total ? (n / total) * 100 : 0);
    ring.style.setProperty("--r", pct(counts.red || 0));
    ring.style.setProperty("--a", pct(counts.amber || 0));
    ring.setAttribute("aria-label", `${counts.red || 0} ${t("risk.red")}, ${counts.amber || 0} ${t("risk.amber")}, ${counts.green || 0} ${t("risk.green")}`);
    $("#riskRingCount").textContent = total;
  }

  // Every "what to do" in one checklist, red items first.
  function planItems(doc) {
    const order = { red: 0, amber: 1, green: 2 };
    return doc.clauses
      .filter(c => c.recommended_action && c.risk_level !== "green")
      .sort((a, b) => order[a.risk_level] - order[b.risk_level])
      .map(c => ({ level: c.risk_level, title: titleCase(c.clause_title), action: c.recommended_action }));
  }

  function renderActionPlan(doc) {
    const items = planItems(doc);
    $("#planList").replaceChildren(...(items.length
      ? items.map(item => h("li", { class: item.level },
          h("span", {}, h("span", { class: "plan-clause", text: item.title }), item.action)))
      : [h("li", { class: "green" }, h("span", { text: t("plan.empty") }))]));
  }

  function initActionPlan() {
    $("#planCopy").addEventListener("click", async () => {
      if (!state.doc) return;
      const items = planItems(state.doc);
      const text = [t("plan.title"), ...items.map((it, i) => `${i + 1}. [${t(`risk.${it.level}`)}] ${it.title}: ${it.action}`)].join("\n");
      try { await navigator.clipboard.writeText(text); toast(t("plan.copied")); }
      catch { toast(t("err.generic")); }
    });
    $("#planPrint").addEventListener("click", () => window.print());
  }

  function visibleClauses(doc) {
    return doc.clauses.filter(c => state.filter === "all" || c.risk_level === state.filter);
  }

  function renderClauseList(doc) {
    const list = visibleClauses(doc);
    $("#clauseList").replaceChildren(...(list.length
      ? list.map(c => clauseCard(c, doc.clauses.indexOf(c)))
      : [h("p", { class: "empty-note", text: t("results.empty") })]));
  }

  function riskPill(level) {
    const emoji = { red: "🚩", amber: "⚠️", green: "✅" }[level] || "";
    return h("span", { class: `risk-pill ${level}` }, h("span", { "aria-hidden": "true", text: emoji }), t(`risk.${level}`));
  }

  // Mirrors backend/risk/decision.py, for results saved before decisions existed.
  const DECISION_ORDER = ["lawyer", "expert", "negotiate", "no_lawyer"];
  const DECISION_ICON = { lawyer: "⚖️", expert: "🧑‍⚖️", negotiate: "🤝", no_lawyer: "✅" };

  function clauseDecision(c) {
    if (c.decision) return c.decision;
    const flags = c.review_flags || [];
    if (c.risk_level === "green") return flags.includes("skipped_legal_check") ? "expert" : "no_lawyer";
    const confirmed = c.verification_status === "human_verified" ||
      (["grounded", "partially_grounded"].includes(c.status) && c.citation_valid !== false && !flags.length);
    if (!confirmed) return "expert";
    return c.risk_level === "red" ? "lawyer" : "negotiate";
  }

  function documentDecision(doc) {
    const counts = { lawyer: 0, expert: 0, negotiate: 0, no_lawyer: 0 };
    doc.clauses.forEach(c => { counts[clauseDecision(c)] += 1; });
    const decision = ["lawyer", "expert", "negotiate"].find(d => counts[d]) || "sign";
    return { decision, counts };
  }

  // The human-in-the-loop answer, as one English sentence so it can be
  // translated whole (a template with an English phrase inside it would
  // read badly in other languages).
  function importantSentence(consequence) {
    return consequence
      ? `This clause is important. If you don’t fix it, ${consequence}. For more detail, talk to a lawyer.`
      : "";
  }
  const needsHuman = d => d === "lawyer" || d === "expert";

  function decisionRow(clause) {
    const d = clauseDecision(clause);
    const reviewed = ["human_verified", "rejected"].includes(clause.verification_status);
    const sentence = needsHuman(d) ? importantSentence(clause.consequence) : "";
    const main = sentence ? h("p", { class: "important-sentence", dataset: { source: sentence }, text: sentence }) : null;
    if (main) applyTranslation(main);
    return h("div", { class: `decision-row decision-${d}` },
      h("span", { class: "decision-icon", "aria-hidden": "true", text: DECISION_ICON[d] }),
      h("div", {},
        h("strong", { text: t(`decision.${d}`) },
          reviewed ? h("span", { class: "decision-reviewed", text: ` · ${t(`status.${clause.verification_status}`)}` }) : null),
        main,
        // the "why" stays for no-lawyer / negotiate, and for expert (AI not sure)
        !main || d === "expert" ? h("p", { text: t(`decisionWhy.${d}`) }) : null,
        d === "lawyer" && state.config.free_legal_aid
          ? h("p", { class: "legal-aid", text: t("expert.aidShort", { number: state.config.free_legal_aid }) }) : null));
  }

  function statusNote(clause) {
    const icons = { auto_approved: "◎", pending: "◔", human_verified: "✓", rejected: "✕" };
    const s = clause.verification_status || "pending";
    // with no reviewer behind the queue, "waiting for a human" would be untrue
    const label = s === "pending" && !state.config.review_enabled ? t("status.pending_noreview") : t(`status.${s}`);
    return h("span", { class: "status-note" }, h("span", { "aria-hidden": "true", text: icons[s] || "◔" }), label);
  }

  function clauseCard(clause, index) {
    const level = clause.risk_level || "amber";
    const id = clause.clause_row_id || `c${index}`;
    const conf = Math.round((clause.confidence || 0) * 100);

    const explain = h("p", { class: "clause-explain", dataset: { source: clause.plain_explanation || "" }, text: clause.plain_explanation || "" });
    const explainNote = h("p", { class: "translation-note", hidden: true });
    const action = h("p", { dataset: { source: clause.recommended_action || "" }, text: clause.recommended_action || "" });
    const actionNote = h("p", { class: "translation-note", hidden: true });
    applyTranslation(explain, explainNote);
    applyTranslation(action, actionNote);

    const chips = [];
    const ct = clause.clause_type;
    if (ct && ct.clause_type) chips.push(h("span", { class: "chip", title: `${Math.round(ct.confidence * 100)}%`, text: t("clause.type", { type: ct.label || ct.clause_type }) }));
    (clause.review_flags || []).forEach(f => chips.push(h("span", { class: "chip flag", title: t(`flag.${f}`), text: `⚑ ${t(`flagShort.${f}`)}` })));

    const details = clauseDetails(clause);
    details.hidden = true;
    details.id = `details-${id}`;
    const toggle = h("button", {
      class: "expand-button", "aria-expanded": "false", "aria-controls": details.id,
      onclick: () => {
        const open = details.hidden;
        details.hidden = !open;
        toggle.setAttribute("aria-expanded", String(open));
        toggle.firstChild.textContent = t(open ? "clause.less" : "clause.more");
      },
    }, h("span", { text: t("clause.more") }), h("span", { class: "chev", "aria-hidden": "true", text: "⌄" }));

    return h("article", { class: `clause-card ${level}`, id: `clause-${id}` },
      h("div", { class: "clause-top" },
        h("div", { class: "clause-heading" },
          h("span", { class: "clause-num", text: `§ ${String(clause.clause_id || index + 1).padStart(2, "0")}` }),
          h("h3", { class: "clause-title", text: titleCase(clause.clause_title) })),
        riskPill(level)),
      chips.length ? h("div", { class: "chip-row" }, chips) : null,
      explain, explainNote,
      clause.recommended_action ? h("div", { class: "clause-action" },
        h("span", { class: "action-arrow", "aria-hidden": "true", text: "→" }),
        h("div", {}, h("span", { class: "mono-label", text: t("clause.whatToDo") }), action, actionNote)) : null,
      decisionRow(clause),
      h("div", { class: "clause-foot" },
        h("div", { class: "confidence" },
          h("span", { text: t("clause.confidence") }),
          h("span", { class: "meter", role: "img", "aria-label": `${conf}%` }, h("span", { style: `width:${conf}%` })),
          h("span", { class: "mono", text: `${conf}%` })),
        toggle),
      details);
  }

  function clauseDetails(clause) {
    const flags = clause.review_flags || [];
    const sources = clause.cited_sources || [];
    const claims = clause.claims || [];
    const block = (labelKey, ...content) => h("div", { class: "detail-block" }, h("h4", { class: "mono-label", text: t(labelKey) }), ...content);

    return h("div", { class: "clause-details" },
      clause.clause_text ? block("clause.original", h("p", { class: "original-text", text: clause.clause_text })) : null,
      flags.length ? block("clause.flags", h("ul", { class: "claims" }, flags.map(f => h("li", { text: t(`flag.${f}`) })))) : null,
      block("clause.assessment", h("p", { text: clause.legal_assessment || "—" })),
      claims.length ? block("clause.claims", h("ul", { class: "claims" }, claims.map(c => h("li", { text: c.claim })))) : null,
      block("clause.sources", sources.length
        ? h("div", { class: "clause-list" }, sources.map(sourceItem))
        : h("p", { class: "empty-note", text: t("clause.noSources") })),
    );
  }

  function sourceItem(s) {
    return h("details", { class: "source" },
      h("summary", {},
        h("span", { class: "source-law", text: `${s.law || s.id}${s.section ? `, s.${s.section}` : ""}` }),
        s.title ? h("span", { class: "source-title", text: s.title }) : null),
      h("div", { class: "source-body" },
        h("p", { text: s.text || "" }),
        h("p", { class: "source-meta" },
          t("source.appliesIn", { place: s.jurisdiction || "India" }), " · ",
          s.official_source
            ? h("a", { href: s.official_source, target: "_blank", rel: "noopener noreferrer", text: t("source.official") })
            : t("source.noLink"))));
  }

  // "TERM OF LEASE" -> "Term of Lease"; already mixed-case titles are left alone
  const SMALL_WORDS = new Set(["a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"]);
  function titleCase(s) {
    if (!s || s !== s.toUpperCase()) return s || "";
    return s.toLowerCase().split(" ").map((word, i) =>
      i > 0 && SMALL_WORDS.has(word) ? word : word.replace(/(^|-)\S/g, m => m.toUpperCase())).join(" ");
  }

  /* document view: the contract itself, highlighted */
  function renderDocView(doc) {
    const view = $("#docView");
    view.replaceChildren(h("p", { class: "mono-label", text: t("results.docHint") }));
    doc.clauses.forEach((c, i) => {
      const level = c.risk_level || "amber";
      const callout = h("div", { class: "doc-callout", hidden: true },
        h("div", {}, h("strong", { text: t(`risk.${level}`) }), c.plain_explanation),
        c.recommended_action ? h("div", {}, h("strong", { text: t("clause.whatToDo") }), c.recommended_action) : null,
        (c.cited_sources || []).length
          ? h("div", {}, h("strong", { text: t("clause.sources") }), c.cited_sources.map(s => `${s.law}, s.${s.section}`).join(" · "))
          : null,
        h("div", {}, h("strong", { text: t("clause.confidence") }), `${Math.round((c.confidence || 0) * 100)}% · ${
          (c.verification_status || "pending") === "pending" && !state.config.review_enabled
            ? t("status.pending_noreview") : t(`status.${c.verification_status || "pending"}`)}`));
      const mark = h("span", {
        class: `doc-mark ${level}`, tabindex: "0", role: "button", "aria-expanded": "false",
        onclick: () => toggleCallout(), onkeydown: e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleCallout(); } },
        text: c.clause_text || c.plain_explanation,
      });
      function toggleCallout() {
        callout.hidden = !callout.hidden;
        mark.setAttribute("aria-expanded", String(!callout.hidden));
      }
      view.append(h("div", { class: "doc-clause" },
        h("h4", { text: `§ ${c.clause_id || i + 1} · ${titleCase(c.clause_title)}` }), mark, callout));
    });
  }

  async function deleteCurrentDocument() {
    if (!state.doc) return;
    try {
      await api(`/document/${state.doc.document_id}`, { method: "DELETE" });
    } catch { /* already expired: nothing left to delete */ }
    state.doc = null;
    translations.clear();
    toast(t("privacy.deleted"));
    go("#/");
  }

  function initResultsControls() {
    $("#deleteNowBtn").addEventListener("click", deleteCurrentDocument);
    $$(".filter").forEach(f => f.addEventListener("click", () => {
      state.filter = f.dataset.filter;
      $$(".filter").forEach(x => x.classList.toggle("is-active", x === f));
      renderClauseList(state.doc);
    }));
    $$("[data-layout]").forEach(b => b.addEventListener("click", () => {
      state.layout = b.dataset.layout;
      renderResults(state.doc);
    }));
  }

  /* ════════════ translation of AI text ════════════ */
  // cache: `${lang}::${text}` -> {text, score, validated} | "failed"
  const translations = new Map();
  const tKey = (lang, text) => `${lang}::${text}`;

  function applyTranslation(el, noteEl) {
    const source = el.dataset.source;
    const meta = window.i18n.meta;
    if (!source || !meta.backend) {
      el.classList.remove("is-translating");
      if (source) el.textContent = source;
      if (noteEl) noteEl.hidden = true;
      return;
    }
    const hit = translations.get(tKey(meta.code, source));
    if (!hit) {
      el.classList.add("is-translating");
      if (noteEl) noteEl.hidden = true;
      return;
    }
    el.classList.remove("is-translating");
    if (hit === "failed" || !hit.validated) {
      el.textContent = hit === "failed" ? source : `${hit.text}\n\n${source}`;
      el.style.whiteSpace = "pre-line";
      if (noteEl) {
        noteEl.hidden = false;
        noteEl.className = "translation-note warn";
        noteEl.textContent = hit === "failed" ? t("translate.failed")
          : !hit.numbersOk ? t("translate.numbers")
          : !hit.rolesOk ? t("translate.roles")
          : t("translate.warn");
      }
      return;
    }
    el.textContent = hit.text;
    el.style.whiteSpace = "";
    if (noteEl) { noteEl.hidden = false; noteEl.className = "translation-note"; noteEl.textContent = t("translate.note", { score: Math.round(hit.score * 100) }); }
  }

  async function translateResults(doc) {
    const meta = window.i18n.meta;
    const statusEl = $("#translateStatus");
    const run = ++state.translateRun;
    if (!meta.backend || !doc) { statusEl.hidden = true; return; }

    const texts = [];
    if (doc.document_summary) texts.push(doc.document_summary.summary);
    doc.clauses.forEach(c => {
      texts.push(c.plain_explanation);
      if (c.recommended_action) texts.push(c.recommended_action);
      if (needsHuman(clauseDecision(c))) texts.push(importantSentence(c.consequence));
    });
    const todo = [...new Set(texts.filter(Boolean))].filter(x => !translations.has(tKey(meta.code, x)));
    const total = todo.length;
    if (!total) { statusEl.hidden = true; refreshTranslations(); return; }

    let done = 0;
    statusEl.hidden = false;
    const updateStatus = () => { statusEl.textContent = t("translate.working", { lang: meta.native, done, total }); };
    updateStatus();

    for (const text of todo) {
      if (run !== state.translateRun) return;   // language changed / new doc: abandon
      try {
        const res = await api("/translate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, target_language: meta.backend, validate_translation: true }),
        });
        translations.set(tKey(meta.code, text), {
          text: res.translated_text,
          score: res.similarity_score ?? 0,
          validated: !!res.validated,
          numbersOk: res.numbers_preserved !== false,
          rolesOk: res.roles_preserved !== false,
        });
      } catch {
        translations.set(tKey(meta.code, text), "failed");
      }
      done += 1;
      if (run !== state.translateRun) return;
      updateStatus();
      refreshTranslations();
    }
    statusEl.textContent = t("translate.done", { lang: meta.native });
  }

  function refreshTranslations() {
    $$("[data-source]").forEach(el => {
      const note = el.nextElementSibling && el.nextElementSibling.classList.contains("translation-note") ? el.nextElementSibling : null;
      applyTranslation(el, note);
    });
  }

  document.addEventListener("langchange", () => {
    if (!$("#view-results").hidden && state.doc) translateResults(state.doc);
    renderGame();
  });

  /* ════════════ reviewer desk ════════════ */
  // The menu shows "Reviewer desk" only in a browser where a reviewer is
  // signed in (or on a server with the old stored-documents desk); everyone
  // else gets a quiet "Reviewer sign-in" link in the footer.
  function updateReviewNav() {
    const signedIn = state.config.expert_review_enabled && Boolean(reviewerKey());
    const reviewLink = $('.nav-link[data-view-link="review"]');
    if (reviewLink) reviewLink.hidden = !(state.config.review_enabled || signedIn);
    $("#footerReviewLink").hidden = !state.config.expert_review_enabled;
  }

  async function loadPendingCount() {
    if (state.config.expert_review_enabled) {
      const key = reviewerKey();
      if (!key) return;
      try {
        const { count } = await api("/expert-review/reviewer/queue", { headers: { "X-Reviewer-Key": key } });
        $("#pendingCount").textContent = count;
        $("#pendingCount").hidden = !count;
      } catch { /* bad or removed key: the desk will ask them to sign in */ }
      return;
    }
    if (!state.config.review_enabled) return;
    try {
      const { count } = await api("/verification/pending");
      const el = $("#pendingCount");
      el.textContent = count;
      el.hidden = !count;
    } catch { /* server not up yet — ignore */ }
  }

  async function loadReview() {
    $("#reviewList").replaceChildren(h("p", { class: "empty-note", text: "…" }));
    try {
      const data = await api("/verification/pending");
      state.reviewItems = data.items || [];
      renderReview();
      $("#pendingCount").textContent = data.count;
      $("#pendingCount").hidden = !data.count;
    } catch (err) {
      $("#reviewList").replaceChildren(h("p", { class: "error-banner", text: err.message }));
    }
  }

  function renderReview() {
    const list = $("#reviewList");
    if (!state.reviewItems.length) {
      list.replaceChildren(h("div", { class: "empty-state" }, h("span", { class: "big", "aria-hidden": "true", text: "✨" }), h("p", { text: t("review.empty") })));
      return;
    }
    list.replaceChildren(...state.reviewItems.map((item, i) => {
      const card = clauseCard(item, i);
      card.classList.add("review-card");
      card.insertBefore(h("p", { class: "review-reason" }, h("strong", { text: `${t("review.whyHere")}: ` }), item.flag_reason || ""), card.children[1]);
      card.append(h("div", { class: "review-actions" },
        h("button", { class: "btn btn-ink btn-small", onclick: () => resolve(item, "approve"), text: `✓ ${t("review.approve")}` }),
        h("button", { class: "btn btn-outline btn-small", onclick: () => openEdit(item), text: `✎ ${t("review.edit")}` }),
        h("button", { class: "btn btn-outline btn-small", onclick: () => resolve(item, "request_more_evidence"), text: `⟳ ${t("review.more")}` }),
        h("button", { class: "btn btn-outline btn-small", onclick: () => resolve(item, "reject"), text: `✕ ${t("review.reject")}` })));
      return card;
    }));
  }

  async function resolve(item, action, extra = {}) {
    if (action === "request_more_evidence") toast(t("toast.rerun"));
    try {
      await api(`/verification/${item.clause_row_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ...extra }),
      });
      toast(t({ approve: "toast.approved", reject: "toast.rejected", edit: "toast.saved", request_more_evidence: "toast.rerunDone" }[action]));
      loadReview();
    } catch (err) {
      toast(err.message);
    }
  }

  function openEdit(item) {
    const dlg = $("#editDialog");
    const form = $("#editForm");
    form.explanation.value = item.plain_explanation || "";
    form.action.value = item.recommended_action || "";
    form.reason.value = "";
    $$('input[name="risk"]', form).forEach(r => { r.checked = r.value === item.risk_level; });
    dlg.returnValue = "";
    dlg.showModal();
    dlg.addEventListener("close", function onClose() {
      dlg.removeEventListener("close", onClose);
      if (dlg.returnValue !== "save") return;
      resolve(item, "edit", {
        edited_explanation: form.explanation.value.trim(),
        edited_recommended_action: form.action.value.trim() || null,
        edited_risk_level: (form.querySelector('input[name="risk"]:checked') || {}).value || null,
        reviewer_notes: form.reason.value.trim(),
      });
    });
  }

  /* ════════════ expert review: the human in the loop ════════════ */
  // The person's checks are remembered in this browser only (the link is the key).
  const CHECKS_KEY = "lawgorithm.expertChecks";
  function savedChecks() {
    try { return JSON.parse(localStorage.getItem(CHECKS_KEY) || "[]"); } catch { return []; }
  }
  function rememberCheck(entry) {
    const list = [entry, ...savedChecks().filter(c => c.id !== entry.id)].slice(0, 10);
    try { localStorage.setItem(CHECKS_KEY, JSON.stringify(list)); } catch { /* private mode */ }
    renderMyChecks();
  }
  function forgetCheck(id) {
    try { localStorage.setItem(CHECKS_KEY, JSON.stringify(savedChecks().filter(c => c.id !== id))); } catch { /* ignore */ }
    renderMyChecks();
  }
  function renderMyChecks() {
    const el = $("#myChecks");
    const list = savedChecks();
    el.hidden = !list.length;
    el.replaceChildren(...(list.length ? [
      h("span", { class: "mono-label", text: t("expert.myChecks") }),
      ...list.map(c => h("a", { class: "link-button", href: `#/expert/${c.id}`, text: c.filename || t("expert.view") })),
    ] : []));
  }

  function renderExpertPanel(doc) {
    const panel = $("#expertPanel");
    const uncertain = doc.clauses.filter(c => clauseDecision(c) === "expert");
    const cfg = state.config;
    if (!uncertain.length) { panel.hidden = true; return; }
    panel.hidden = false;

    if (!cfg.expert_review_enabled) {
      // no reviewers yet: a real, free human to talk to instead
      panel.replaceChildren(
        h("span", { class: "expert-icon", "aria-hidden": "true", text: "📞" }),
        h("div", {},
          h("h3", { text: t("expert.aidTitle") }),
          h("p", { text: t("expert.aidText", { number: cfg.free_legal_aid || "15100" }) })));
      return;
    }

    const sent = savedChecks().find(c => c.docId === doc.document_id);
    if (sent) {
      panel.replaceChildren(
        h("span", { class: "expert-icon", "aria-hidden": "true", text: "🧑‍⚖️" }),
        h("div", {},
          h("h3", { text: t("expert.sent") }),
          h("a", { class: "btn btn-ink btn-small", href: `#/expert/${sent.id}` }, t("expert.view"),
            h("span", { class: "btn-arrow", "aria-hidden": "true", text: "→" }))));
      return;
    }

    const consent = h("input", { type: "checkbox", id: "expertConsent" });
    const priced = cfg.payments_enabled && cfg.price_expert > 0;
    const button = h("button", { class: "btn btn-ink btn-small", type: "button" },
      priced ? t("pay.expertButton", { price: cfg.price_expert }) : t("expert.send"),
      h("span", { class: "btn-arrow", "aria-hidden": "true", text: "→" }));
    button.addEventListener("click", async () => {
      if (!consent.checked) { toast(t("expert.consentNeeded")); consent.focus(); return; }
      button.disabled = true;
      let paid = {};
      if (cfg.payments_enabled && cfg.price_expert > 0) {
        paid = await payWithRazorpay("expert", doc.filename);
        if (!paid) { button.disabled = false; return; }
      }
      button.firstChild.textContent = t("expert.sending");
      try {
        const ticket = await api("/expert-review", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ document_id: doc.document_id, clause_row_ids: uncertain.map(c => c.clause_row_id), consent: true, ...paid }),
        });
        rememberCheck({ id: ticket.id, docId: doc.document_id, filename: doc.filename, created: ticket.created_at });
        go(`#/expert/${ticket.id}`);
      } catch (err) {
        toast(err.message);
        button.disabled = false;
        button.firstChild.textContent = t("expert.send");
      }
    });
    panel.replaceChildren(
      h("span", { class: "expert-icon", "aria-hidden": "true", text: "🧑‍⚖️" }),
      h("div", {},
        h("h3", { text: plural("expert.panelTitle", uncertain.length) }),
        h("p", { text: t(cfg.reviewer_kind === "legal" ? "expert.panelSub" : "expert.panelSub.team",
          { keep: cfg.expert_review_keep_days, max: cfg.expert_review_max_days }) }),
        h("label", { class: "consent expert-consent" }, consent,
          h("span", { text: t("expert.consent") })),
        button));
  }

  // ── the person's private ticket page ──
  async function openTicket(id) {
    showView("expert");
    $("#expertList").replaceChildren(h("div", { class: "clause-card skeleton", "aria-hidden": "true" }));
    try {
      state.ticket = await api(`/expert-review/${id}`);
      renderTicket(state.ticket);
      translateList(state.ticket.clauses.flatMap(c => [c.ai.plain_explanation, c.review && c.review.note,
        c.review && c.review.decision !== "no_lawyer" && importantSentence(c.review.consequence)]));
      if (state.ticket.status === "waiting") {
        state.pollTimer = setTimeout(() => { if (!$("#view-expert").hidden) openTicket(id); }, 30000);
      }
    } catch (err) {
      state.ticket = null;
      if (err.status === 404) forgetCheck(id);
      $("#expertStatus").textContent = "";
      $("#expertRetention").textContent = "";
      $("#expertList").replaceChildren(h("p", { class: "error-banner", text: err.status === 404 ? t("expert.gone") : err.message }));
    }
  }

  function renderTicket(ticket) {
    const waiting = ticket.clauses.filter(c => !c.review).length;
    $("#expertStatus").textContent = waiting ? plural("expert.waiting", waiting) : t("expert.done");
    $("#expertRetention").textContent = t("expert.retention", { keep: ticket.keep_days, max: ticket.max_days });
    const date = iso => new Date(iso).toLocaleDateString(document.documentElement.lang || "en", { day: "numeric", month: "short", year: "numeric" });

    $("#expertList").replaceChildren(...ticket.clauses.map(c => {
      const ai = c.ai || {};
      const aiText = h("p", { dataset: { source: ai.plain_explanation || "" }, text: ai.plain_explanation || "" });
      const card = h("article", { class: `clause-card ${(c.review || ai).risk_level || "amber"}` },
        h("div", { class: "clause-top" },
          h("h3", { class: "clause-title", text: titleCase(c.clause_title) }),
          riskPill((c.review || ai).risk_level || "amber")),
        h("div", { class: "detail-block" }, h("h4", { class: "mono-label", text: t("expert.aiSaid") }), aiText),
        c.review ? reviewOutcome(c.review, date) : h("div", { class: "decision-row decision-expert" },
          h("span", { class: "decision-icon", "aria-hidden": "true", text: "⏳" }),
          h("div", {}, h("strong", { text: t("expert.pendingClause") }))));
      applyTranslation(aiText);
      return card;
    }));
  }

  function reviewOutcome(review, date) {
    const sentence = review.decision !== "no_lawyer" ? importantSentence(review.consequence) : "";
    const main = sentence ? h("p", { class: "important-sentence", dataset: { source: sentence }, text: sentence }) : null;
    const note = review.note ? h("p", { dataset: { source: review.note }, text: review.note }) : null;
    const row = h("div", { class: `decision-row decision-${review.decision}` },
      h("span", { class: "decision-icon", "aria-hidden": "true", text: DECISION_ICON[review.decision] || "🧑‍⚖️" }),
      h("div", {},
        h("span", { class: "mono-label", text: t("expert.reviewerSaid") }),
        h("strong", { text: t(`decision.${review.decision}`) }),
        main,
        note,
        h("p", { class: "reviewer-by", text: t("expert.by", { name: review.reviewer, date: date(review.reviewed_at) }) }),
        review.decision === "lawyer" && state.config.free_legal_aid
          ? h("p", { class: "legal-aid", text: t("expert.aidShort", { number: state.config.free_legal_aid }) }) : null));
    if (main) applyTranslation(main);
    if (note) applyTranslation(note);
    return row;
  }

  // translate a handful of texts (no status line), then repaint them
  async function translateList(texts) {
    const meta = window.i18n.meta;
    if (!meta.backend) return;
    for (const text of [...new Set(texts.filter(Boolean))]) {
      if (translations.has(tKey(meta.code, text))) continue;
      try {
        const res = await api("/translate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, target_language: meta.backend, validate_translation: true }),
        });
        translations.set(tKey(meta.code, text), {
          text: res.translated_text, score: res.similarity_score ?? 0, validated: !!res.validated,
          numbersOk: res.numbers_preserved !== false, rolesOk: res.roles_preserved !== false,
        });
      } catch {
        translations.set(tKey(meta.code, text), "failed");
      }
      refreshTranslations();
    }
  }

  function initExpertTicket() {
    $("#expertCopyLink").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(location.href); toast(t("expert.linkCopied")); }
      catch { toast(location.href); }
    });
    $("#expertDelete").addEventListener("click", async () => {
      if (!state.ticket) return;
      try {
        await api(`/expert-review/${state.ticket.id}`, { method: "DELETE" });
        forgetCheck(state.ticket.id);
        state.ticket = null;
        toast(t("expert.deleted"));
        go("#/");
      } catch (err) { toast(err.message); }
    });
    renderMyChecks();
  }

  // ── the reviewer desk (partner lawyers / law students) ──
  const KEY_STORE = "lawgorithm.reviewerKey";
  const reviewerKey = () => { try { return localStorage.getItem(KEY_STORE) || state.inviteKey || null; } catch { return state.inviteKey || null; } };
  const forgetReviewerKey = () => { state.inviteKey = null; try { localStorage.removeItem(KEY_STORE); } catch { /* ignore */ } };

  async function loadExpertDesk(error) {
    const desk = $("#expertDesk");
    desk.hidden = false;
    $("#view-review .section-sub").textContent = t("desk.sub");
    $("#reviewList").hidden = true;
    const key = reviewerKey();
    if (!key) return renderDeskLogin(error);
    desk.replaceChildren(h("p", { class: "empty-note", text: "…" }));
    try {
      state.desk = await api("/expert-review/reviewer/queue", { headers: { "X-Reviewer-Key": key } });
      renderExpertDesk();
      updateReviewNav();
      $("#pendingCount").textContent = state.desk.count;
      $("#pendingCount").hidden = !state.desk.count;
    } catch (err) {
      if (err.status === 401) {
        forgetReviewerKey();
        return renderDeskLogin(t("desk.badKey"));
      }
      desk.replaceChildren(h("p", { class: "error-banner", text: err.message }));
    }
  }

  function renderDeskLogin(error) {
    const input = h("input", { type: "password", class: "desk-input", autocomplete: "off", placeholder: t("desk.key"), "aria-label": t("desk.key") });
    const form = h("form", { class: "desk-login" },
      h("h2", { class: "section-title small", text: t("desk.loginTitle") }),
      h("p", { class: "section-sub", text: t("desk.loginSub") }),
      input,
      error ? h("p", { class: "error-banner", text: error }) : null,
      h("button", { class: "btn btn-ink", type: "submit", text: t("desk.signIn") }));
    form.addEventListener("submit", e => {
      e.preventDefault();
      const key = input.value.trim();
      if (!key) return;
      try { localStorage.setItem(KEY_STORE, key); } catch { state.inviteKey = key; }
      loadExpertDesk();
    });
    $("#expertDesk").replaceChildren(form);
    input.focus();
  }

  function renderExpertDesk() {
    const data = state.desk;
    if (!data) return;
    const signOut = h("button", { class: "btn btn-outline btn-small", type: "button", text: t("desk.signOut") });
    signOut.addEventListener("click", () => {
      forgetReviewerKey();
      state.desk = null;
      updateReviewNav();
      renderDeskLogin();
    });
    const manage = data.role === "owner"
      ? h("button", { class: "btn btn-ink btn-small", type: "button", text: `👥 ${t("desk.manage")}`, onclick: () => toggleTeamPanel() })
      : null;
    const messagesBtn = data.role === "owner"
      ? h("button", { class: "btn btn-outline btn-small", type: "button", text: `📨 ${t("desk.messages")}`, onclick: () => {
          state.messagesOpen = !state.messagesOpen;
          const panel = $("#messagesPanel");
          panel.hidden = !state.messagesOpen;
          if (state.messagesOpen) loadMessages(panel);
        } })
      : null;
    const head = h("div", { class: "desk-head" },
      h("span", { text: t("desk.signedIn", { name: data.reviewer }) }),
      h("strong", { text: plural("desk.count", data.count) }),
      manage, messagesBtn, signOut);
    const team = h("section", { class: "team-panel", id: "teamPanel", hidden: !state.teamOpen });
    if (state.teamOpen) loadTeam(team);
    const inbox = h("section", { class: "team-panel", id: "messagesPanel", hidden: !state.messagesOpen });
    if (state.messagesOpen) loadMessages(inbox);
    if (!data.items.length) {
      return $("#expertDesk").replaceChildren(head, team, inbox,
        h("div", { class: "empty-state" }, h("span", { class: "big", "aria-hidden": "true", text: "✨" }), h("p", { text: t("desk.empty") })));
    }
    $("#expertDesk").replaceChildren(head, team, inbox, ...data.items.map(deskCard));
  }

  // ── owner: manage reviewers (add -> invite link, remove -> revoked at once) ──
  function toggleTeamPanel() {
    state.teamOpen = !state.teamOpen;
    const panel = $("#teamPanel");
    panel.hidden = !state.teamOpen;
    if (state.teamOpen) loadTeam(panel);
  }

  async function loadTeam(panel, invite) {
    const headers = { "X-Reviewer-Key": reviewerKey() || "" };
    let list = [];
    try { list = (await api("/expert-review/reviewers", { headers })).reviewers; }
    catch (err) { return panel.replaceChildren(h("p", { class: "error-banner", text: err.message })); }

    const nameInput = h("input", { type: "text", class: "desk-input", maxlength: 60, placeholder: t("desk.addPlaceholder"), "aria-label": t("desk.addPlaceholder") });
    const addForm = h("form", { class: "team-add" }, nameInput,
      h("button", { class: "btn btn-ink btn-small", type: "submit", text: t("desk.add") }));
    addForm.addEventListener("submit", async e => {
      e.preventDefault();
      const name = nameInput.value.trim();
      if (!name) return nameInput.focus();
      try {
        const added = await api("/expert-review/reviewers", {
          method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify({ name }),
        });
        loadTeam(panel, added);
      } catch (err) { toast(err.message); }
    });

    const rows = list.map(r => h("li", { class: "team-row" },
      h("span", {}, h("strong", { text: r.name }), " ",
        h("span", { class: "mono-label", text: r.role === "owner" ? t("desk.owner") : t("desk.addedOn", { date: new Date(r.added_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) }) })),
      r.role === "owner" ? null : h("button", { class: "btn btn-outline btn-small", type: "button", text: t("desk.remove"),
        onclick: async () => {
          if (!confirm(t("desk.removeConfirm", { name: r.name }))) return;
          try {
            await api(`/expert-review/reviewers/${r.id}`, { method: "DELETE", headers });
            toast(t("desk.removed", { name: r.name }));
            loadTeam(panel);
          } catch (err) { toast(err.message); }
        } })));

    panel.replaceChildren(
      h("h3", { text: t("desk.manage") }),
      h("p", { class: "section-sub", text: t("desk.manageSub") }),
      invite ? inviteBox(invite) : null,
      addForm,
      h("ul", { class: "team-list" }, rows));
    if (!invite) nameInput.focus();
  }

  function inviteBox(invite) {
    const link = `${location.origin}${location.pathname}#/review?invite=${invite.key}`;
    const message = t("desk.inviteMessage", { link });
    return h("div", { class: "invite-box" },
      h("strong", { text: t("desk.inviteReady", { name: invite.name }) }),
      h("input", { type: "text", class: "desk-input invite-link", readonly: true, value: link, onclick: e => e.target.select() }),
      h("div", { class: "invite-actions" },
        h("button", { class: "btn btn-ink btn-small", type: "button", text: `⧉ ${t("desk.copyInvite")}`,
          onclick: async () => {
            try { await navigator.clipboard.writeText(message); toast(t("desk.inviteCopied")); } catch { toast(link); }
          } }),
        h("a", { class: "btn btn-outline btn-small", href: `https://wa.me/?text=${encodeURIComponent(message)}`,
          target: "_blank", rel: "noopener noreferrer", text: t("desk.whatsapp") })),
      h("p", { class: "desk-help", text: t("desk.inviteWarning", { name: invite.name }) }));
  }

  function deskCard(item) {
    const ai = item.ai || {};
    const when = new Date(item.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
    const radios = (name, values, labelKey, checked) => h("fieldset", { class: "risk-radios" },
      h("legend", { text: t(labelKey) }),
      ...values.map(([value, label]) => h("label", {},
        h("input", { type: "radio", name, value, required: true, checked: value === checked }), ` ${label}`)));
    const uid = `${item.ticket_id}-${item.clause_row_id}`;
    const consequence = h("input", { type: "text", class: "desk-input", name: "consequence", value: ai.consequence || "",
      placeholder: t("desk.consequencePlaceholder") });
    const note = h("textarea", { name: "note", rows: 2, placeholder: t("desk.notePlaceholder") });
    const form = h("form", { class: "desk-form" },
      radios(`decision-${uid}`, [["no_lawyer", `✅ ${t("decision.no_lawyer")}`], ["negotiate", `🤝 ${t("decision.negotiate")}`], ["lawyer", `⚖️ ${t("decision.lawyer")}`]], "desk.yourDecision"),
      radios(`risk-${uid}`, [["green", t("risk.green")], ["amber", t("risk.amber")], ["red", t("risk.red")]], "desk.risk", ai.risk_level),
      h("label", {}, h("span", { text: t("desk.consequence") }), consequence,
        h("small", { class: "desk-help", text: t("desk.consequenceHelp") })),
      h("label", {}, h("span", { text: t("desk.noteOptional") }), note),
      h("button", { class: "btn btn-ink btn-small", type: "submit", text: t("desk.submit") }));
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const value = name => (form.querySelector(`input[name="${name}-${uid}"]:checked`) || {}).value;
      try {
        await api(`/expert-review/${item.ticket_id}/clauses/${item.clause_row_id}`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Reviewer-Key": reviewerKey() || "" },
          body: JSON.stringify({ decision: value("decision"), risk_level: value("risk"),
            consequence: consequence.value.trim(), note: note.value.trim() }),
        });
        toast(t("desk.saved"));
        loadExpertDesk();
      } catch (err) { toast(err.message); }
    });

    const sources = ai.cited_sources || [];
    return h("article", { class: `clause-card review-card ${ai.risk_level || "amber"}` },
      h("p", { class: "mono-label", text: t("desk.meta", {
        type: item.document_type || "", states: (item.jurisdiction_states || []).join(", ") || t("desk.anyState"), date: when }) }),
      h("div", { class: "clause-top" },
        h("h3", { class: "clause-title", text: titleCase(item.clause_title) }), riskPill(ai.risk_level || "amber")),
      h("div", { class: "detail-block" }, h("h4", { class: "mono-label", text: t("desk.original") }),
        h("p", { class: "original-text", text: item.clause_text })),
      h("div", { class: "detail-block" }, h("h4", { class: "mono-label", text: t("desk.ai") }),
        h("p", { text: ai.plain_explanation || "—" }),
        h("p", {}, h("strong", { text: `${t("desk.assessment")}: ` }), ai.legal_assessment || "—"),
        h("p", {}, h("strong", { text: `${t("clause.whatToDo")}: ` }), ai.recommended_action || "—"),
        ai.consequence ? h("p", {}, h("strong", { text: `${t("desk.consequence")} ` }), ai.consequence) : null,
        h("p", {}, h("strong", { text: `${t("desk.aiDecision")}: ` }), `${t(`decision.${ai.decision || "expert"}`)} · ${Math.round((ai.confidence || 0) * 100)}%`)),
      (ai.review_flags || []).length ? h("div", { class: "detail-block" }, h("h4", { class: "mono-label", text: t("desk.flags") }),
        h("ul", { class: "claims" }, ai.review_flags.map(f => h("li", { text: t(`flag.${f}`) })))) : null,
      h("div", { class: "detail-block" }, h("h4", { class: "mono-label", text: t("desk.sources") }),
        sources.length ? h("ul", { class: "claims" }, sources.map(src => h("li", {},
          src.official_source ? h("a", { href: src.official_source, target: "_blank", rel: "noopener noreferrer", text: `${src.law}, s.${src.section}` })
            : `${src.law}, s.${src.section}`, src.title ? ` — ${src.title}` : "")))
          : h("p", { text: t("desk.noSources") })),
      form);
  }

  /* ════════════ pricing / terms / refunds / contact ════════════ */
  // Terms and refund policy are legal documents: English (with a translated
  // note saying so), as is usual in India. Everything else is translated.
  const rupees = n => `₹${n}`;

  function legalSections(kind) {
    const c = state.config;
    const biz = c.business_name || "Lawgorithm";
    const reach = c.contact_email ? `the Contact page or ${c.contact_email}` : "the Contact page";
    if (kind === "terms") return [
      ["What Lawgorithm is", `${biz} is a software tool that explains rental and job contracts in plain language and points to the Indian law behind each point. It is not a law firm, it does not give legal advice, and using it does not create a lawyer–client relationship. Explanations are produced by AI and can be wrong; we show how confident each answer is and flag clauses we could not confirm. For any important decision, and anything marked “Talk to a lawyer”, consult an enrolled advocate.`],
      ["Human checks", `If you ask for a human check, a member of our team${c.reviewer_kind === "legal" ? " (a lawyer or law student)" : ""} looks at the clauses you send and adds a note. This is a second opinion on our explanation, not legal advice or representation.`],
      ["Your use", "Upload only documents you have the right to share. Do not use the service for anything unlawful or to harm others. We may refuse or stop service that is being misused."],
      ["Payments", c.payments_enabled
        ? `A contract check costs ${rupees(c.price_analysis)}${c.price_expert > 0 ? ` and a human check ${rupees(c.price_expert)}` : ""}; the price is shown before you pay. Payments are processed by Razorpay — we never see your card, UPI or bank details. Prices are in Indian rupees. The sample contracts are free.`
        : "The service is currently free to use."],
      ["Refunds", "See the Refund policy. In short: if a check fails on our side, you are refunded in full automatically."],
      ["Privacy", "Your contract is never saved; see the Privacy notice for exactly how your data is handled under the Digital Personal Data Protection Act, 2023."],
      ["Liability", `We work hard to be accurate, but we do not guarantee any outcome. To the extent the law allows, ${biz}'s total liability for any claim is limited to the amount you paid for the check concerned.`],
      ["Changes and law", `We may update these terms; the version on this page applies. These terms are governed by the laws of India. Questions: ${reach}.`],
    ];
    return [
      ["Automatic refunds", `If you paid and the check fails on our side — for example the AI service is down — or you delete your contract before the check starts, the full amount is refunded automatically. You don't need to ask.`],
      ["Other problems", `If you were charged but didn't receive your results, or were charged twice, write to us through ${reach} within 7 days with the payment ID from your Razorpay receipt. We'll check and refund in full.`],
      ["After the results are delivered", "A check is complete once your results are shown, so it isn't refundable after that. If you think something went wrong with your results, tell us — we will look into it."],
      ["How long it takes", "Refunds go back to the original payment method (UPI, card or bank) and normally reach you within 5–7 working days, depending on your bank."],
      ["Cancellation", "There are no subscriptions — you pay per contract, so there is nothing to cancel. You can close the payment window at any time before paying and nothing is charged."],
    ];
  }

  function renderInfo(kind) {
    state.infoPage = kind;
    const c = state.config;
    const englishNote = $("#infoEnglishNote");
    englishNote.hidden = !(kind === "terms" || kind === "refunds") || window.i18n.lang === "en";
    englishNote.textContent = t("legal.englishOnly");
    const body = $("#infoBody");

    if (kind === "terms" || kind === "refunds") {
      $("#infoEyebrow").textContent = t(kind === "terms" ? "footer.terms" : "footer.refunds");
      $("#infoTitle").textContent = kind === "terms" ? "Terms of use" : "Refund & cancellation policy";
      body.replaceChildren(h("ol", { class: "privacy-list" }, legalSections(kind).map(([title, text]) =>
        h("li", {}, h("strong", { text: title }), h("p", { text })))));
      return;
    }

    if (kind === "pricing") {
      $("#infoEyebrow").textContent = t("pricing.eyebrow");
      $("#infoTitle").textContent = t("pricing.title");
      const price = n => (c.payments_enabled && n > 0 ? rupees(n) : t("pricing.free"));
      const card = (title, amount, text) => h("div", { class: "price-card" },
        h("span", { class: "mono-label", text: title }),
        h("strong", { class: "price-amount", text: amount }),
        h("p", { text }));
      body.replaceChildren(h("div", { class: "price-grid" },
        card(t("pricing.check"), `${price(c.price_analysis)}${c.payments_enabled && c.price_analysis > 0 ? ` ${t("pricing.perContract")}` : ""}`, t("pricing.checkD")),
        card(t("pricing.samples"), t("pricing.free"), t("pricing.samplesD")),
        card(t("pricing.expert"), c.payments_enabled && c.price_expert > 0 ? `${rupees(c.price_expert)} ${t("pricing.perContract")}` : t("pricing.expertFree"), t("pricing.expertD")),
        card(t("pricing.refund"), "↺", t("pricing.refundD"))));
      return;
    }

    // contact / grievances (DPDP Act)
    $("#infoEyebrow").textContent = t("contact.eyebrow");
    $("#infoTitle").textContent = t("contact.title");
    const topic = h("select", { name: "topic", class: "desk-input" },
      ["grievance", "payment", "question", "other"].map(v => h("option", { value: v, text: t(`contact.t.${v}`) })));
    const message = h("textarea", { name: "message", rows: 5, required: true, minlength: 5, maxlength: 2000 });
    const replyTo = h("input", { type: "text", name: "reply_to", class: "desk-input", maxlength: 200, autocomplete: "email" });
    const trap = h("input", { type: "text", name: "website", tabindex: "-1", autocomplete: "off", class: "visually-hidden", "aria-hidden": "true" });
    const form = h("form", { class: "desk-form contact-form" },
      h("label", {}, h("span", { text: t("contact.topic") }), topic),
      h("label", {}, h("span", { text: t("contact.message") }), message),
      h("label", {}, h("span", { text: t("contact.replyTo") }), replyTo, h("small", { class: "desk-help", text: t("contact.replyHelp") })),
      trap,
      h("button", { class: "btn btn-ink", type: "submit", text: t("contact.send") }));
    form.addEventListener("submit", async e => {
      e.preventDefault();
      try {
        await api("/contact", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ topic: topic.value, message: message.value.trim(), reply_to: replyTo.value.trim(), website: trap.value }) });
        form.replaceWith(h("p", { class: "contact-sent", text: `✓ ${t("contact.sent")}` }));
      } catch (err) { toast(err.message); }
    });
    body.replaceChildren(
      h("p", { class: "section-sub", text: t("contact.sub") }),
      c.contact_form ? form : null,
      c.contact_email ? h("p", {}, `${t("contact.email")} `, h("a", { href: `mailto:${c.contact_email}`, text: c.contact_email })) : null,
      h("p", { class: "desk-help" }, `${t("contact.rights")} `,
        h("a", { href: c.dpdp_act_url || "#/privacy", target: "_blank", rel: "noopener noreferrer", text: "DPDP Act, 2023 ↗" })));
  }

  // ── owner: messages from the Contact page ──
  async function loadMessages(panel) {
    const headers = { "X-Reviewer-Key": reviewerKey() || "" };
    let messages = [];
    try { messages = (await api("/contact/messages", { headers })).messages; }
    catch (err) { return panel.replaceChildren(h("p", { class: "error-banner", text: err.message })); }
    panel.replaceChildren(h("h3", { text: t("desk.messages") }),
      messages.length ? h("ul", { class: "team-list" }, messages.map(m => h("li", { class: "message-row" },
        h("div", {},
          h("span", { class: "mono-label", text: `${t(`contact.t.${m.topic}`)} · ${new Date(m.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` }),
          h("p", { class: "message-text", text: m.message }),
          h("p", { class: "desk-help", text: `${t("desk.replyTo")}: ${m.reply_to || t("desk.noReplyTo")}` })),
        h("button", { class: "btn btn-outline btn-small", type: "button", text: t("desk.delete"), onclick: async () => {
          if (!confirm(t("desk.deleteMsgConfirm"))) return;
          try { await api(`/contact/messages/${m.id}`, { method: "DELETE", headers }); loadMessages(panel); }
          catch (err) { toast(err.message); }
        } }))))
      : h("p", { class: "desk-help", text: t("desk.messagesEmpty") }));
  }

  /* ════════════ landing page ════════════ */
  function initLanding() {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    $$("#view-home > section, #view-home > .hero").forEach(el => {
      if (!el.classList.contains("impact")) el.classList.add("reveal");
    });

    const seen = new IntersectionObserver(entries => entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-visible");
      $$(".count-up", entry.target).forEach(countUp);
      seen.unobserve(entry.target);
    }), { threshold: 0.18 });
    $$(".reveal, .impact, .finale").forEach(el => seen.observe(el));


    function countUp(el) {
      if (el.dataset.counted) return;
      el.dataset.counted = "1";
      const target = Number(el.dataset.countTo);
      const fmt = n => Math.round(n).toLocaleString("en-IN");
      if (reduce) { el.textContent = fmt(target); return; }
      const start = performance.now(), duration = target > 1000 ? 2200 : 900;
      const tick = now => {
        const p = Math.min(1, (now - start) / duration);
        el.textContent = fmt(target * (1 - Math.pow(1 - p, 4)));   // ease-out
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }

    renderGame();
  }

  /* ── "spot the red flag" ── */
  // Real clause wordings; the answers are grounded in the statute library.
  // Clause wordings live in i18n.js (game.cN.text) so they follow the language.
  const GAME = [
    { text: "game.c1.text", answer: "green", why: "game.c1.why" },
    { text: "game.c2.text", answer: "red", why: "game.c2.why" },
    { text: "game.c3.text", answer: "red", why: "game.c3.why" },
    { text: "game.c4.text", answer: "amber", why: "game.c4.why" },
  ];
  const game = { index: 0, score: 0, picked: null };

  function renderGame() {
    const card = $("#gameCard");
    if (!card) return;
    if (game.index >= GAME.length) {
      card.replaceChildren(h("div", { class: "game-score" },
        h("span", { class: "big", text: `${game.score}/${GAME.length}` }),
        h("strong", { text: t("game.score", { score: game.score, total: GAME.length }) }),
        h("p", { class: "section-sub", text: t("game.scoreLine") }),
        h("div", { class: "row" },
          h("button", { class: "btn btn-ink", onclick: () => document.getElementById("start").scrollIntoView({ behavior: "smooth" }) },
            t("game.try"), h("span", { class: "btn-arrow", "aria-hidden": "true", text: "→" })),
          h("button", { class: "btn btn-outline", onclick: () => { Object.assign(game, { index: 0, score: 0, picked: null }); renderGame(); }, text: t("game.again") }))));
      return;
    }
    const q = GAME[game.index];
    const answered = game.picked !== null;
    const choice = level => h("button", {
      class: `game-choice ${level}${game.picked === level ? " picked" : ""}${answered && q.answer === level ? " answer" : ""}`,
      disabled: answered,
      onclick: () => { game.picked = level; if (level === q.answer) game.score += 1; renderGame(); },
    }, h("span", { "aria-hidden": "true", text: { red: "🚩", amber: "⚠️", green: "✅" }[level] }), t(`risk.${level}`));

    card.replaceChildren(...[
      h("div", { class: "game-progress" }, GAME.map((_, i) =>
        h("span", { class: i < game.index ? "done" : i === game.index ? "now" : "" }))),
      h("div", { class: "game-meta" }, h("span", { text: t("game.q", { n: game.index + 1, total: GAME.length }) }),
        h("span", { text: `${t("game.scoreLabel")}: ${game.score}` })),
      h("p", { class: "game-clause", text: `“${t(q.text)}”` }),
      h("div", { class: "game-choices" }, ["red", "amber", "green"].map(choice)),
      answered ? h("div", { class: `game-result ${game.picked === q.answer ? "right" : "wrong"}` },
        h("strong", { text: game.picked === q.answer ? t("game.right") : t("game.wrong") }),
        h("p", {}, h("b", { text: `${t("game.answerIs")} ${t(`risk.${q.answer}`)}. ` }), t(q.why)),
        h("button", { class: "btn btn-ink btn-small", onclick: () => { game.index += 1; game.picked = null; renderGame(); } },
          game.index + 1 < GAME.length ? t("game.next") : t("game.finish"))) : null,
    ].filter(Boolean));   // replaceChildren would print a literal "null"
  }

  /* ════════════ nav ════════════ */
  function initNav() {
    document.addEventListener("click", e => {
      const link = e.target.closest("[data-view-link]");
      if (link) {
        e.preventDefault();
        const view = link.dataset.viewLink;
        if (view === "home") { setFile(null); $("#analyzeBtn").disabled = true; go("#/"); }
        else go(`#/${view}`);
        return;
      }
      const scroll = e.target.closest("[data-scroll-to]");
      if (scroll) {
        e.preventDefault();
        if ($("#view-home").hidden) go("#/");
        requestAnimationFrame(() => document.getElementById(scroll.dataset.scrollTo).scrollIntoView({ behavior: "smooth" }));
      }
    });
    window.addEventListener("hashchange", route);
  }

  /* ════════════ boot ════════════ */
  initTheme();
  initLanguage();
  initUpload();
  initResultsControls();
  initNav();
  initLanding();
  initActionPlan();
  initExpertTicket();
  loadConfig().then(() => { route(); loadPendingCount(); });
})();
