/* AGX dashboard page. No external URLs. All reads are GET requests. The ONLY write function is postWrite(): the
   model controller on the Models page (/api/models/..., docs/MODEL_CONTROL_API.md) and the pairing of RK boards on the
   Settings page (/api/pair/..., docs/PAIRING_API.md). No service control.
   Pages: router.js (hash routing, pure functions). Camera tile state: tiles.js (pure functions). */
(function () {
  "use strict";

  const PAGE_VERSION = "2.1 (2026-10-07: sidebar pages, model control, RK link pairing)";
  const R = window.AGXRouter;
  const T = window.AGXTiles;
  const $ = (id) => document.getElementById(id);
  const NA = "n/a";
  const SVGNS = document.querySelector(".brand__icon").namespaceURI;  // the SVG namespace, from the inline brand icon (no URL in this file)

  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else e.setAttribute(k, v);
    }
    for (const k of kids) if (k != null && k !== false) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
    return e;
  }
  function setText(id, v, cls) {
    const e = $(id); if (!e) return;
    e.textContent = v;
    if (cls !== undefined) e.className = cls;
  }
  const num = (v) => typeof v === "number" && isFinite(v);
  function fmt(v, d = 1, unit = "") { return num(v) ? v.toFixed(d) + (unit ? " " + unit : "") : NA; }
  function fmtBps(b) {
    if (!num(b)) return NA;
    const bits = b * 8;
    if (bits >= 1e9) return (bits / 1e9).toFixed(2) + " Gb/s";
    if (bits >= 1e6) return (bits / 1e6).toFixed(2) + " Mb/s";
    if (bits >= 1e3) return (bits / 1e3).toFixed(1) + " kb/s";
    return bits.toFixed(0) + " b/s";
  }
  function fmtDur(s) {
    if (!num(s)) return NA;
    s = Math.floor(s);
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return (d ? d + " d " : "") + String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }
  const fmtTime = (t) => (num(t) ? new Date(t * 1000).toLocaleTimeString() : NA);
  const fmtDateTime = (t) => (num(t) ? new Date(t * 1000).toLocaleString() : NA);
  const lvClass = (lv) => "lv-" + (lv === "ok" || lv === "warn" || lv === "crit" ? lv : "na");
  const lvWord = (lv) => ({ ok: "OK", warn: "WARN", crit: "CRIT" }[lv] || NA);
  const LV_TONE = { ok: "green", warn: "amber", crit: "red" };
  const LV_LIGHT = { ok: "green", warn: "amber", crit: "red" };
  function fill(tbody, rows) { tbody.replaceChildren(...rows); }
  function badge(text, tone, title) {
    return el("span", { class: "da-badge da-badge--" + (tone || "neutral"), title: title || null }, text);
  }
  function simBadge(on) { return on ? badge("SIMULATED", "info") : null; }
  function setBadge(id, text, tone, title) {
    const e = $(id); if (!e) return;
    e.textContent = text;
    e.className = "da-badge da-badge--" + (tone || "neutral");
    if (title !== undefined) e.title = title;
  }
  function emptyRow(cols, text) { return el("tr", null, el("td", { colspan: String(cols), class: "da-table__empty" }, text)); }
  // a table cell with the column label for the narrow-screen card layout (da-table--stack)
  function td(label, attrs, ...kids) { return el("td", Object.assign({ "data-label": label }, attrs || {}), ...kids); }
  function kvList(items) {
    return el("dl", { class: "da-kv" }, ...items.filter(Boolean).map(([k, v, title]) =>
      el("div", { class: "da-kv__row" }, el("dt", null, k), el("dd", { title: title || null }, v == null || v === "" ? NA : v))));
  }

  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store", credentials: "same-origin" });
    if (!r.ok) {
      let why = "";
      try { const d = await r.json(); why = d && (d.reason || d.error) ? ": " + (d.reason || d.error) : ""; } catch (e) { /* plain text */ }
      throw new Error(url + " -> HTTP " + r.status + why);
    }
    return r.json();
  }

  /* ---------------- traffic light (the rk console TrafficLight: a shape and a text, not colour alone) ---------------- */
  const TL_TEXT = { green: "OK", amber: "Warning", red: "Fault", unknown: "Unknown", off: "Off" };
  const TL_SHAPES = {
    green: [["circle", { cx: 8, cy: 8, r: 8, fill: "currentColor" }], ["path", { class: "da-tl__glyph", d: "M4.6 8.3l2.2 2.2 4.6-4.7" }]],
    amber: [["path", { d: "M8 .9 15.4 14.6H.6Z", fill: "currentColor", stroke: "currentColor", "stroke-width": "1.2", "stroke-linejoin": "round" }],
      ["path", { class: "da-tl__glyph", d: "M8 5.6v4.1M8 12.2v.1" }]],
    red: [["path", { d: "M5 .5h6L15.5 5v6L11 15.5H5L.5 11V5Z", fill: "currentColor" }], ["path", { class: "da-tl__glyph", d: "M5.4 5.4l5.2 5.2M10.6 5.4l-5.2 5.2" }]],
    off: [["circle", { cx: 8, cy: 8, r: 6.6, fill: "none", stroke: "currentColor", "stroke-width": "2" }]],
    unknown: [["circle", { cx: 8, cy: 8, r: 8, fill: "currentColor" }], ["path", { class: "da-tl__glyph", d: "M6 6.1a2 2 0 1 1 2.8 1.8c-.5.3-.8.7-.8 1.3v.3M8 11.9v.1" }]],
  };
  function trafficLight(status, size, showText, label) {
    const s = Object.prototype.hasOwnProperty.call(TL_TEXT, status) ? status : "unknown";
    const text = label || TL_TEXT[s];
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16"); svg.setAttribute("aria-hidden", "true");
    for (const [tag, attrs] of TL_SHAPES[s]) {
      const p = document.createElementNS(SVGNS, tag);
      for (const [k, v] of Object.entries(attrs)) p.setAttribute(k, String(v));
      svg.append(p);
    }
    return el("span", { class: "da-tl da-tl--" + s + " da-tl--" + (size || "md"), title: text }, svg,
      showText === false ? el("span", { class: "da-visually-hidden" }, text) : el("span", { class: "da-tl__text" }, text));
  }

  /* ---------------- status tile (the rk console StatusTile) ---------------- */
  function statusTile(o) {
    const rs = (o.reasons || []).filter(Boolean);
    const max = o.maxReasons || 2;
    const figs = o.figures || [];
    return el("a", { class: "da-tile da-tile--" + (o.status || "unknown"), href: o.href, id: o.id || null },
      el("div", { class: "da-tile__head" }, el("span", { class: "da-tile__title" }, o.title), trafficLight(o.status, "sm")),
      figs.length ? el("dl", { class: "da-tile__figs" + (o.columns === 2 ? " da-tile__figs--2" : "") },
        ...figs.map((f) => el("div", null, el("dt", null, f.label),
          el("dd", { title: typeof f.value === "string" ? f.value : null }, f.value == null || f.value === "" ? NA : f.value)))) : null,
      rs.length ? el("ul", { class: "da-tile__reasons" }, ...rs.slice(0, max).map((r) => el("li", null, r)),
        rs.length > max ? el("li", null, (rs.length - max) + " more") : null) : null,
      o.footer ? el("div", { class: "da-tile__foot" }, o.footer) : null);
  }

  /* ---------------- information controls: the "i" button shows and hides the explanation ---------------- */
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest && ev.target.closest(".info-btn");
    if (!b) return;
    const box = $(b.getAttribute("aria-controls"));
    if (!box) return;
    box.hidden = !box.hidden;
    b.setAttribute("aria-expanded", String(!box.hidden));
  });

  /* ---------------- theme (system / light / dark, kept in localStorage) ---------------- */
  const THEME_KEY = "agx-dashboard-theme";
  function readTheme() {
    try { const t = localStorage.getItem(THEME_KEY); return t === "light" || t === "dark" ? t : "system"; } catch (e) { return "system"; }
  }
  function applyTheme(t, save) {
    const root = document.documentElement;
    if (t === "light" || t === "dark") root.setAttribute("data-theme", t); else root.removeAttribute("data-theme");
    if (save) { try { localStorage.setItem(THEME_KEY, t); } catch (e) { /* private window: not kept */ } }
    document.querySelectorAll("#theme-seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeSet === t)));
    resetCharts();
  }
  document.querySelectorAll("#theme-seg button").forEach((b) => b.addEventListener("click", () => applyTheme(b.dataset.themeSet, true)));
  if (window.matchMedia) {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => { if (readTheme() === "system") resetCharts(); };
    if (mq.addEventListener) mq.addEventListener("change", onChange); else if (mq.addListener) mq.addListener(onChange);
  }
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  /* ---------------- live health (SSE) ---------------- */
  let lastMsg = 0;
  let lastInfer = null;  // infer_reason from the last health message (null when agx-infer sends status)
  let lastHealth = null, lastServices = null;
  let nodeName = "";      // node name of this AGX (/api/health node_name; config node_name, default the host name)
  // the power log part of this AGX: the "part" of the power document, else the node name
  function powerPart(d) { return (d && d.part) || nodeName || "agx"; }
  function renderHealth(h) {
    lastHealth = h;
    nodeName = h.node_name || h.hostname || nodeName;   // config node_name (default: the short host name)
    const host = nodeName || "agx";
    setText("host", host);
    setText("side-host", host);
    document.title = R.label(currentPage) + " · " + host + " dashboard";
    lastInfer = h.infer_reason || null;
    const ns = h.node_state || "NO DATA";
    setBadge("node-state", ns, LV_TONE[ns.toLowerCase()] || "neutral", "Source: " + (h.node_state_source || NA));
    const rs = $("state-reasons");
    if (h.node_state_reasons && h.node_state_reasons.length) {
      rs.hidden = false; rs.textContent = "Node state " + ns + ": " + h.node_state_reasons.join("; ");
    } else rs.hidden = true;
    $("sim-badge").hidden = !h.simulated;
    setText("time", h.time_iso ? new Date(h.time * 1000).toLocaleTimeString() : NA);
    setText("uptime", fmtDur(h.uptime_s));
    const nv = h.nvpmodel || {};
    setText("nvp", nv.mode ? nv.mode + (num(nv.id) ? " (" + nv.id + ")" : "") : NA + (nv.error ? " (" + nv.error + ")" : ""));

    // CPU
    const c = h.cpu || {};
    setText("cpu-avg", fmt(c.load_pct_avg, 0, "%"));
    const cores = (c.per_core || []).map((v, i) => {
      const f = (c.freq_mhz || [])[i];
      const bar = el("i"); bar.style.width = (num(v) ? v : 0) + "%";
      return el("div", { class: "core" },
        el("div", { title: (c.per_core_na || {})[i] || null }, "CPU" + i + " ", el("b", null, num(v) ? v.toFixed(0) + "%" : NA)),
        el("div", { class: "f", title: (c.freq_na || {})[i] || null }, num(f) ? f + " MHz" : "frequency " + NA),
        el("div", { class: "bar" }, bar));
    });
    $("cpu-cores").replaceChildren(...cores);

    // GPU / RAM
    const g = h.gpu || {};
    setText("gpu-load", fmt(g.load_pct, 1, "%")); $("gpu-load").title = g.load_na || "";
    $("gpu-bar").style.width = (num(g.load_pct) ? g.load_pct : 0) + "%";
    setText("gpu-freq", fmt(g.freq_mhz, 0, "MHz")); $("gpu-freq").title = g.freq_na || "";
    const r = h.ram || {};
    setText("ram", num(r.pct) ? `${r.used_mb} / ${r.total_mb} MB (${r.pct.toFixed(1)} %) ${lvWord(r.level)}` : NA + (r.na ? " (" + r.na + ")" : ""), "v " + lvClass(r.level));
    $("ram").title = r.used_def ? "Used = " + r.used_def : "";
    const rb = $("ram-bar"); rb.style.width = (num(r.pct) ? r.pct : 0) + "%"; rb.className = lvClass(r.level);
    const s = h.swap || {};
    setText("swap", num(s.total_mb) ? `${s.used_mb} / ${s.total_mb} MB (${fmt(s.pct, 1, "%")})` : NA + (s.na ? " (" + s.na + ")" : ""));

    // temperatures
    const t = h.temps || {};
    setText("temp-max", num(t.max_c) ? `${t.max_c.toFixed(1)} °C ${lvWord(t.level)}` : NA, "big " + lvClass(t.level));
    const zones = Object.entries(t.zones || {});
    fill($("temp-tbl").tBodies[0], zones.map(([name, v]) => {
      const isMax = name === t.max_zone;
      return el("tr", { class: isMax ? "max" : null },
        el("td", null, name, isMax ? " (max)" : ""),
        el("td", { class: "n" + (num(v) ? "" : " na"), title: (t.na || {})[name] || null },
          num(v) ? v.toFixed(1) + " °C" : NA + " (not readable)"));
    }));

    // power + fan
    const p = h.power || {};
    setText("power-total", fmt(p.total_w, 1, "W"));
    setText("power-src", "Total: " + (p.total_source || NA));
    fill($("power-tbl").tBodies[0], Object.entries(p.rails || {}).map(([n, v]) =>
      el("tr", { title: v.na || null }, el("td", null, n), el("td", { class: "n" }, fmt(v.v, 2)), el("td", { class: "n" }, fmt(v.a, 2)), el("td", { class: "n" }, fmt(v.w, 2)))));
    const f = h.fan || {};
    setText("fan", (num(f.pwm_pct) ? f.pwm_pct.toFixed(0) + " % PWM" : "PWM " + NA) + ", " + (num(f.rpm) ? f.rpm + " rpm" : "rpm " + NA));
    $("fan").title = [f.pwm_na, f.rpm_na].filter(Boolean).join("; ");

    // disks
    $("disks").replaceChildren(...(h.disk || []).map((d) => {
      const bar = el("i", { class: lvClass(d.level) }); bar.style.width = (num(d.pct) ? d.pct : 0) + "%";
      return el("div", { class: "disk" },
        el("div", { class: "row" }, el("span", null, d.mount, el("span", { class: "muted" }, " " + d.fs)),
          el("span", { class: "v " + lvClass(d.level), title: "GiB = 2^30 bytes (the unit of df -h)" }, `${fmt(d.pct, 1, "%")} used, ${fmt(d.free_gib, 1, "GiB")} free of ${fmt(d.total_gib, 1, "GiB")} ${lvWord(d.level)}`)),
        el("div", { class: "bar" }, bar));
    }));

    // network
    fill($("net-tbl").tBodies[0], (h.net || []).map((n) => el("tr", null,
      td("Interface", null, n.if), td("State", { class: n.state === "up" ? "lv-ok" : "muted" }, n.state),
      td("Speed", { class: "n", title: n.speed_na || null }, num(n.speed_mbps) ? n.speed_mbps + " Mb/s" : NA),
      td("RX", { class: "n", title: n.rate_na || null }, fmtBps(n.rx_bps)), td("TX", { class: "n", title: n.rate_na || null }, fmtBps(n.tx_bps)),
      td("IPv4", null, (n.addrs || []).join(", ") || "-"))));

    // link
    const l = h.link || {};
    setText("rk-ip", l.rk_ip || NA);
    setText("ping", num(l.ping_ms) ? l.ping_ms.toFixed(1) + " ms" : NA + (l.ping_error ? " (" + l.ping_error + ")" : ""));
    setText("loss-k", "Packet loss (" + (num(l.loss_window_s) ? l.loss_window_s.toFixed(0) + " s" : NA) + ")");
    setText("loss", num(l.loss_pct) ? `${l.loss_pct.toFixed(0)} % (${l.loss_samples} pings)` : NA + " (" + (l.ping_error && l.ping_error !== "not measured yet" ? l.ping_error : "no ping samples yet") + ")");
    setText("clock", num(l.clock_offset_ms)
      ? `${l.clock_offset_ms.toFixed(0)} ms ±${fmt(l.clock_uncertainty_ms, 0)} ms [${l.clock_method}]`
      : NA + " [method: " + (l.clock_method || "none") + "]");
    setText("clock-note", l.clock_note || "");
    const inaReason = l.infer_na || NA;
    $("link-sim").hidden = !l.simulated;
    setText("frame-age", num(l.time_since_last_frame_ms) ? l.time_since_last_frame_ms.toFixed(0) + " ms" : inaReason);
    $("frame-age").title = l.time_since_last_frame_basis || "";
    setText("res-rate", num(l.results_rate_hz) ? l.results_rate_hz.toFixed(1) + " Hz" : inaReason);
    setText("subs", num(l.subscribers) ? String(l.subscribers) : inaReason);
    setText("res-total", num(l.results_total) ? String(l.results_total) : inaReason);
    setText("res-last", num(l.last_result_t)
      ? new Date(l.last_result_t * 1000).toLocaleTimeString() + " (" + Math.max(0, h.time - l.last_result_t).toFixed(1) + " s ago)"
      : (l.infer_na ? inaReason : "no result yet"));

    // infer
    const inf = h.infer;
    const st = h.infer_state || "NO DATA";
    const stLv = { RUNNING: "ok", STARTING: "warn", DEGRADED: "warn", ERROR: "crit" }[st] || "na";
    setBadge("infer-state", st, LV_TONE[stLv] || "neutral");
    $("infer-sim").hidden = !(inf && inf.simulated);
    setText("infer-reason", inf ? `Status age ${fmt(inf.age_s, 1, "s")}, version ${inf.version || NA}` : (h.infer_reason || ""));
    setText("set-infer-ver", inf ? (inf.version || NA) : NA + (h.infer_reason ? " (" + h.infer_reason + ")" : ""));
    $("infer-wait").hidden = !!inf;
    const box = $("infer-summary");
    if (!inf) { box.replaceChildren(); }
    else {
      const cs = inf.cameras_summary || {}, ms = inf.models_summary || {};
      const camRows = (cs.per_cam || []).map((c) => el("tr", null,
        td("Camera", null, "cam " + c.cam + (camText(c) ? " " + camText(c) : ""),
          c.cam_note ? el("span", { class: "muted small" }, " (" + c.cam_note + ")") : null),
        td("State", null, c.state || NA, " ", simBadge(c.simulated)),
        td("fps", { class: "n" }, fmt(c.fps, 1, "fps"))));
      const modRows = (ms.per_model || []).map((m) => el("tr", null,
        td("Model", null, m.name || NA), td("State", null, m.state || NA, " ", simBadge(m.simulated)),
        td("Latency", { class: "n" }, fmt(m.lat_total_p50_ms, 1, "ms p50"))));
      box.replaceChildren(
        el("h3", null, `Cameras (${cs.total || 0})`, " ", simBadge(cs.simulated)),
        el("div", { class: "da-table-wrap" }, el("table", { class: "da-table da-table--stack da-table--compact" }, el("tbody", null, ...camRows))),
        el("h3", null, `Models (${ms.total || 0})`, " ", simBadge(ms.simulated)),
        el("div", { class: "da-table-wrap" }, el("table", { class: "da-table da-table--stack da-table--compact" }, el("tbody", null, ...modRows))),
        ...((inf.errors || []).length ? [el("p", { class: "note lv-crit" }, "Errors: " + inf.errors.join("; "))] : []));
    }
    renderOverview();
  }

  let es = null, connT0 = 0, reconnectTimer = null;
  function setConn(text, on) {
    setText("conn", text, "conn " + (on ? "conn--on" : "conn--off"));
    setText("side-feed", on ? "Live" : text, "feed " + (on ? "feed--live" : "feed--stale"));
  }
  function markStale(on) {
    $("main").classList.toggle("stale", on);
    if (on) setBadge("node-state", "NO DATA", "neutral");
  }
  function reconnect(delay) {
    if (es) { es.close(); es = null; }
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, delay);
  }
  function connect() {
    reconnectTimer = null;
    connT0 = Date.now();
    es = new EventSource("/api/stream");
    es.onopen = () => { setConn("Connected", true); };
    es.onmessage = (ev) => {
      lastMsg = Date.now();
      try {
        const d = JSON.parse(ev.data);
        if (d.services) lastServices = d.services;
        if (d.cameras) setCameras(d.cameras);
        if (d.health) renderHealth(d.health);
        markStale(!!(d.health && d.health.stale));
        setConn("Connected", true);
      } catch (e) {
        console.error(e);
        setConn("Data error: " + e.message, false);
      }
    };
    // the server sends "event: fail" when it cannot make one document
    es.addEventListener("fail", (ev) => {
      let m = "server error";
      try { m = JSON.parse(ev.data).error || m; } catch (e) { /* keep default */ }
      setConn("Server error: " + m, false);
    });
    es.onerror = () => {
      setConn("Not connected. The page tries again.", false);
      // CLOSED (2): the browser does not try again by itself, so open a new stream
      if (es && es.readyState === 2) reconnect(3000);
    };
  }
  setInterval(() => {
    const now = Date.now();
    if (lastMsg && now - lastMsg > 3500) {
      setConn("No data for " + Math.round((now - lastMsg) / 1000) + " s", false);
      markStale(true);
    }
    // no message for 10 s since the last message or the last (re)connect, also when the TCP
    // connection stays open: open a new stream
    if (!reconnectTimer && now - Math.max(lastMsg, connT0) > 10000) reconnect(0);
  }, 1000);

  /* camera name / role text from the server (dashboard/infer_views.py camera_text): DA01 name and role; "role
     unconfirmed" only when DA01 has no role; cam_note "no camera info from DA01" when the text is the config one */
  function camText(c) { return (c && (c.cam_text != null ? c.cam_text : c.role)) || ""; }
  // the DA01 camera name for the model tables (short) and the camera picker (long: with the index), from
  // /api/cameras (via the SSE stream). Without DA01 info: "camN".
  function camName(n, long) {
    const c = camDoc && (camDoc.cameras || [])[n];
    const name = c && !c.cam_note && typeof c.name === "string" && c.name ? c.name : "";
    return name ? name + (long ? " (cam" + n + ")" : "") : "cam" + n;
  }
  const camList = (v) => (Array.isArray(v) ? v.filter((c) => Number.isInteger(c)) : []);
  const camNames = (l, long) => (l && l.length ? l.map((n) => camName(n, long)).join(", ") : "-");

  /* ---------------- cameras (six tiles) ---------------- */
  // serverOffset = server clock - page clock (s). Tiles are evaluated every 250 ms with the page
  // clock + serverOffset, so a tile changes to NO SIGNAL also between two SSE events. The server
  // sends an SSE event at once for each new agx-infer status. No status for 3 s -> NO DATA.
  let camDoc = null, serverOffset = 0;
  const tiles = [];
  const CAM_TONE = { "st-ok": "green", "st-sim": "info", "st-stale": "amber", "st-nosig": "red", "st-nodata": "neutral" };
  function buildTiles() {
    const box = $("cam-tiles");
    for (let n = 0; n < 6; n++) {
      const t = {
        state: el("span", { class: "da-badge", text: "NO DATA" }),
        sim: el("span", { class: "da-badge da-badge--info", text: "SIMULATED", hidden: "" }),
        role: el("span", { class: "muted small" }),
        img: el("img", { alt: "Camera " + n + " picture", width: "320", height: "180" }),
        over: el("span", { class: "over", text: "NO DATA" }),
        none: el("span", { class: "nopic", text: "No picture" }),
        fps: el("b"), rate: el("b"), lost: el("b"), dec: el("b"), age: el("b"),
        reason: el("div", { class: "note" }),
        err: el("div", { class: "note lv-warn", hidden: "" }),
        url: null, snapT: 0, busy: false,
      };
      const kv = (k, v) => el("div", { class: "row" }, el("span", { class: "k" }, k), v);
      t.root = el("div", { class: "da-tile cam-tile st-nodata", id: "cam-tile-" + n },
        el("div", { class: "da-tile__head" }, el("span", { class: "da-tile__title" }, "Camera " + n), t.role, el("span", { class: "sp" }), t.sim, t.state),
        el("div", { class: "snap" }, t.none, t.img, t.over),
        kv("Frames per second", t.fps), kv("Bit rate", t.rate), kv("Lost packets (frames)", t.lost),
        kv("Decode time p50", t.dec), kv("Frame age", t.age), t.reason, t.err);
      t.img.hidden = true;
      tiles.push(t);
      box.append(t.root);
    }
  }
  function setCameras(doc) {
    camDoc = doc;
    if (num(doc.server_t)) serverOffset = doc.server_t - Date.now() / 1000;
    const lim = $("cams-limits");
    if (num(doc.stale_s) && num(doc.no_signal_s)) {
      const hold = Math.min(num(doc.hold_s) ? doc.hold_s : 0, num(doc.hold_cap_s) ? doc.hold_cap_s : doc.no_signal_s + 0.5);
      const late = Math.max(doc.no_signal_s, hold) + 0.25;
      lim.textContent = `STALE: agx-infer gives a frame age of ${doc.stale_s} s or more. NO SIGNAL: no new frame for ${doc.no_signal_s} s. ` +
        `NO DATA: no status from agx-infer for ${fmt(doc.no_data_s, 0)} s. Limits from ${doc.limits_source || NA}. ` +
        `agx-infer sends its status each ${fmt(doc.status_period_s, 1, "s")}, thus this page shows NO SIGNAL ${fmt(doc.no_signal_s, 1, "s")} to ${fmt(late, 2, "s")} after the last frame.`;
    }
    setText("cams-note", doc.available ? "" : (doc.reason || ""));
    $("cams-sim").hidden = !doc.simulated;
    evalTiles();
  }
  function evalTiles() {
    if (!tiles.length) return;
    const nowS = Date.now() / 1000 + serverOffset;
    const cams = (camDoc && camDoc.cameras) || [];
    for (let n = 0; n < 6; n++) {
      const t = tiles[n], c = cams[n] || { cam: n };
      const r = T.tileState(c, nowS, camDoc);
      t.root.className = "da-tile cam-tile " + r.cls;
      t.state.textContent = r.state;
      t.state.className = "da-badge da-badge--" + (CAM_TONE[r.cls] || "neutral");
      t.over.textContent = r.state;
      t.sim.hidden = r.label !== "SIMULATED";
      t.role.textContent = camText(c) + (c.cam_note ? " (" + c.cam_note + ")" : "");
      const nd = r.state === "NO DATA";
      const nf = nd || r.state === "NO SIGNAL";  // no frame now: the rates of the last status are not current
      t.fps.textContent = nf ? NA : fmt(c.fps, 1);
      t.rate.textContent = nf ? NA : fmt(c.bitrate_kbps, 0, "kbit/s");
      t.lost.textContent = nd ? NA : (num(c.lost_packets) ? c.lost_packets : NA) + " (" + (num(c.lost_frames) ? c.lost_frames : NA) + ")";
      t.dec.textContent = nd ? NA : fmt(c.decode_p50_ms, 1, "ms");
      // OK / SIMULATED: the age that agx-infer measured; else the time since the newest known frame
      t.age.textContent = (r.state === "OK" || r.state === "SIMULATED") && num(c.frame_age_ms) ? c.frame_age_ms.toFixed(0) + " ms"
        : num(r.age_s) ? (r.age_s * 1000).toFixed(0) + " ms" : NA;
      // last ingest error of this camera (agx-infer status); not shown without a current status
      const ce = !nd && typeof c.last_error === "string" && c.last_error ? c.last_error : "";
      t.err.textContent = ce ? "Last error: " + ce : "";
      t.err.hidden = !ce;
      t.reason.textContent = nd ? ((camDoc && camDoc.reason) || "No status from agx-infer") : (r.state === "NO SIGNAL" || r.state === "STALE" ? (num(r.age_s) ? "Last frame " + r.age_s.toFixed(1) + " s ago." : "No frame received.") : "");
    }
  }
  async function loadSnap(n) {
    const t = tiles[n];
    const c = camDoc && camDoc.cameras && camDoc.cameras[n];
    if (t.busy || !c || !num(c.snapshot_t) || c.snapshot_t <= t.snapT) return;
    t.busy = true;
    // a request that does not finish must not stop the pictures of this tile: stop it after 3 s
    const ac = typeof AbortController === "function" ? new AbortController() : null;
    const tm = ac ? setTimeout(() => ac.abort(), 3000) : null;
    try {
      const r = await fetch("/api/cameras/" + n + "/snapshot.jpg?t=" + Date.now(),
        { cache: "no-store", credentials: "same-origin", signal: ac ? ac.signal : undefined });
      if (!r.ok) return;  // keep the last picture (dimmed by the tile state)
      const u = URL.createObjectURL(await r.blob());
      if (t.url) URL.revokeObjectURL(t.url);
      t.url = u; t.img.src = u; t.img.hidden = false; t.none.hidden = true;
      t.snapT = c.snapshot_t;
    } catch (e) { /* keep the last picture */ } finally { if (tm) clearTimeout(tm); t.busy = false; }
  }

  /* ---------------- Overview: banner + status tiles (SSE data and the slow catalog poll) ---------------- */
  function renderOverview() {
    const h = lastHealth;
    if (!h) return;
    setText("ov-sub", (h.node_name || h.hostname || "agx") + " · up " + fmtDur(h.uptime_s) + (h.nvpmodel && h.nvpmodel.mode ? " · power mode " + h.nvpmodel.mode : ""));
    const ns = (h.node_state || "NO DATA").toLowerCase();
    const light = LV_LIGHT[ns] || "unknown";
    const ban = $("ov-banner");
    ban.className = "banner" + (light !== "unknown" ? " banner--" + light : "");
    $("ov-light").replaceChildren(trafficLight(light, "lg", false));
    setText("ov-title", { green: "All areas are OK", amber: "Warning", red: "Fault", unknown: "Node state not known" }[light] +
      " (node state " + (h.node_state || "NO DATA") + ")");
    setText("ov-reasons", (h.node_state_reasons || []).join(" · ") || "No reason. Each measured value is in its limits.");

    const tilesOut = [];
    // cameras
    const nowS = Date.now() / 1000 + serverOffset;
    const cams = (camDoc && camDoc.cameras) || [];
    const cst = [0, 1, 2, 3, 4, 5].map((n) => T.tileState(cams[n] || { cam: n }, nowS, camDoc).state);
    const cnt = (s) => cst.filter((x) => x === s).length;
    const ok = cnt("OK") + cnt("SIMULATED");
    const camStatus = cnt("NO DATA") === 6 ? "unknown" : cnt("NO SIGNAL") ? "red" : cnt("STALE") || cnt("NO DATA") ? "amber" : "green";
    tilesOut.push(statusTile({ id: "ov-t-cams", title: "Cameras", status: camStatus, href: R.href("cameras"),
      figures: [{ label: "OK", value: ok + " / 6" }, { label: "Stale", value: String(cnt("STALE")) },
        { label: "No signal", value: String(cnt("NO SIGNAL") + cnt("NO DATA")) }],
      reasons: cst.map((s, n) => (s === "OK" || s === "SIMULATED" ? null : camName(n) + ": " + s)),
      footer: cnt("SIMULATED") ? "SIMULATED source" : null }));
    // models (catalog: slow poll on this page; agx-infer models: SSE)
    const ms = (h.infer && h.infer.models_summary) || null;
    const per = (ms && ms.per_model) || [];
    const running = per.filter((m) => m.state === "RUNNING").length;
    const infFailed = per.filter((m) => m.state === "FAILED").length;
    const cat = catalog;
    const counts = (cat && cat.counts) || {};
    const mode = ctlField("control_mode");
    const change = changeText(ctlField("change_in_progress"));
    const modelStatus = !ms && !cat ? "unknown" : infFailed ? "red" : (counts.FAILED || 0) > 0 ? "amber" : running || counts.ACTIVE ? "green" : "amber";
    tilesOut.push(statusTile({ id: "ov-t-models", title: "Models", status: modelStatus, href: R.href("models"),
      figures: [{ label: "Active", value: cat ? String(counts.ACTIVE || 0) : running + " running" },
        { label: "Ready", value: cat ? String(counts.READY || 0) : NA }, { label: "Failed", value: cat ? String(counts.FAILED || 0) : String(infFailed) }],
      reasons: [change ? "Change: " + change : null, mode === "vehicle" ? "Control mode vehicle: changes are refused" : null,
        catalogError ? "Catalog: " + catalogError : null,
        ...((cat && cat.entries) || []).filter((e) => e.state === "FAILED").map((e) => e.key + ": " + (e.reason || "FAILED"))],
      footer: mode ? "Control mode: " + mode : null }));
    // agx-infer
    const ist = h.infer_state || "NO DATA";
    const inf = h.infer;
    const inLight = { RUNNING: "green", STARTING: "amber", DEGRADED: "amber", ERROR: "red" }[ist] || "unknown";
    const csum = (inf && inf.cameras_summary) || null;
    tilesOut.push(statusTile({ id: "ov-t-infer", title: "agx-infer", status: inLight, href: R.href("services"),
      figures: [{ label: "State", value: ist }, { label: "Cameras OK", value: csum ? ((csum.states || {}).OK || 0) + " / " + (csum.total || 0) : NA },
        { label: "Status age", value: inf ? fmt(inf.age_s, 1, "s") : NA }],
      reasons: [inf ? null : h.infer_reason, ...((inf && inf.errors) || [])],
      footer: inf ? "Version " + (inf.version || NA) : null }));
    // RK link
    const l = h.link || {};
    const linkStatus = !num(l.ping_ms) ? (l.ping_error && l.ping_error !== "not measured yet" ? "red" : "unknown")
      : num(l.loss_pct) && l.loss_pct > 0 ? "amber" : "green";
    tilesOut.push(statusTile({ id: "ov-t-link", title: "RK link", status: linkStatus, href: R.href("rklink"), columns: 2,
      figures: [{ label: "Ping", value: fmt(l.ping_ms, 1, "ms") }, { label: "Packet loss", value: fmt(l.loss_pct, 0, "%") },
        { label: "Results/s", value: fmt(l.results_rate_hz, 1) }, { label: "Subscribers", value: num(l.subscribers) ? String(l.subscribers) : NA }],
      reasons: [num(l.ping_ms) ? null : l.ping_error, l.infer_na] }));
    // system
    const levels = [(h.ram || {}).level, (h.temps || {}).level];
    const worst = (lvs) => (lvs.includes("crit") ? "red" : lvs.includes("warn") ? "amber" : lvs.includes("ok") ? "green" : "unknown");
    const tm = h.temps || {};
    tilesOut.push(statusTile({ id: "ov-t-system", title: "System", status: worst(levels), href: R.href("system"),
      figures: [{ label: "CPU", value: fmt((h.cpu || {}).load_pct_avg, 0, "%") }, { label: "GPU", value: fmt((h.gpu || {}).load_pct, 0, "%") },
        { label: "Memory", value: fmt((h.ram || {}).pct, 0, "%") }, { label: "Hottest", value: fmt(tm.max_c, 1, "°C") },
        { label: "Power", value: fmt((h.power || {}).total_w, 1, "W") }, { label: "Swap", value: fmt((h.swap || {}).pct, 0, "%") }],
      reasons: [(h.ram || {}).level === "warn" || (h.ram || {}).level === "crit" ? "RAM " + fmt((h.ram || {}).pct, 1, "%") : null,
        tm.level === "warn" || tm.level === "crit" ? "Temperature " + fmt(tm.max_c, 1, "°C") + " (" + (tm.max_zone || NA) + ")" : null] }));
    // disks
    const disks = h.disk || [];
    tilesOut.push(statusTile({ id: "ov-t-disks", title: "Disks", status: worst(disks.map((d) => d.level)), href: R.href("system"),
      figures: disks.slice(0, 3).map((d) => ({ label: d.mount, value: fmt(d.pct, 0, "%") })),
      reasons: disks.filter((d) => d.level === "warn" || d.level === "crit").map((d) => d.mount + " " + fmt(d.pct, 1, "%") + " used") }));
    // services (SSE summary)
    const sv = lastServices;
    const user = (sv && sv.user) || {};
    const names = Object.keys(user);
    const act = names.filter((n) => /^active/.test(user[n] || "")).length;
    const failed = names.filter((n) => /^failed/.test(user[n] || "") || /^failed/.test(((sv && sv.system) || {})[n] || ""));
    const dk = (sv && sv.docker) || {};
    tilesOut.push(statusTile({ id: "ov-t-svc", title: "Services", status: !sv ? "unknown" : failed.length ? "red" : "green", href: R.href("services"),
      figures: [{ label: "agx units", value: sv ? act + " / " + names.length : NA }, { label: "Docker", value: dk.available ? (dk.running || 0) + " / " + (dk.total || 0) : NA },
        { label: "Old processes", value: sv && num(sv.old_processes) ? String(sv.old_processes) : NA }],
      reasons: [...failed.map((n) => n + " failed"), sv && sv.old_processes ? sv.old_processes + " old DriverAgent processes run" : null,
        dk.error ? "Docker: " + dk.error : null],
      footer: sv && sv.old_units ? "Old units: " + sv.old_units.active + " active / " + sv.old_units.total : null }));
    $("ov-tiles").replaceChildren(...tilesOut);
  }

  /* ---------------- models: catalog + /api/models + audit + control ---------------- */
  const STATE_TONE = { ACTIVE: "green", READY: "info", BUILDING: "info", "NEEDS BUILD": "amber", FAILED: "red",
    "NO ADAPTER": "muted", REGISTERED: "neutral" };
  const INFER_TONE = { RUNNING: "green", LOADED: "amber", LOADING: "amber", OFF: "muted", FAILED: "red" };
  const RESULT_TONE = { ok: "green", started: "info", refused: "amber", failed: "red" };
  let catalog = null, catalogError = "", modelsDoc = null, modelsError = "", control = null, events = null;
  const openDetails = {};             // key -> true: the rows with open details
  let notice = null;                  // {id, text, at}: the 202 message stays until the end of that change

  function fmtSize(b) {
    if (!num(b)) return NA;
    if (b >= 1048576) return (b / 1048576).toFixed(1) + " MiB";
    return (b / 1024).toFixed(0) + " KiB";
  }
  const shp = (t) => (t.name || "?") + " " + (Array.isArray(t.shape) ? "[" + t.shape.join("x") + "]" : "") + (t.dtype ? " " + t.dtype : "");
  function ioCell(ins, outs, label) {
    if (!(ins || []).length && !(outs || []).length) return td(label || "Inputs and outputs", { class: "muted" }, NA);
    return td(label || "Inputs and outputs", { class: "io" },
      el("div", null, el("span", { class: "k" }, "In: "), (ins || []).map(shp).join("; ") || NA),
      el("div", null, el("span", { class: "k" }, "Out: "), (outs || []).map(shp).join("; ") || NA));
  }
  // TensorRT match in a table cell: yes / no / n/a, the TensorRT version and a failed load. The TensorRT device
  // warning and the load messages are in the details only.
  function trtCell(m) {
    const txt = m.trt_match === true ? "yes" : m.trt_match === false ? "no" : NA;
    const cls = m.trt_match === true ? "lv-ok" : m.trt_match === false ? "lv-crit" : "muted";
    return td("TensorRT match", { title: m.trt_build_device ? "Build device: " + m.trt_build_device : null },
      el("span", { class: cls }, txt), m.trt_version ? el("span", { class: "muted" }, " TensorRT " + m.trt_version) : null,
      m.engine_load === "FAILED" ? el("div", { class: "lv-crit small" }, "Load FAILED" + (m.engine_error ? ": " + m.engine_error : "")) : null);
  }
  const p3 = (o) => o ? [o.p50, o.p95, o.p99].map((v) => fmt(v, 1)).join(" / ") : NA;
  const keyOf = (e) => (e && (e.key || (e.name + "@" + e.version))) || "";
  const changeText = (c) => (c && typeof c === "object" ? `${c.action || "change"} ${c.model || ""}`.trim() : c || "");
  const setList = (v) => (Array.isArray(v) ? v : v && Array.isArray(v.set) ? v.set : []);
  const real = (p) => String(p || "");
  // The control fields (mode, problem, change in progress, last change) are in the catalog AND in the control
  // document. Each page polls only one of them (Settings: control; Overview: catalog), so use the newer document.
  // Both have "t" (docs/MODEL_CONTROL_API.md).
  function ctlField(k) {
    const tc = catalog && num(catalog.t) ? catalog.t : -1, tk = control && num(control.t) ? control.t : -1;
    const a = catalog && control ? (tk > tc ? control : catalog) : catalog || control;
    if (!a) return null;
    if (a[k] !== undefined) return a[k];
    const b = a === catalog ? control : catalog;
    return b && b[k] !== undefined ? b[k] : null;
  }

  // Update a table body by row key. A row group (a row and its detail row) that did not change keeps its elements:
  // keyboard focus, a pressed button and a text selection stay. Only the changed groups are replaced. A group that
  // holds the text selection of the owner is not replaced until the selection goes. When a focused element is
  // replaced, the element with the same data-fid in the new group gets the focus.
  const rowCache = new WeakMap();   // tbody -> Map(key -> {sig, nodes})
  function syncRows(tb, groups) {
    const old = rowCache.get(tb) || new Map();
    const sel = window.getSelection ? window.getSelection() : null;
    const selNode = sel && !sel.isCollapsed ? sel.anchorNode : null;
    const af = document.activeElement;
    const fid = af && tb.contains(af) ? af.getAttribute("data-fid") : null;
    const next = new Map(), want = [];
    for (const g of groups) {
      let key = String(g.key);
      for (let i = 2; next.has(key); i++) key = g.key + "#" + i;   // the keys must be unique
      const sig = g.nodes.map((n) => n.outerHTML).join("");
      const o = old.get(key);
      const keep = o && o.nodes.every((n) => n.parentNode === tb) &&
        (o.sig === sig || (selNode && o.nodes.some((n) => n.contains(selNode))));
      const use = keep ? o : { sig, nodes: g.nodes };
      next.set(key, use);
      want.push(...use.nodes);
    }
    const keepSet = new Set(want);
    for (const n of [...tb.childNodes]) if (!keepSet.has(n)) tb.removeChild(n);
    let cur = tb.firstChild;
    for (const n of want) {
      if (cur === n) { cur = cur.nextSibling; continue; }
      tb.insertBefore(n, cur);
    }
    rowCache.set(tb, next);
    if (fid && document.activeElement !== af) {
      const n = [...tb.querySelectorAll("[data-fid]")].find((x) => x.getAttribute("data-fid") === fid);
      if (n) n.focus({ preventScroll: true });
    }
  }
  // While a mouse button or a finger is down on a Models table, the table does not change (else the button can go
  // between mousedown and mouseup and the click is lost). The render waits until the release.
  let tablePress = false, tablePending = false;
  for (const id of ["models-tbl", "extra-tbl"]) $(id).addEventListener("pointerdown", () => { tablePress = true; });
  const tableRelease = () => {
    if (!tablePress) return;
    tablePress = false;
    if (tablePending) { tablePending = false; setTimeout(renderModels, 0); }  // after the click event
  };
  window.addEventListener("pointerup", tableRelease);
  window.addEventListener("pointercancel", tableRelease);

  // Rows of the Models table: each catalog entry, joined with its /api/models row (the agx-infer and
  // config/models.yaml view: engine facts, latency per stage, errors, ...). An /api/models row without a catalog
  // entry is its own row ("not in the model store"), so that each value of /api/models stays on the page.
  function modelRows() {
    const entries = (catalog && catalog.entries) || [];
    const docs = (modelsDoc && modelsDoc.models) || [];
    const used = new Set();
    const rows = entries.map((e) => ({ key: keyOf(e), entry: e, doc: null }));
    docs.forEach((m, i) => {
      const same = rows.filter((r) => r.entry.name === m.name && !r.doc);
      const eng = (r) => r.entry.engine && (real(r.entry.engine.path) === real(m.engine) || real(r.entry.engine.path) === real(m.engine_realpath));
      const pick = same.find(eng) || (same.filter((r) => r.entry.state === "ACTIVE").length === 1 ? same.find((r) => r.entry.state === "ACTIVE") : null)
        || (same.length === 1 ? same[0] : null);
      if (pick) { pick.doc = m; used.add(i); }
    });
    docs.forEach((m, i) => { if (!used.has(i)) rows.push({ key: "infer:" + (m.name || i), entry: null, doc: m }); });
    return rows;
  }
  function canBuild(e) {
    if (!e) return false;
    if (e.state === "NEEDS BUILD") return true;
    const onnx = (e.files || []).some((f) => f.role === "onnx" && f.exists);
    return e.state === "FAILED" && onnx && (!e.engine || !e.engine.exists);
  }
  function actionButtons(e) {
    if (!e) return [el("span", { class: "muted" }, "-")];
    const out = [];
    const btn = (label, kind, primary) => {
      const b = el("button", { type: "button", class: "da-btn da-btn--sm" + (primary ? " da-btn--primary" : ""), "data-kind": kind, "data-key": keyOf(e),
        "data-fid": kind + ":" + keyOf(e) }, label);
      // the newest catalog entry of this key (a row that did not change keeps its button from an older poll)
      b.addEventListener("click", () => openDialog(kind, ((catalog && catalog.entries) || []).find((x) => keyOf(x) === keyOf(e)) || e));
      return b;
    };
    if (e.state === "ACTIVE") out.push(btn("Deactivate", "deactivate"));
    if (canBuild(e)) out.push(btn("Build", "build"));
    if (e.state === "READY" || e.state === "FAILED") out.push(btn("Activate", "activate", true));
    return out.length ? [el("span", { class: "actions" }, ...out)] : [el("span", { class: "muted" }, "-")];
  }
  function stateCell(r) {
    const e = r.entry, m = r.doc;
    if (e) {
      const why = e.reason || (e.live && e.live.error) || "";
      const job = e.job;
      return td("State", null, el("span", { class: "state-cell" }, badge(e.state || NA, STATE_TONE[e.state] || "neutral"),
        simBadge(m && m.simulated),
        why ? el("span", { class: "state-cell__reason muted small", title: why }, why) : null,
        job && (job.state === "queued" || job.state === "running") ? el("span", { class: "small" },
          "Build " + job.state + " · " + fmt(job.elapsed_s, 0, "s") + (job.progress ? " · " + job.progress : "")) : null));
    }
    const st = m.state || NA;
    return td("State", null, el("span", { class: "state-cell" }, badge(st, INFER_TONE[st] || "neutral"), simBadge(m.simulated),
      m.error ? el("span", { class: "lv-crit small" }, m.error) : null,
      m.reason ? el("span", { class: "state-cell__reason muted small" }, m.reason) : null));
  }
  function renderModels() {
    if (tablePress) { tablePending = true; return; }
    const tb = $("models-tbl").tBodies[0];
    const rows = modelRows();
    if (!rows.length) {
      syncRows(tb, [{ key: "", nodes: [emptyRow(8, catalogError && modelsError ? "No model data: " + catalogError : "No model in the store and no model in agx-infer.")] }]);
    } else {
      const out = [];
      for (const r of rows) {
        const e = r.entry, m = r.doc;
        const live = (e && e.live) || null;
        const open = !!openDetails[r.key];
        const cams = e ? (e.state === "ACTIVE" && live ? camList(live.cameras) : camList(e.cameras_default)) : camList(m.cameras);
        const fps = live && num(live.fps) ? live.fps : m ? m.fps : null;
        const lat = live && live.latency_ms ? live.latency_ms : m && m.lat_ms ? m.lat_ms.total : null;
        const db = el("button", { type: "button", class: "details-btn", "aria-expanded": String(open), title: open ? "Hide the details" : "Show the details",
          "data-fid": "details:" + r.key }, el("code", null, (e ? e.name : m.name) || NA));
        db.addEventListener("click", () => { openDetails[r.key] = !openDetails[r.key]; renderModels(); });
        const g = { key: r.key, nodes: [] };
        out.push(g);
        g.nodes.push(el("tr", { class: open ? "has-detail" : null, "data-key": r.key },
          td("Name", null, db, e ? null : el("div", { class: "muted small" }, "Not in the model store")),
          td("Version", null, e ? e.version || NA : NA),
          td("Type", { class: "type-cell" }, e ? e.type || NA : (m.adapter || NA)),
          stateCell(r),
          td("Cameras", { class: "cams-cell", title: camNames(cams, true) }, camNames(cams)),
          td("Results/s", { class: "n" }, fmt(fps, 1)),
          td("Latency p50 / p95 / p99", { class: "num" }, lat ? p3(lat) + " ms" : NA),
          td("Actions", null, ...actionButtons(e))));
        if (open) g.nodes.push(el("tr", { class: "detail" }, el("td", { colspan: "8" }, modelDetails(e, m))));
      }
      syncRows(tb, out);
    }
    const ex = (modelsDoc && modelsDoc.engines_not_in_config) || [];
    setText("extra-sum", "(" + ex.length + ")");
    const xo = [];
    ex.forEach((x, i) => {
      const k = "extra:" + (x.engine_realpath || x.engine || i);
      const open = !!openDetails[k];
      const db = el("button", { type: "button", class: "details-btn", "aria-expanded": String(open), title: x.engine_realpath || null,
        "data-fid": "details:" + k }, x.engine_file || x.engine_realpath || x.engine || NA);
      db.addEventListener("click", () => { openDetails[k] = !openDetails[k]; renderModels(); });
      const g = { key: k, nodes: [] };
      xo.push(g);
      g.nodes.push(el("tr", { class: open ? "has-detail" : null },
        td("Engine file", null, db), td("Size", { class: "n" }, fmtSize(x.size_bytes)), td("Date", null, x.mtime || NA),
        td("sha256 (16)", { class: "mono" }, x.sha256_16 || NA), trtCell(x), ioCell(x.inputs, x.outputs)));
      if (open) g.nodes.push(el("tr", { class: "detail" }, el("td", { colspan: "6" }, el("div", { class: "mdet" }, engineSection(x, "Engine file")))));
    });
    syncRows($("extra-tbl").tBodies[0], xo.length ? xo : [{ key: "", nodes: [emptyRow(6, modelsDoc ? "No other engine file found." : (modelsError || "Loading"))] }]);
  }

  /* == model details: the ONLY code path that shows the TensorRT device warning (owner rule: only when the owner
        opens the details of a model). Every value of the old Models table and its detail row is here. == */
  function engineSection(m, title) {
    const dw = m.trt_device_warning || null;
    const w = (m.load_warnings || []).filter((x) => x !== dw);
    const trt = (m.trt_match === true ? "yes" : m.trt_match === false ? "no" : NA) + (m.trt_version ? ", TensorRT " + m.trt_version : "");
    return el("section", null, el("h4", null, title || "Engine (agx-infer and config/models.yaml)"), kvList([
      ["Engine file", m.engine_file || "no engine file", m.engine_realpath],
      m.engine && !m.engine_exists ? ["File", el("span", { class: "lv-crit" }, "File not found")] : null,
      ["Path", m.engine_realpath || m.engine || NA],
      ["Size", fmtSize(m.size_bytes)],
      ["Date", m.mtime || NA],
      ["sha256 (16)", el("span", { class: "mono" }, m.sha256_16 || NA)],
      ["TensorRT match", trt],
      ["Build device", m.trt_build_device || NA],
      ["Engine load", m.engine_load === "FAILED" ? el("span", { class: "lv-crit" }, "Load FAILED" + (m.engine_error ? ": " + m.engine_error : "")) : (m.engine_load || NA)],
      m.engine_error && m.engine_load !== "FAILED" ? ["Engine note", m.engine_error] : null,
      m.engine_note ? ["Scan note", m.engine_note] : null,
      ["Device warning (information only)", dw ? el("span", { class: "muted" }, dw) : "none"],
      ["Load messages (" + w.length + ")", w.length ? el("span", { class: "lv-warn" }, w.join(" | ")) : "none"],
      num(m.device_memory_bytes) ? ["Device memory (engine)", fmtSize(m.device_memory_bytes)] : null,
      ["Inputs", (m.inputs || []).map(shp).join("; ") || NA],
      ["Outputs", (m.outputs || []).map(shp).join("; ") || NA],
    ]));
  }
  function inferSection(m) {
    const lat = m.lat_ms || {};
    return el("section", null, el("h4", null, "agx-infer"), kvList([
      ["State", el("span", null, badge(m.state || NA, INFER_TONE[m.state] || "neutral"), " ", simBadge(m.simulated))],
      ["In config/models.yaml", m.in_config ? "yes" + (m.enabled ? "" : " (disabled)") : el("span", { class: "lv-warn" }, "Not in config/models.yaml")],
      m.group ? ["Group", m.group] : null,
      m.adapter ? ["Adapter", m.adapter] : null,
      ["Error", m.error ? el("span", { class: "lv-crit" }, m.error) : "none"],
      ["Last error", m.last_error ? el("span", { class: "lv-warn" }, (num(m.last_error_t) ? new Date(m.last_error_t * 1000).toLocaleTimeString() + ": " : "") + m.last_error) : "none"],
      ["Errors", num(m.errors_total) ? String(m.errors_total) : NA],
      ["Automatic restarts", num(m.auto_restarts) ? String(m.auto_restarts) : NA],
      m.reason ? ["Reason", m.reason] : null,
      ["Cameras", camNames(camList(m.cameras))],
      ["fps", fmt(m.fps, 1)],
      ["Latency p50 / p95 / p99 (ms)", p3(lat.total)],
      ["Per stage p50 / p95 / p99 (ms)", "pre " + p3(lat.pre) + ", infer " + p3(lat.infer) + ", post " + p3(lat.post)],
      ["Queue wait p50 / p95 / p99 (ms)", m.queue_ms ? p3(m.queue_ms) : NA],
      ["GPU memory (estimate)", num(m.gpu_mem_mb) ? m.gpu_mem_mb.toFixed(0) + " MB (estimate)" : NA + " (estimate)", m.gpu_mem_note || "estimate"],
      ["Results", num(m.results_total) ? String(m.results_total) : NA],
      m.engine_version ? ["Engine version", el("span", { class: "mono" }, m.engine_version)] : null,
    ]));
  }
  function manifestSection(e) {
    const inp = e.input || {};
    const size = inp.size ? (inp.size.width + " x " + inp.size.height) : null;
    return el("section", null, el("h4", null, "Manifest"), kvList([
      ["Key", el("span", { class: "mono" }, keyOf(e))],
      ["Description", e.description || NA],
      ["Type", e.type || NA],
      ["Adapter", e.adapter || NA],
      ["Precision", e.precision || NA],
      ["Date", e.date || NA],
      ["Output kinds", (e.output_kinds || []).join(", ") || NA],
      ["Cameras permitted", camNames(camList(e.cameras_permitted))],
      ["Cameras default", camNames(camList(e.cameras_default))],
      size ? ["Input size", size + (inp.colour_order ? ", " + inp.colour_order : "")] : null,
      ["Input tensors", (e.input_tensors || []).map(shp).join("; ") || NA],
      ["Output tensors", (e.output_tensors || []).map(shp).join("; ") || NA],
      e.runtime ? ["Runtime", Object.entries(e.runtime).map(([k, v]) => k + " " + v).join(", ")] : null,
      ["Notes", e.notes || NA],
      ["Folder", el("span", { class: "mono" }, e.folder || NA)],
      (e.manifest_errors || []).length ? ["Manifest errors", el("span", { class: "lv-crit" }, e.manifest_errors.join("; "))] : null,
      e.engine ? ["Engine in the store", el("span", { class: "mono" }, e.engine.path || NA),
        (e.engine.built ? "built on this AGX" : "from the manifest") + (e.engine.exists ? "" : ", file missing")] : null,
    ]));
  }
  function filesSection(e) {
    const files = e.files || [];
    return el("section", { class: "wide" }, el("h4", null, "Files (" + files.length + ")"),
      el("div", { class: "da-table-wrap" }, el("table", { class: "da-table da-table--stack da-table--compact" },
        el("thead", null, el("tr", null, el("th", null, "Role"), el("th", null, "Path"), el("th", null, "sha256"), el("th", null, "File"))),
        el("tbody", null, ...(files.length ? files.map((f) => el("tr", null, td("Role", null, f.role || NA),
          td("Path", { class: "cmd" }, f.path || NA), td("sha256", { class: "cmd" }, f.sha256 || NA),
          td("File", { class: f.exists ? "lv-ok" : "lv-crit" }, f.exists ? "exists" : "missing"))) : [emptyRow(4, "No file in the manifest.")])))));
  }
  function checkSection(e) {
    const c = e.check;
    if (!c) return el("section", null, el("h4", null, "Check"), kvList([["Result", catalog && catalog.check_running === keyOf(e) ? "checks running now" : "not done yet"]]));
    const rs = c.result_summary || null;
    return el("section", null, el("h4", null, "Check"), kvList([
      ["Result", c.ok ? el("span", { class: "lv-ok" }, "passed") : el("span", { class: "lv-crit" }, "failed" + (c.reason ? ": " + c.reason : ""))],
      ["Time", fmtDateTime(c.t) + (num(c.duration_s) ? " (" + c.duration_s.toFixed(1) + " s)" : "")],
      ["TensorRT", (c.trt_version || NA) + ", match " + (c.trt_match === true ? "yes" : c.trt_match === false ? "no" : NA)],
      ["Build device", c.trt_build_device || NA],
      ["Device warning (information only)", c.trt_device_warning ? el("span", { class: "muted" }, c.trt_device_warning) : "none"],
      ["GPU memory need / free", fmt(c.gpu_need_mb, 0, "MB") + " / " + fmt(c.gpu_free_mb, 0, "MB")],
      ["Inference time", fmt(c.inference_ms, 1, "ms")],
      rs ? ["Test result", Object.entries(rs).map(([k, v]) => k + " " + (Array.isArray(v) ? v.join(", ") : v == null ? NA : v)).join("; ")] : null,
      c.engine_sha256 ? ["Engine sha256", el("span", { class: "mono" }, c.engine_sha256)] : null,
      ...(c.checks || []).map((x) => [x.name || NA, el("span", { class: x.ok ? "lv-ok" : "lv-crit" }, (x.ok ? "ok" : "failed") + (x.detail ? ": " + x.detail : ""))]),
    ]));
  }
  function liveSection(e) {
    const l = e.live;
    if (!l) return null;
    const lat = l.latency_ms || {};
    return el("section", null, el("h4", null, "Live (catalog)"), kvList([
      ["State", l.state || NA],
      l.error ? ["Error", el("span", { class: "lv-crit" }, l.error)] : null,
      ["Cameras", camNames(camList(l.cameras))],
      ["Results/s", fmt(l.fps, 1)],
      ["Latency p50 / p95 / p99 (ms)", p3(lat)],
      ["Results", num(l.results_total) ? String(l.results_total) : NA],
      ["GPU memory (estimate)", num(l.gpu_mem_mb) ? l.gpu_mem_mb.toFixed(0) + " MB (estimate)" : NA],
      l.engine_version ? ["Engine version", el("span", { class: "mono" }, l.engine_version)] : null,
      ["TensorRT match", l.trt_match === true ? "yes" : l.trt_match === false ? "no" : NA],
      ["Device warning (information only)", l.trt_device_warning ? el("span", { class: "muted" }, l.trt_device_warning) : "none"],
    ]));
  }
  function jobSection(e) {
    const j = e.job, f = e.failure;
    if (!j && !f) return null;
    return el("section", null, el("h4", null, "Build job and failures"), kvList([
      j ? ["Build", (j.state || NA) + ", " + fmt(j.elapsed_s, 0, "s")] : null,
      j ? ["Started / ended", fmtDateTime(j.started) + " / " + (num(j.ended) ? fmtDateTime(j.ended) : "-")] : null,
      j ? ["Progress", j.progress || NA] : null,
      j && j.error ? ["Build error", el("span", { class: "lv-crit" }, j.error)] : null,
      j && j.engine ? ["Engine", el("span", { class: "mono" }, j.engine)] : null,
      j && j.engine_sha256 ? ["Engine sha256", el("span", { class: "mono" }, j.engine_sha256)] : null,
      j && j.log ? ["Build log", el("span", { class: "mono" }, j.log)] : null,
      j && j.warning ? ["Build warning", j.warning] : null,
      f ? ["Watchdog failure", el("span", { class: "lv-crit" }, (f.reason || NA) + " (" + fmtTime(f.t) + ")")] : null,
    ]));
  }
  function modelDetails(e, m) {
    return el("div", { class: "mdet" }, m ? engineSection(m) : null, m ? inferSection(m) : null,
      e ? manifestSection(e) : null, e ? checkSection(e) : null, e ? liveSection(e) : null, e ? jobSection(e) : null,
      e ? filesSection(e) : null);
  }
  /* == end of the model details == */

  function renderModelHead() {
    const c = catalog;
    const mode = ctlField("control_mode");
    const modeBadge = (id) => (mode === "bench" ? setBadge(id, "Bench", "green") : mode === "vehicle"
      ? setBadge(id, "Vehicle: changes are refused", "amber") : setBadge(id, "Not known", "muted"));
    modeBadge("mc-mode"); modeBadge("set-mode");
    const problem = ctlField("control_problem") || "";
    $("mc-problem").hidden = !problem; $("mc-problem").textContent = problem ? "Control file of this AGX: " + problem : "";
    $("set-mode-problem").hidden = !problem; $("set-mode-problem").textContent = problem;
    if (control && control.control_file) setText("set-mode-file", control.control_file);
    const ch = ctlField("change_in_progress");
    $("mc-change").hidden = !ch;
    if (ch) $("mc-change").textContent = "Change: " + changeText(ch) + (ch && ch.t ? " since " + fmtTime(ch.t) : "") +
      (ch && ch.source ? " (" + ch.source + (ch.user ? ", " + ch.user : "") + ")" : "");
    const last = ctlField("last_change");
    const lb = $("mc-last");
    lb.hidden = !last;
    if (last) lb.replaceChildren(el("span", { class: "muted" }, "Last change"), badge(last.result || NA, RESULT_TONE[last.result] || "neutral"),
      el("span", null, changeText(last) + (last.reason ? ": " + last.reason : "")),
      el("span", { class: "muted" }, fmtDateTime(last.ended || last.t) + (last.user ? " · " + last.user : "") + (last.source ? " (" + last.source + ")" : "")));
    if (notice && ((notice.id && last && last.id === notice.id) || Date.now() - notice.at > 180000)) notice = null;
    $("mc-notice").hidden = !notice; $("mc-notice").textContent = notice ? notice.text : "";
    const err = [catalogError ? "Model catalog: " + catalogError : "", modelsError ? "Models: " + modelsError : ""].filter(Boolean).join(" ");
    $("mc-error").hidden = !err; $("mc-error").textContent = err;
    if (c) {
      const cn = c.counts || {};
      setText("mc-counts", Object.keys(cn).filter((k) => cn[k]).map((k) => cn[k] + " " + k).join(" · ") || "no model version in the store");
      setText("mc-checks", (c.check_running ? "Checks run now: " + c.check_running + ". " : "") +
        ((c.check_queued || []).length ? "Checks queued: " + c.check_queued.join(", ") + ". " : "") +
        "Store: " + (c.store || NA) + (c.store_exists === false ? " (missing)" : "") + ".");
    }
    if (modelsDoc) {
      setText("models-reason", modelsDoc.available ? "" : "agx-infer gives no status: " + (modelsDoc.reason || NA) + ". Live values show n/a.");
      $("models-sim").hidden = !modelsDoc.simulated;
      setText("models-note", modelsDoc.config_error ? modelsDoc.config_error : "");
      setText("models-gpu-note", modelsDoc.gpu_mem_note || "GPU memory values are an estimate (engine file + activation + I/O).");
      const sc = modelsDoc.engine_scan || {};
      setText("scan-note", "Engine scan: " + (num(sc.t) ? new Date(sc.t * 1000).toLocaleString() : "not done yet") +
        (sc.running ? " (scan runs now)" : "") + ", " + (sc.count || 0) + " engine files in " + (sc.dirs || []).join(", ") +
        ". Scan interval " + fmt((sc.interval_s || 0) / 60, 0, "min") + "." + (sc.error ? " Error: " + sc.error : "") +
        " " + (modelsDoc.gpu_mem_note || ""));
    }
  }
  async function fetchCatalog() {
    try { catalog = await getJSON("/api/models/catalog"); catalogError = ""; } catch (e) { catalogError = e.message; }
  }
  async function fetchModels() {
    try { modelsDoc = await getJSON("/api/models"); modelsError = ""; } catch (e) { modelsError = "Cannot read models: " + e.message; setText("models-reason", modelsError); }
  }
  function afterModelData() {
    renderModelHead();
    if (currentPage === "models") renderModels();
    else renderOverview();
  }
  async function loadCatalog() { await fetchCatalog(); afterModelData(); }
  async function loadModels() { await fetchModels(); afterModelData(); }
  // the Models page polls the catalog and /api/models with the same period: one render for the two answers
  async function loadCatalogAndModels() { await Promise.all([fetchCatalog(), fetchModels()]); afterModelData(); }
  let controlError = "";
  async function loadControl() {
    try { control = await getJSON("/api/models/control"); controlError = ""; } catch (e) { controlError = e.message; /* the catalog has the same mode */ }
    renderModelHead();
  }
  async function loadEvents() {
    try {
      events = await getJSON("/api/models/events?limit=50");
      setText("mc-events-note", "");
    } catch (e) { setText("mc-events-note", "Cannot read the audit list: " + e.message); return; }
    const ev = events.events || [];
    syncRows($("models-events").tBodies[0], (ev.length ? ev.map((x, i) => ({ key: x.change_id ? x.change_id + ":" + x.result + ":" + x.t : "i" + i, nodes: [el("tr", null,
      // browser time, as every other time on this page; the AGX clock text is in the tooltip
      td("Time", { class: "nowrap", title: x.time ? "AGX clock: " + x.time : null }, num(x.t) ? fmtDateTime(x.t) : (x.time || NA)),
      td("Source", null, x.source || NA),
      td("User", null, x.user || NA),
      td("Action", null, el("span", { class: "tag" }, x.action || NA), Array.isArray(x.cameras) ? el("div", { class: "muted small" }, "cameras " + x.cameras.join(", ")) : null),
      td("Model", null, x.model ? x.model + (x.version ? "@" + x.version : "") : "-"),
      td("Result", null, badge(x.result || NA, RESULT_TONE[x.result] || "neutral")),
      td("Reason", { class: "small reason-cell" }, x.reason || "-"))] })) : [{ key: "", nodes: [emptyRow(7, "No event yet.")] }]));
  }

  /* ---------------- the ONE write function + model control confirmation dialog ---------------- */
  // The ONLY write request of this page: a POST to the model controller (/api/models/{name}/{version}/{action},
  // /api/models/rollback; docs/MODEL_CONTROL_API.md) or to the pairing API (/api/pair/code, /api/pair/settings,
  // /api/pair/boards/{id}/remove; docs/PAIRING_API.md). The browser sends its Basic auth; X-AGX-CSRF: 1 is required.
  const WRITE_PREFIXES = ["/api/models/", "/api/pair/"];
  async function postWrite(path, body) {
    if (!WRITE_PREFIXES.some((p) => path.startsWith(p))) throw new Error("not a write path of this page: " + path);
    const r = await fetch(path, {
      method: "POST", cache: "no-store", credentials: "same-origin",
      headers: { "X-AGX-CSRF": "1", "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await r.text();
    let doc = null;
    try { doc = JSON.parse(text); } catch (e) { doc = null; }
    return { status: r.status, accepted: r.status === 202 || (r.ok && !!(doc && doc.ok)), doc, text };
  }
  function refusalText(res) {
    // the refusal reason of the AGX as it is
    return res.doc && res.doc.reason ? res.doc.reason : "HTTP " + res.status + (res.text ? ": " + res.text.slice(0, 300) : "");
  }
  let dlg = null, dlgBusy = false;
  const DLG_TITLE = { build: "Build", activate: "Activate", deactivate: "Deactivate", rollback: "Rollback" };
  function openDialog(kind, e) {
    dlg = { kind, entry: e || null };
    const key = e ? keyOf(e) : "";
    setText("mc-dlg-title", DLG_TITLE[kind] + (key ? " " + key : ""));
    const ok = $("mc-dlg-ok");
    ok.textContent = DLG_TITLE[kind];
    ok.className = "da-btn " + (kind === "deactivate" || kind === "rollback" ? "da-btn--danger" : "da-btn--primary");
    const body = $("mc-dlg-body");
    const camBox = $("mc-dlg-cams");
    camBox.hidden = kind !== "activate";
    if (kind === "build") {
      body.replaceChildren(el("p", null, "This AGX builds an engine for ", el("code", null, key), " from its ONNX file."),
        el("p", { class: "callout callout--amber" }, (catalog && catalog.build_warning) || "A build uses the GPU and the CPU for some minutes."));
    } else if (kind === "activate") {
      const permitted = camList(e.cameras_permitted);
      const def = camList(e.cameras_default).filter((c) => permitted.includes(c));
      body.replaceChildren(el("p", null, "This AGX loads ", el("code", null, key), " on the selected cameras. The other active models continue."));
      $("mc-dlg-camlist").replaceChildren(...(permitted.length ? permitted.map((c) => {
        const cb = el("input", { type: "checkbox", value: String(c), checked: def.includes(c) ? "" : null });
        cb.addEventListener("change", dlgValidate);
        return el("label", { class: "check" }, cb, camName(c, true));
      }) : [el("span", { class: "muted small" }, "The manifest permits no camera.")]));
    } else if (kind === "deactivate") {
      body.replaceChildren(el("p", null, "This AGX stops ", el("code", null, key), ". The other models continue."));
    } else {
      rollbackBody(false);
      if (!control) {
        // one GET of the control document for this dialog; then only the body text changes (no new openDialog,
        // so a refusal reason in #mc-dlg-error stays)
        const mine = dlg;
        loadControl().then(() => { if (dlg === mine) rollbackBody(true); });
      }
    }
    dlgError("");
    dlgValidate();
    const d = $("mc-dlg");
    if (!d.open) { if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", ""); }
  }
  function rollbackBody(loaded) {
    const lg = setList(control && control.last_good_set);
    const why = !control && loaded && controlError ? " (cannot read /api/models/control: " + controlError + ")" : "";
    $("mc-dlg-body").replaceChildren(el("p", null, "This AGX puts the last good set back: " +
      (lg.length ? lg.map((s) => s.name + "@" + s.version + " on " + camNames(camList(s.cameras), true)).join("; ")
        : (control || loaded ? "not known on this page" : "reading the last good set")) + why + "."));
  }
  function dlgCams() { return [...document.querySelectorAll("#mc-dlg-camlist input:checked")].map((x) => Number(x.value)).sort((a, b) => a - b); }
  function dlgValidate() {
    const noCam = dlg && dlg.kind === "activate" && !dlgCams().length;
    $("mc-dlg-ok").disabled = dlgBusy || noCam;
    $("mc-dlg-cancel").disabled = dlgBusy;
    if (noCam && !dlgBusy) dlgError("Select one camera or more.");
    else if ($("mc-dlg-error").textContent === "Select one camera or more.") dlgError("");
  }
  function dlgError(t) { const e = $("mc-dlg-error"); e.textContent = t; e.hidden = !t; }
  function closeDialog() {
    if (dlgBusy) return;
    dlg = null;
    const d = $("mc-dlg");
    if (d.open) { if (typeof d.close === "function") d.close(); else d.removeAttribute("open"); }
  }
  $("mc-dlg-cancel").addEventListener("click", closeDialog);
  $("mc-dlg").addEventListener("cancel", (ev) => { ev.preventDefault(); closeDialog(); });
  $("mc-dlg-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!dlg || dlgBusy) return;
    const { kind, entry } = dlg;
    const path = kind === "rollback" ? "rollback"
      : encodeURIComponent(entry.name) + "/" + encodeURIComponent(entry.version) + "/" + kind;
    const body = kind === "activate" ? { cameras: dlgCams() } : null;
    dlgBusy = true; dlgError(""); $("mc-dlg-ok").textContent = "Working"; dlgValidate();
    try {
      const res = await postWrite("/api/models/" + path, body);
      dlgBusy = false;
      if (res.accepted) {
        const ch = (res.doc && res.doc.change) || {};
        notice = { id: ch.id || null, at: Date.now(),
          text: "This AGX started the change: " + DLG_TITLE[kind].toLowerCase() + (entry ? " " + keyOf(entry) : "") + "." +
            (res.doc && res.doc.warning ? " " + res.doc.warning : "") };
        closeDialog();
        renderModelHead();
        loadCatalog(); loadEvents(); loadControl();
      } else {
        dlgError(refusalText(res));
        $("mc-dlg-ok").textContent = DLG_TITLE[kind];
        dlgValidate();
        loadEvents();
      }
    } catch (e) {
      dlgBusy = false;
      dlgError("The request did not complete: " + e.message);
      $("mc-dlg-ok").textContent = DLG_TITLE[kind];
      dlgValidate();
    }
  });
  $("mc-rollback").addEventListener("click", () => openDialog("rollback"));

  /* ---------------- services ---------------- */
  function memTxt(m) { return num(m) ? m.toFixed(0) + " MB" : "-"; }
  async function loadServices() {
    try {
      const d = await getJSON("/api/services");
      const u = d.units || {};
      const sys = Object.fromEntries((u.system || []).map((x) => [x.name, x]));
      fill($("agx-tbl").tBodies[0], (u.user || []).map((x) => {
        const s = sys[x.name] || {};
        const act = (v) => (v.active_state === "active" ? "lv-ok" : v.active_state === "failed" ? "lv-crit" : "muted");
        // take the values from the manager that has the unit loaded (user first)
        const m = x.load_state === "loaded" ? x : s.load_state === "loaded" ? s : null;
        return el("tr", null, td("Unit", null, x.name),
          td("User manager", { class: act(x) }, x.state), td("System manager", { class: act(s) }, s.state || NA),
          td("PID", { class: "n" }, (m && m.main_pid) || "-"),
          td("Restarts", { class: "n" }, m && num(m.n_restarts) ? m.n_restarts : "-"),
          td("Memory", { class: "n" }, memTxt(m ? m.memory_mb : null)));
      }));
      const dk = d.docker || {};
      const cont = dk.containers || [];
      setText("docker-sum", dk.available ? `${cont.filter((c) => c.state === "running").length} running / ${cont.length}` : "(" + (dk.error || NA) + ")");
      fill($("docker-tbl").tBodies[0], cont.map((c) => el("tr", null,
        td("Name", null, c.name || c.id), td("State", { class: c.state === "running" ? "lv-ok" : "muted" }, c.state || NA),
        td("Status", null, c.status || ""), td("Restart policy", null, c.restart_policy || NA), td("Image", null, c.image || ""))));
      const old = u.old || [];
      setText("old-sum", `${old.filter((x) => x.active_state === "active").length} active / ${old.length}`);
      fill($("old-tbl").tBodies[0], old.map((x) => el("tr", null,
        td("Unit", null, x.name),
        td("State", { class: x.active_state === "active" ? "lv-ok" : x.active_state === "failed" ? "lv-crit" : "muted" }, x.state),
        td("Unit file", null, x.unit_file_state || "-"), td("PID", { class: "n" }, x.main_pid || "-"),
        td("Memory", { class: "n" }, memTxt(x.memory_mb)))));
      const op = d.old_processes || {};
      const ps = op.processes || [];
      setText("oldp-sum", op.error ? "(" + op.error + ")" : ps.length ? "(" + ps.length + " running)" : "(none running)");
      if (op.note) setText("oldp-note", op.note);
      fill($("oldp-tbl").tBodies[0], ps.length ? ps.map((x) => el("tr", null,
        td("PID", { class: "n" }, x.pid), td("User", null, x.user || NA), td("Match", null, x.match || ""),
        td("Command line", { class: "cmd" }, x.cmdline || ""))) : [emptyRow(4, "none running")]);
      setText("svc-err", (u.errors || []).join("; "));
    } catch (e) { setText("svc-err", "Cannot read services: " + e.message); }
  }

  /* ---------------- logs (poll only while the Services page shows and the logs are open) ---------------- */
  let logsTimer = null;
  async function loadLogs() {
    const unit = $("logs-unit").value;
    try {
      const d = await getJSON("/api/services/logs?unit=" + encodeURIComponent(unit));
      $("logs").textContent = d.lines && d.lines.length ? d.lines.join("\n") : "No log lines for " + unit + "." + (d.error ? " " + d.error : "");
      setText("logs-t", "Updated " + new Date(d.t * 1000).toLocaleTimeString() +
        (d.source ? (d.source === "system" ? " (system unit)" : " (user unit)") : ""));
    } catch (e) { $("logs").textContent = "Cannot read logs: " + e.message; }
  }
  function syncLogs() {
    const want = R.logsWanted(currentPage, $("logs-det").open);
    if (want && !logsTimer) { loadLogs(); logsTimer = setInterval(loadLogs, R.LOGS_MS); }
    if (!want && logsTimer) { clearInterval(logsTimer); logsTimer = null; }
  }
  $("logs-det").addEventListener("toggle", syncLogs);
  $("logs-unit").addEventListener("change", () => { if (logsTimer) loadLogs(); });

  /* ---------------- history charts ---------------- */
  const SERIES_VARS = ["--da-chart-1", "--da-chart-2", "--da-chart-3", "--da-chart-4", "--da-green", "--da-red", "--da-amber", "--da-muted"];
  const CHARTS = [
    { id: "ch-load", pick: () => [["gpu_load_pct", "GPU"], ["cpu_load_avg_pct", "CPU avg"]], range: [0, 100] },
    { id: "ch-ram", pick: () => [["ram_used_pct", "RAM"]], range: [0, 100] },
    { id: "ch-temp", pick: () => [["temp_max_c", "Max"]] },
    { id: "ch-power", pick: () => [["power_total_w", "Total"]] },
    { id: "ch-fps", infer: true, pick: (names) => names.filter((n) => n.startsWith("fps.") || n.startsWith("sim_fps.")).sort().map((n) => [n, n.startsWith("sim_") ? n.slice(8) + " SIMULATED" : n.slice(4)]) },
    { id: "ch-lat", infer: true, pick: (names) => names.filter((n) => n.startsWith("lat_p50.") || n.startsWith("sim_lat_p50.")).sort().map((n) => [n, n.startsWith("sim_") ? n.slice(12) + " SIMULATED" : n.slice(8)]) },
  ];
  let plots = {};  // id -> {u, key}
  let range = "1h";
  let histTimer = null, lastHist = null;

  function axisOpts() {
    const common = { stroke: cssVar("--da-muted"), grid: { stroke: cssVar("--da-grid"), width: 1 }, ticks: { stroke: cssVar("--da-border"), width: 1 } };
    return [common, Object.assign({}, common, { size: 48 })];
  }
  function plotWidth(box) { return Math.max(200, box.clientWidth); }
  function drawChart(cfg, data) {
    const box = document.querySelector("#" + cfg.id + " .plot");
    const names = Object.keys(data.series || {});
    const picked = cfg.pick(names).filter(([k]) => (data.series[k] || []).some((v) => v != null));
    const key = range + "|" + picked.map((p) => p[0]).join(",");
    const sb = document.querySelector("#" + cfg.id + " .sim");
    if (sb) sb.hidden = !picked.some(([k]) => k.startsWith("sim_"));
    const p = plots[cfg.id];
    if (!picked.length) {
      if (p) { p.u.destroy(); plots[cfg.id] = null; }
      const why = cfg.infer && lastInfer ? " Now: " + lastInfer + "." : "";
      box.replaceChildren(el("div", { class: "empty", text: "No data for this time range." + why }));
      return;
    }
    const arr = [data.t].concat(picked.map(([k]) => data.series[k]));
    if (p && p.key === key) { p.u.setData(arr); return; }
    if (p) p.u.destroy();
    box.replaceChildren();
    const opts = {
      width: plotWidth(box), height: 180,
      legend: { show: true, live: true },
      cursor: { drag: { x: true, y: false } },
      scales: { x: { time: true }, y: cfg.range ? { range: cfg.range } : { auto: true } },
      axes: axisOpts(),
      series: [{ label: "Time" }].concat(picked.map(([k, label], i) => ({
        label, stroke: cssVar(SERIES_VARS[i % SERIES_VARS.length]), width: 2, spanGaps: false,
        points: { show: false }, value: (u, v) => (v == null ? "-" : v.toFixed(1)),
      }))),
    };
    plots[cfg.id] = { u: new uPlot(opts, arr, box), key };
  }
  // a new theme gives new token colours: make the charts again from the last data
  function resetCharts() {
    for (const p of Object.values(plots)) if (p) p.u.destroy();
    plots = {};
    if (lastHist && typeof uPlot === "function") for (const c of CHARTS) drawChart(c, lastHist);
    resetPowerChart();
  }
  // a hidden plot has the width 0: give each plot the width of its box when the History page shows
  function resizeCharts() {
    for (const [id, p] of Object.entries(plots)) {
      if (!p) continue;
      const box = document.querySelector("#" + id + " .plot");
      const w = plotWidth(box);
      if (box.clientWidth > 0 && Math.abs(w - p.u.width) > 4) p.u.setSize({ width: w, height: 180 });
    }
    resizePowerChart();
  }
  async function loadHistory() {
    const r = range;
    try {
      const d = await getJSON("/api/history?range=" + r);
      if (r !== range) return;  // the range changed while this request was open
      lastHist = d;
      setText("hist-src", `Source: ${d.source}. ${d.t.length} points.` + (d.db_error ? " " + d.db_error : ""));
      for (const c of CHARTS) drawChart(c, d);
    } catch (e) { if (r === range) setText("hist-src", "Cannot read history: " + e.message); }
  }
  function scheduleHistory() {
    clearInterval(histTimer);
    histTimer = setInterval(loadHistory, range === "1h" ? 10000 : 60000);
    loadHistory();
  }
  document.querySelectorAll("#hist-seg button").forEach((b) => b.addEventListener("click", () => {
    range = b.dataset.range;
    document.querySelectorAll("#hist-seg button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    scheduleHistory();
  }));
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(resizeCharts);
    document.querySelectorAll(".chart").forEach((c) => ro.observe(c));
  }

  /* ---------------- System: power log (/api/power..., dashboard/power_api.py) ---------------- */
  // Read only while the System page shows (router.js POLLS.system.power, 5 s): the value of now and the events each
  // poll, the chart each 10 s (1 h) or 60 s (24 h, 7 d, 30 d), the energy each 60 s. Labels (rule W2): SENSOR (a sensor
  // reads the value now) or NO SENSOR. The page calculates no power value.
  const PL_KIND = { models: "Model set", sender: "Sender", link: "Link", agx_unit: "Active unit", cameras: "Cameras",
    recording: "Recording", power_mode: "Power mode", control_mode: "Control mode" };
  const PL_RANGE_TEXT = { "1h": "1 h", "24h": "24 h", "7d": "7 d", "30d": "30 d" };
  const PL_PERIODS = [["today", "Today (from 00:00)"], ["d7", "Last 7 days"], ["d30", "Last 30 days"]];
  const PL_HEIGHT = 220;
  let plRange = "1h", plPlot = null, plData = null, plChartT = 0, plEnergyT = 0, plBusy = false;
  function plVal(v) {
    if (v == null) return NA;
    if (Array.isArray(v)) return v.length ? v.join(", ") : "(none)";
    if (typeof v === "boolean") return v ? "on" : "off";
    return String(v);
  }
  function plEventText(e) { return (PL_KIND[e.kind] || e.kind) + ": " + plVal(e.prev) + " to " + plVal(e.value); }
  function plBucketText(s) { return s >= 3600 ? s / 3600 + " h" : s >= 60 ? s / 60 + " min" : s + " s"; }
  // uPlot plugin: a dashed vertical line (token colour --da-amber) at the time of each event in the range
  function plMarks() {
    return { hooks: { draw: [(u) => {
      const evs = (plData && plData.events) || [];
      const x0 = u.scales.x.min, x1 = u.scales.x.max, px = window.devicePixelRatio || 1, ctx = u.ctx;
      ctx.save();
      ctx.strokeStyle = cssVar("--da-amber");
      ctx.lineWidth = px;
      ctx.setLineDash([4 * px, 3 * px]);
      for (const e of evs) {
        if (!(e.t >= x0 && e.t <= x1)) continue;
        const x = Math.round(u.valToPos(e.t, "x", true));
        ctx.beginPath(); ctx.moveTo(x, u.bbox.top); ctx.lineTo(x, u.bbox.top + u.bbox.height); ctx.stroke();
      }
      ctx.restore();
    }] } };
  }
  function drawPowerChart(d) {
    const box = document.querySelector("#ch-powerlog .plot");
    const part = powerPart(d);
    const s = (d.series || {})[part] || [];
    if (!s.some((v) => v != null)) {
      if (plPlot) { plPlot.destroy(); plPlot = null; }
      box.replaceChildren(el("div", { class: "empty", text: "No power samples in this time range." }));
      return;
    }
    const arr = [d.t, s];
    if (plPlot && plPlot.plRange === d.range) { plPlot.setData(arr); return; }
    if (plPlot) plPlot.destroy();
    box.replaceChildren();
    const opts = {
      width: plotWidth(box), height: PL_HEIGHT,
      legend: { show: true, live: true },
      cursor: { drag: { x: true, y: false } },
      scales: { x: { time: true }, y: { auto: true } },
      axes: axisOpts(),
      plugins: [plMarks()],
      series: [{ label: "Time" }, { label: part.toUpperCase() + " W (SENSOR)", stroke: cssVar("--da-chart-1"), width: 2, spanGaps: false,
        points: { show: false }, value: (u, v) => (v == null ? "-" : v.toFixed(2)) }],
    };
    plPlot = new uPlot(opts, arr, box);
    plPlot.plRange = d.range;
  }
  function resetPowerChart() {
    if (plPlot) { plPlot.destroy(); plPlot = null; }
    if (plData && typeof uPlot === "function") drawPowerChart(plData);
  }
  function resizePowerChart() {
    if (!plPlot) return;
    const box = document.querySelector("#ch-powerlog .plot");
    if (box.clientWidth > 0 && Math.abs(plotWidth(box) - plPlot.width) > 4) plPlot.setSize({ width: plotWidth(box), height: PL_HEIGHT });
  }
  async function loadPowerChart() {
    const r = plRange;
    try {
      const d = await getJSON("/api/power/samples?range=" + r);
      if (r !== plRange) return;  // the range changed while this request was open
      plData = d; plChartT = Date.now();
      if (typeof uPlot === "function") drawPowerChart(d);
      const n = (d.events || []).length;
      setText("pl-chart-note", "Mean power per " + plBucketText(d.bucket_s) + ". " + n + " event(s) in this range (dashed lines). " +
        "A gap in the line is a time without samples." + (typeof uPlot === "function" ? "" : " Chart library not loaded."));
    } catch (e) { if (r === plRange) setText("pl-chart-note", "Cannot read the power samples: " + e.message); }
  }
  function renderPowerNow(d) {
    const n = d.now || {};
    const sensor = n.label === "SENSOR" && num(n.watts);
    setText("pl-now", sensor ? fmt(n.watts, 1, "W") : NA);
    setBadge("pl-label", sensor ? "SENSOR" : "NO SENSOR", sensor ? "green" : "muted",
      sensor ? "A sensor reads this value now" : "There is no sensor value now");
    setText("pl-what", "It measures: " + (n.what || NA));
    setText("pl-mode", d.power_mode || NA);
    setText("pl-time", num(n.t) ? fmtTime(n.t) + (num(n.age_s) ? " (" + n.age_s.toFixed(1) + " s ago)" : "") : NA);
    const rails = Object.entries(n.rails || {});
    fill($("pl-rails").tBodies[0], rails.length ? rails.map(([k, w]) => el("tr", null, el("td", null, k), el("td", { class: "n" }, fmt(w, 2))))
      : [emptyRow(2, "No rail value now")]);
    const st = d.state || {};
    const known = Object.keys(PL_KIND).filter((k) => st[k] != null);
    setText("pl-state", known.length ? "Now: " + known.map((k) => PL_KIND[k] + " " + plVal(st[k])).join(" · ") : "");
    const lg = d.log || {};
    setText("pl-log", "Log file " + (lg.path || NA) + ": " + (num(lg.bytes) ? (lg.bytes / 1048576).toFixed(1) + " MB" : NA) +
      (lg.limits ? ". Limits: " + lg.limits : "") + (lg.error ? ". Problem: " + lg.error : ""));
  }
  function renderPowerEvents(d) {
    const rows = d.rows || [];
    fill($("pl-events").tBodies[0], rows.length ? rows.map((r) => {
      const p = (r.parts || {})[powerPart(d)] || {};
      const notes = (r.notes || []).concat(p.reason ? [p.reason] : []);
      return el("tr", null, td("Time", null, fmtDateTime(r.t)), td("Event", null, plEventText(r)),
        td("Before W", { class: "n" }, fmt(p.before_w, 2)), td("After W", { class: "n" }, fmt(p.after_w, 2)),
        td("Difference W", { class: "n" }, num(p.diff_w) ? (p.diff_w > 0 ? "+" : "") + p.diff_w.toFixed(2) : NA),
        td("Notes", null, notes.join("; ")));
    }) : [emptyRow(6, "No event yet.")]);
  }
  function renderPowerEnergy(d) {
    fill($("pl-energy").tBodies[0], PL_PERIODS.map(([k, label]) => {
      const e = (d[k] || {})[powerPart(d)] || {};
      return el("tr", null, td("Period", null, label), td("Wh", { class: "n" }, fmt(e.wh, 1)),
        td("Hours with data", { class: "n" }, num(e.hours) ? e.hours.toFixed(1) + " of " + fmt(e.span_h, 1) : NA),
        td("Mean W", { class: "n" }, fmt(e.mean_w, 1)));
    }));
  }
  async function loadPower() {
    if (plBusy) return;   // the last poll is still open
    plBusy = true;
    try {
      const now = Date.now();
      const jobs = [getJSON("/api/power").then(renderPowerNow), getJSON("/api/power/events?limit=20").then(renderPowerEvents)];
      if (now - plChartT >= (plRange === "1h" ? 10000 : 60000)) jobs.push(loadPowerChart());
      if (now - plEnergyT >= 60000) jobs.push(getJSON("/api/power/energy").then((d) => { plEnergyT = Date.now(); renderPowerEnergy(d); }));
      const res = await Promise.allSettled(jobs);
      const bad = res.filter((x) => x.status === "rejected").map((x) => (x.reason && x.reason.message) || String(x.reason));
      setText("pl-err", bad.length ? "Cannot read the power log: " + bad.join("; ") : "");
    } finally { plBusy = false; }
  }
  function plLinks() {
    setText("pl-csv-range", PL_RANGE_TEXT[plRange] || plRange);
    $("pl-csv-samples").href = "/api/power/export?kind=samples&range=" + plRange;
    $("pl-csv-events").href = "/api/power/export?kind=events&range=" + plRange;
  }
  document.querySelectorAll("#pl-seg button").forEach((b) => b.addEventListener("click", () => {
    plRange = b.dataset.range;
    document.querySelectorAll("#pl-seg button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    plLinks();
    loadPowerChart();
  }));

  /* ---------------- Settings, RK link: pairing of RK boards (docs/PAIRING_API.md) ---------------- */
  // GET /api/pair/state while the Settings page shows. The pairing code is ONLY in the answer of this page's own POST
  // /api/pair/code (pairCode); no GET answer has it, so only the page of the user who made the code shows it.
  const PAIR_POLL_MS = 2000;
  const LINK_TL = { "UP": "green", "frames only": "amber", "results only": "amber", "DOWN": "red", "NO DATA": "unknown" };
  let pairDoc = null, pairTimer = null, pairCode = null, pairTick = null, pairBusy = false, accDirty = false;
  let prDlg = null, prBusy = false;
  function pairMsg(id, text) { const e = $(id); if (!e) return; e.textContent = text || ""; e.hidden = !text; }
  function fmtLeft(s) { s = Math.max(0, Math.ceil(num(s) ? s : 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
  async function loadPairState() {
    try { pairDoc = await getJSON("/api/pair/state"); }
    catch (e) { pairMsg("pr-problem", "Cannot read the pairing state: " + e.message); return; }
    renderPair();
  }
  function setPairPoll(on) {
    if (pairTimer) { clearInterval(pairTimer); pairTimer = null; }
    if (!on) return;
    loadPairState();
    pairTimer = setInterval(loadPairState, PAIR_POLL_MS);
  }
  function renderUnit(u) {
    const p = u.ports || {};
    setText("pr-name", u.name || NA);
    const nets = (u.addresses || []).filter((n) => n && (n.addrs || []).length);
    $("pr-addrs").replaceChildren(...(nets.length ? nets.map((n) => el("div", { class: "mono" }, n.if + ": " + n.addrs.join(", "))) : [NA]));
    const vp = Array.isArray(p.video) && p.video.length ? p.video : null;
    setText("pr-p-video", vp ? vp[0] + " to " + vp[vp.length - 1] + " (" + vp[0] + " + camera number)" : NA);
    setText("pr-p-results", p.results != null ? String(p.results) : NA);
    setText("pr-p-status", p.status != null ? String(p.status) : NA);
    setText("pr-p-rkinfo", p.rkinfo != null ? String(p.rkinfo) : NA);
    setText("pr-p-api", p.api != null ? String(p.api) : NA);
  }
  function renderCode() {
    const c = (pairDoc && pairDoc.code) || {};
    let note = "";
    if (pairCode) {
      const same = c.expires_t == null || c.expires_t === pairCode.expires_t;
      const left = (pairCode.until - Date.now()) / 1000;
      if (!same) { pairCode = null; note = "A newer code cancelled your code."; }
      else if (c.state === "used") { pairCode = null; note = "The code was used. The new board is in the table."; }
      else if (c.state === "cancelled") { pairCode = null; note = "The code was cancelled after " + (c.wrong_max || 5) + " wrong codes. Make a new code."; }
      else if (c.state === "expired" || left <= 0) { pairCode = null; note = "The code expired. Make a new code."; }
    }
    const code = $("pr-code");
    if (pairCode) {
      code.textContent = pairCode.code;
      code.hidden = false;
      setText("pr-code-left", "Time left " + fmtLeft((pairCode.until - Date.now()) / 1000));
      note = "Type this code on the AGX link page of the rk console of the board. The code works one time." +
        (c.wrong ? " Wrong codes: " + c.wrong + " of " + (c.wrong_max || 5) + "." : "");
    } else {
      code.textContent = ""; code.hidden = true;
      setText("pr-code-left", "");
      if (!note && c.open) note = "A code is open (made by " + (c.made_by || NA) + ", time left " + fmtLeft(c.left_s) + "). Only the page that made the code shows it.";
    }
    setText("pr-code-state", note);
    if (!pairCode && pairTick) { clearInterval(pairTick); pairTick = null; }
  }
  function boardRow(b) {
    const st = b.link_state || "NO DATA";
    const rm = el("button", { type: "button", class: "da-btn da-btn--sm da-btn--danger" }, "Remove");
    rm.addEventListener("click", () => openPairDialog(b));
    const seen = num(b.last_seen_t) ? fmtDateTime(b.last_seen_t) + (b.last_seen_addr ? " from " + b.last_seen_addr : "") : "not yet";
    return el("tr", null,
      td("Board", null, el("strong", null, b.name || b.id), el("div", { class: "muted small mono" }, b.id),
        b.source === "migration" ? el("span", { class: "tag", title: "From the old control token (data/control.token)" }, "migrated") : null),
      td("Addresses", { class: "mono" }, (b.addresses || []).join(", ") || NA),
      td("Paired since", { class: "nowrap" }, fmtDateTime(b.paired_t)),
      td("Last seen", null, seen),
      td("Link", null, trafficLight(LINK_TL[st] || "unknown", "sm", true, st), b.link_detail ? el("div", { class: "muted small" }, b.link_detail) : null),
      td("Actions", { class: "actions" }, rm));
  }
  function renderPair() {
    const d = pairDoc; if (!d) return;
    renderUnit(d.unit || {});
    const probs = [];
    if (d.control_mode === "vehicle") probs.push("This AGX is in vehicle mode: it refuses pairing, removal and changes of these settings.");
    for (const p of [d.control_problem, d.store_problem, d.settings_problem]) if (p) probs.push(p);
    pairMsg("pr-problem", probs.join(" "));
    renderCode();
    const rows = d.boards || [];
    setText("pr-count", rows.length + (rows.length === 1 ? " board" : " boards"));
    fill($("pr-boards").tBodies[0], rows.length ? rows.map(boardRow)
      : [emptyRow(6, "No paired board. Make a pairing code, then pair the board on its rk console.")]);
    const o = d.other_subscribers || {};
    setText("pr-others", "Other result subscribers: " + (o.count == null ? NA : o.count + " (not paired)" +
      ((o.addresses || []).length ? ": " + o.addresses.join(", ") : "")));
    pairMsg("pr-linknote", o.available === false && o.reason ? "Link state: " + o.reason + "." : "");
    setText("pr-filter", "Video source filter of agx-infer: " + filterText(d.source_filter || {}));
    const acc = (d.settings && d.settings.accepted_board_address) || "";
    if (d.accepted_line) setText("pr-acc-line", d.accepted_line);
    setText("pr-acc-now", "Now: " + (acc ? "only " + acc + " can control this AGX." : "empty (each paired board can control this AGX)."));
    if (!accDirty && document.activeElement !== $("pr-acc")) $("pr-acc").value = acc;
  }
  $("pr-code-btn").addEventListener("click", async () => {
    if (pairBusy) return;
    pairBusy = true; $("pr-code-btn").disabled = true; pairMsg("pr-error", ""); pairMsg("pr-notice", "");
    try {
      const res = await postWrite("/api/pair/code");
      if (res.accepted && res.doc && res.doc.code) {
        pairCode = { code: res.doc.code, expires_t: res.doc.expires_t, until: Date.now() + (num(res.doc.ttl_s) ? res.doc.ttl_s : 600) * 1000 };
        if (pairDoc) pairDoc.code = { open: true, state: "open", expires_t: res.doc.expires_t, wrong: 0, wrong_max: res.doc.wrong_max };
        if (!pairTick) pairTick = setInterval(renderCode, 1000);
        renderCode();
      } else pairMsg("pr-error", refusalText(res));
    } catch (e) { pairMsg("pr-error", "The request did not complete: " + e.message); }
    pairBusy = false; $("pr-code-btn").disabled = false;
    loadPairState();
  });
  $("pr-acc").addEventListener("input", () => { accDirty = true; $("pr-acc").removeAttribute("aria-invalid"); });
  $("pr-acc-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (pairBusy) return;
    const v = $("pr-acc").value.trim();
    if (v !== "" && !/^\d{1,3}(\.\d{1,3}){3}$/.test(v)) {
      $("pr-acc").setAttribute("aria-invalid", "true");
      pairMsg("pr-error", "Type an IPv4 address (for example 10.42.0.2), or make the field empty.");
      return;
    }
    pairBusy = true; $("pr-acc-save").disabled = true; pairMsg("pr-error", ""); pairMsg("pr-notice", "");
    try {
      const res = await postWrite("/api/pair/settings", { accepted_board_address: v });
      if (res.accepted) {
        accDirty = false;
        pairMsg("pr-notice", "This AGX saved the accepted board address." + (res.doc.warning ? " Warning: " + res.doc.warning + "." : ""));
      } else pairMsg("pr-error", refusalText(res));
    } catch (e) { pairMsg("pr-error", "The request did not complete: " + e.message); }
    pairBusy = false; $("pr-acc-save").disabled = false;
    loadPairState();
  });
  // The FrameLink / RkCameraInfo source filter that agx-infer uses now (GET /api/pair/state source_filter).
  function filterText(f) {
    if (f.mode === "only") return "only from " + f.addresses.join(", ") + "." + (f.error ? " Problem: " + f.error + "." : "");
    if (f.mode === "any") return "off. No paired board has an address: agx-infer accepts video frames and camera names from each address.";
    if (f.mode === "none") return "no paired board has an address: agx-infer accepts video frames and camera names from no address.";
    return NA + (f.reason ? " (" + f.reason + ")" : "");
  }
  // Addresses that stay in the paired boards file after the removal of board b.
  function addressesLeft(b) {
    const left = new Set();
    for (const x of (pairDoc && pairDoc.boards) || []) if (x.id !== b.id) for (const a of x.addresses || []) left.add(a);
    return left.size;
  }
  function openPairDialog(b) {
    prDlg = b;
    setText("pr-dlg-title", "Remove the pairing of " + (b.name || b.id));
    const f = (pairDoc && pairDoc.source_filter) || {};
    const lastText = "No other paired board has an address. " + (f.when_empty === "none"
      ? "Then agx-infer accepts video frames and camera names from no address, until you pair a board again."
      : f.when_empty === "any"
        ? "Then the video source filter of agx-infer is off: it accepts video frames and camera names from each address, until you pair a board again."
        : "Then agx-infer has no board address for its video source filter.");
    const body = [
      el("p", null, "This AGX refuses the control token of ", el("code", null, b.name || b.id), " at once."),
      el("p", null, "To control this AGX again, the board must pair again with a new code.")];
    if (!addressesLeft(b)) body.push(el("p", { class: "callout callout--amber", id: "pr-dlg-last" }, el("strong", null, "Last board address. "), lastText));
    $("pr-dlg-body").replaceChildren(...body);
    const ok = $("pr-dlg-ok");
    ok.textContent = "Remove";
    prDlgError("");
    ok.disabled = false; $("pr-dlg-cancel").disabled = false;
    const d = $("pr-dlg");
    if (!d.open) { if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", ""); }
  }
  function prDlgError(t) { const e = $("pr-dlg-error"); e.textContent = t; e.hidden = !t; }
  function closePairDialog() {
    if (prBusy) return;
    prDlg = null;
    const d = $("pr-dlg");
    if (d.open) { if (typeof d.close === "function") d.close(); else d.removeAttribute("open"); }
  }
  $("pr-dlg-cancel").addEventListener("click", closePairDialog);
  $("pr-dlg").addEventListener("cancel", (ev) => { ev.preventDefault(); closePairDialog(); });
  $("pr-dlg-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!prDlg || prBusy) return;
    const b = prDlg;
    prBusy = true; prDlgError(""); $("pr-dlg-ok").disabled = true; $("pr-dlg-cancel").disabled = true;
    $("pr-dlg-ok").textContent = "Working";
    try {
      const res = await postWrite("/api/pair/boards/" + encodeURIComponent(b.id) + "/remove");
      prBusy = false;
      if (res.accepted) {
        closePairDialog();
        pairMsg("pr-error", "");
        pairMsg("pr-notice", "This AGX removed the pairing of " + (b.name || b.id) + "." +
          (res.doc && res.doc.warning ? " Warning: " + res.doc.warning + "." : ""));
      } else {
        prDlgError(refusalText(res));
        $("pr-dlg-ok").textContent = "Remove";
      }
    } catch (e) {
      prBusy = false;
      prDlgError("The request did not complete: " + e.message);
      $("pr-dlg-ok").textContent = "Remove";
    }
    $("pr-dlg-ok").disabled = false; $("pr-dlg-cancel").disabled = false;
    loadPairState();
  });

  /* ---------------- pages (hash routing, router.js) ---------------- */
  const POLLERS = { catalog: loadCatalog, models: loadModels, events: loadEvents, control: loadControl, services: loadServices,
    power: loadPower };
  let currentPage = null, pollTimers = [];
  function setPolls(page) {
    for (const t of pollTimers) clearInterval(t);
    pollTimers = [];
    let plan = R.polls(page);
    if (plan.catalog && plan.catalog === plan.models) {
      loadCatalogAndModels();
      pollTimers.push(setInterval(loadCatalogAndModels, plan.catalog));
      plan = Object.fromEntries(Object.entries(plan).filter(([k]) => k !== "catalog" && k !== "models"));
    }
    for (const [name, ms] of Object.entries(plan)) {
      const f = POLLERS[name];
      if (!f || !(ms > 0)) continue;
      f();
      pollTimers.push(setInterval(f, ms));
    }
  }
  function showPage() {
    const r = R.parse(location.hash);
    if (!r.known) { history.replaceState(null, "", R.href(r.page)); }
    const prev = currentPage;
    currentPage = r.page;
    document.querySelectorAll("main .page").forEach((s) => { s.hidden = s.dataset.page !== r.page; });
    document.querySelectorAll("#nav a").forEach((a) => {
      const on = a.dataset.page === r.page;
      a.classList.toggle("active", on);
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    $("shell").dataset.page = r.page;
    document.title = R.label(r.page) + " · " + ($("host").textContent || "agx") + " dashboard";
    if (r.page === "models" && r.arg) openDetails[r.arg] = true;
    if (prev !== r.page) {
      // a confirmation is for the page where it opened: close it (it stays only while its request runs, to show the result)
      closeDialog();
      closePairDialog();
      setPolls(r.page);
      setPairPoll(r.page === "settings");
      if (r.page === "models") renderModels();
      if (r.page === "overview") renderOverview();
      if (r.page === "history" || r.page === "system") requestAnimationFrame(resizeCharts);
      window.scrollTo(0, 0);
    } else if (r.page === "models") renderModels();
    syncLogs();
  }
  window.addEventListener("hashchange", showPage);

  /* ---------------- Settings: version and refresh periods ---------------- */
  function renderSettings() {
    setText("set-page-ver", PAGE_VERSION);
    setText("side-ver", "Page " + PAGE_VERSION.split(" ")[0]);
    const per = (ms) => (ms >= 1000 ? ms / 1000 + " s" : ms + " ms");
    const pollRows = [];
    for (const p of R.pages()) for (const [k, ms] of Object.entries(R.polls(p.id))) pollRows.push([k, ms, p.label]);
    const NAME = { catalog: "Model catalog", models: "Models (agx-infer, config/models.yaml)", events: "Model audit list",
      control: "Model control (mode, last good set)", services: "Services",
      power: "Power log: now and events (chart: 10 s for 1 h, else 60 s; energy: 60 s)" };
    const SRC = { catalog: "/api/models/catalog", models: "/api/models", events: "/api/models/events?limit=50",
      control: "/api/models/control", services: "/api/services",
      power: "/api/power, /api/power/events, /api/power/samples, /api/power/energy" };
    const rows = [
      ["Live data (health, cameras, services summary)", "/api/stream (SSE)", "1 s, and at once for each agx-infer status", "always"],
      ["Camera tile state", "this page (tiles.js)", "250 ms", "always"],
      ["Camera snapshots", "/api/cameras/N/snapshot.jpg", "1 s (only a new snapshot)", "always"],
      ...pollRows.map(([k, ms, label]) => [NAME[k] || k, SRC[k] || k, per(ms), "while the " + label + " page shows"]),
      ["Paired boards, pairing code state, this unit", "/api/pair/state", per(PAIR_POLL_MS), "while the Settings page shows"],
      ["Logs", "/api/services/logs", per(R.LOGS_MS), "while the Services page shows and the logs are open"],
      ["History", "/api/history", "10 s (1 h) or 60 s (24 h)", "always"],
    ];
    fill($("refresh-tbl").tBodies[0], rows.map((r) => el("tr", null, td("Data", null, r[0]), td("Source", { class: "mono" }, r[1]),
      td("Period", null, r[2]), td("When", null, r[3]))));
  }

  /* ---------------- start ---------------- */
  applyTheme(readTheme(), false);
  renderSettings();
  buildTiles(); evalTiles();
  setInterval(evalTiles, 250);
  setInterval(() => { for (let n = 0; n < tiles.length; n++) loadSnap(n); }, 1000);
  showPage();
  connect();
  if (typeof uPlot === "function") scheduleHistory();
  else setText("hist-src", "Chart library not loaded.");
})();
