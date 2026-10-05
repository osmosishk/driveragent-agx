/* agx02 dashboard page. Read-only: only GET requests. No external URLs. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const NA = "n/a";

  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else e.setAttribute(k, v);
    }
    for (const k of kids) if (k != null) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
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
  const lvClass = (lv) => "lv-" + (lv === "ok" || lv === "warn" || lv === "crit" ? lv : "na");
  const lvWord = (lv) => ({ ok: "OK", warn: "WARN", crit: "CRIT" }[lv] || NA);
  function fill(tbody, rows) { tbody.replaceChildren(...rows); }
  function simBadge(on) { return on ? el("span", { class: "badge sim", text: "SIMULATED" }) : null; }

  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store", credentials: "same-origin" });
    if (!r.ok) throw new Error(url + " -> HTTP " + r.status);
    return r.json();
  }

  /* ---------------- live health (SSE) ---------------- */
  let lastMsg = 0;
  let lastInfer = null;  // infer_reason from the last health message (null when agx-infer sends status)
  function renderHealth(h) {
    setText("host", h.hostname || "agx02");
    document.title = (h.hostname || "agx02") + " dashboard";
    lastInfer = h.infer_reason || null;
    const ns = h.node_state || "NO DATA";
    setText("node-state", ns, "badge " + lvClass(ns.toLowerCase()));
    $("node-state").title = "Source: " + (h.node_state_source || NA);
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
      el("td", null, n.if), el("td", { class: n.state === "up" ? "lv-ok" : "muted" }, n.state),
      el("td", { class: "n", title: n.speed_na || null }, num(n.speed_mbps) ? n.speed_mbps + " Mb/s" : NA),
      el("td", { class: "n", title: n.rate_na || null }, fmtBps(n.rx_bps)), el("td", { class: "n", title: n.rate_na || null }, fmtBps(n.tx_bps)),
      el("td", null, (n.addrs || []).join(", ") || "-"))));

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
    setText("frame-age", num(l.time_since_last_frame_ms) ? l.time_since_last_frame_ms.toFixed(0) + " ms" : inaReason);
    setText("res-rate", num(l.results_rate_hz) ? l.results_rate_hz.toFixed(1) + " Hz" : inaReason);
    setText("subs", num(l.subscribers) ? String(l.subscribers) : inaReason);

    // infer
    const inf = h.infer;
    const st = h.infer_state || "NO DATA";
    const stLv = { RUNNING: "ok", STARTING: "warn", DEGRADED: "warn", ERROR: "crit" }[st] || "na";
    setText("infer-state", st, "badge " + lvClass(stLv));
    $("infer-sim").hidden = !(inf && inf.simulated);
    setText("infer-reason", inf ? `Status age ${fmt(inf.age_s, 1, "s")}, version ${inf.version || NA}` : (h.infer_reason || ""));
    $("infer-wait").hidden = !!inf;
    const box = $("infer-summary");
    if (!inf) { box.replaceChildren(); }
    else {
      const cs = inf.cameras_summary || {}, ms = inf.models_summary || {};
      const camRows = (cs.per_cam || []).map((c) => el("tr", null,
        el("td", null, "cam " + c.cam + (c.role ? " " + c.role : "")),
        el("td", null, c.state || NA, " ", simBadge(c.simulated)),
        el("td", { class: "n" }, fmt(c.fps, 1, "fps"))));
      const modRows = (ms.per_model || []).map((m) => el("tr", null,
        el("td", null, m.name || NA), el("td", null, m.state || NA, " ", simBadge(m.simulated)),
        el("td", { class: "n" }, fmt(m.lat_total_p50_ms, 1, "ms p50"))));
      box.replaceChildren(
        el("h3", null, `Cameras (${cs.total || 0})`, " ", simBadge(cs.simulated)),
        el("div", { class: "scroll" }, el("table", { class: "tbl" }, el("tbody", null, ...camRows))),
        el("h3", null, `Models (${ms.total || 0})`, " ", simBadge(ms.simulated)),
        el("div", { class: "scroll" }, el("table", { class: "tbl" }, el("tbody", null, ...modRows))),
        (inf.errors || []).length ? el("p", { class: "note lv-crit" }, "Errors: " + inf.errors.join("; ")) : null);
    }
  }

  let es = null, connT0 = 0, reconnectTimer = null;
  function markStale(on) {
    document.querySelector("main").classList.toggle("stale", on);
    if (on) setText("node-state", "NO DATA", "badge lv-na");
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
    es.onopen = () => { setText("conn", "Connected", "conn on"); };
    es.onmessage = (ev) => {
      lastMsg = Date.now();
      try {
        const d = JSON.parse(ev.data);
        if (d.health) renderHealth(d.health);
        markStale(!!(d.health && d.health.stale));
        setText("conn", "Connected", "conn on");
      } catch (e) {
        console.error(e);
        setText("conn", "Data error: " + e.message, "conn off");
      }
    };
    // the server sends "event: fail" when it cannot make one document
    es.addEventListener("fail", (ev) => {
      let m = "server error";
      try { m = JSON.parse(ev.data).error || m; } catch (e) { /* keep default */ }
      setText("conn", "Server error: " + m, "conn off");
    });
    es.onerror = () => {
      setText("conn", "Not connected. The page tries again.", "conn off");
      // CLOSED (2): the browser does not try again by itself, so open a new stream
      if (es && es.readyState === 2) reconnect(3000);
    };
  }
  setInterval(() => {
    const now = Date.now();
    if (lastMsg && now - lastMsg > 3500) {
      setText("conn", "No data for " + Math.round((now - lastMsg) / 1000) + " s", "conn off");
      markStale(true);
    }
    // no message for 10 s since the last message or the last (re)connect, also when the TCP
    // connection stays open: open a new stream
    if (!reconnectTimer && now - Math.max(lastMsg, connT0) > 10000) reconnect(0);
  }, 1000);

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
        return el("tr", null, el("td", null, x.name),
          el("td", { class: act(x) }, x.state), el("td", { class: act(s) }, s.state || NA),
          el("td", { class: "n" }, (m && m.main_pid) || "-"),
          el("td", { class: "n" }, m && num(m.n_restarts) ? m.n_restarts : "-"),
          el("td", { class: "n" }, memTxt(m ? m.memory_mb : null)));
      }));
      const dk = d.docker || {};
      const cont = dk.containers || [];
      setText("docker-sum", dk.available ? `${cont.filter((c) => c.state === "running").length} running / ${cont.length}` : "(" + (dk.error || NA) + ")");
      fill($("docker-tbl").tBodies[0], cont.map((c) => el("tr", null,
        el("td", null, c.name || c.id), el("td", { class: c.state === "running" ? "lv-ok" : "muted" }, c.state || NA),
        el("td", null, c.status || ""), el("td", null, c.restart_policy || NA), el("td", null, c.image || ""))));
      const old = u.old || [];
      setText("old-sum", `${old.filter((x) => x.active_state === "active").length} active / ${old.length}`);
      fill($("old-tbl").tBodies[0], old.map((x) => el("tr", null,
        el("td", null, x.name),
        el("td", { class: x.active_state === "active" ? "lv-ok" : x.active_state === "failed" ? "lv-crit" : "muted" }, x.state),
        el("td", null, x.unit_file_state || "-"), el("td", { class: "n" }, x.main_pid || "-"),
        el("td", { class: "n" }, memTxt(x.memory_mb)))));
      setText("svc-err", (u.errors || []).join("; "));
    } catch (e) { setText("svc-err", "Cannot read services: " + e.message); }
  }

  /* ---------------- logs (poll only while open) ---------------- */
  let logsTimer = null;
  async function loadLogs() {
    const unit = $("logs-unit").value;
    try {
      const d = await getJSON("/api/services/logs?unit=" + encodeURIComponent(unit));
      $("logs").textContent = d.lines && d.lines.length ? d.lines.join("\n") : "No log lines for " + unit + "." + (d.error ? " " + d.error : "");
      setText("logs-t", "Updated " + new Date(d.t * 1000).toLocaleTimeString());
    } catch (e) { $("logs").textContent = "Cannot read logs: " + e.message; }
  }
  $("logs-det").addEventListener("toggle", () => {
    clearInterval(logsTimer); logsTimer = null;
    if ($("logs-det").open) { loadLogs(); logsTimer = setInterval(loadLogs, 5000); }
  });
  $("logs-unit").addEventListener("change", () => { if ($("logs-det").open) loadLogs(); });

  /* ---------------- history charts ---------------- */
  const SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
  const CHARTS = [
    { id: "ch-load", pick: () => [["gpu_load_pct", "GPU"], ["cpu_load_avg_pct", "CPU avg"]], range: [0, 100] },
    { id: "ch-ram", pick: () => [["ram_used_pct", "RAM"]], range: [0, 100] },
    { id: "ch-temp", pick: () => [["temp_max_c", "Max"]] },
    { id: "ch-power", pick: () => [["power_total_w", "Total"]] },
    { id: "ch-fps", infer: true, pick: (names) => names.filter((n) => n.startsWith("fps.") || n.startsWith("sim_fps.")).sort().map((n) => [n, n.startsWith("sim_") ? n.slice(8) + " SIMULATED" : n.slice(4)]) },
    { id: "ch-lat", infer: true, pick: (names) => names.filter((n) => n.startsWith("lat_p50.") || n.startsWith("sim_lat_p50.")).sort().map((n) => [n, n.startsWith("sim_") ? n.slice(12) + " SIMULATED" : n.slice(8)]) },
  ];
  const plots = {};  // id -> {u, key}
  let range = "1h";
  let histTimer = null;

  function axisOpts() {
    const common = { stroke: "#9a988f", grid: { stroke: "#2c2c2a", width: 1 }, ticks: { stroke: "#383835", width: 1 } };
    return [common, Object.assign({}, common, { size: 48 })];
  }
  function drawChart(cfg, data) {
    const box = document.querySelector("#" + cfg.id + " .plot");
    const names = Object.keys(data.series || {});
    const picked = cfg.pick(names).filter(([k]) => (data.series[k] || []).some((v) => v != null));
    const key = range + "|" + picked.map((p) => p[0]).join(",");
    const sb = document.querySelector("#" + cfg.id + " .badge.sim");
    if (sb) sb.hidden = !picked.some(([k]) => k.startsWith("sim_"));
    if (!picked.length) {
      if (plots[cfg.id]) { plots[cfg.id].u.destroy(); delete plots[cfg.id]; }
      const why = cfg.infer && lastInfer ? " Now: " + lastInfer + "." : "";
      box.replaceChildren(el("div", { class: "empty", text: "No data for this time range." + why }));
      return;
    }
    const arr = [data.t].concat(picked.map(([k]) => data.series[k]));
    const p = plots[cfg.id];
    if (p && p.key === key) { p.u.setData(arr); return; }
    if (p) p.u.destroy();
    box.replaceChildren();
    const opts = {
      width: Math.max(200, box.clientWidth), height: 180,
      legend: { show: true, live: true },
      cursor: { drag: { x: true, y: false } },
      scales: { x: { time: true }, y: cfg.range ? { range: cfg.range } : { auto: true } },
      axes: axisOpts(),
      series: [{ label: "Time" }].concat(picked.map(([k, label], i) => ({
        label, stroke: SERIES_COLORS[i % SERIES_COLORS.length], width: 2, spanGaps: false,
        points: { show: false }, value: (u, v) => (v == null ? "-" : v.toFixed(1)),
      }))),
    };
    plots[cfg.id] = { u: new uPlot(opts, arr, box), key };
  }
  async function loadHistory() {
    const r = range;
    try {
      const d = await getJSON("/api/history?range=" + r);
      if (r !== range) return;  // the range changed while this request was open
      setText("hist-src", `Source: ${d.source}. ${d.t.length} points.` + (d.db_error ? " " + d.db_error : ""));
      for (const c of CHARTS) drawChart(c, d);
    } catch (e) { if (r === range) setText("hist-src", "Cannot read history: " + e.message); }
  }
  function scheduleHistory() {
    clearInterval(histTimer);
    histTimer = setInterval(loadHistory, range === "1h" ? 10000 : 60000);
    loadHistory();
  }
  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    range = b.dataset.range;
    document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
    scheduleHistory();
  }));
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => {
      for (const [id, p] of Object.entries(plots)) {
        const box = document.querySelector("#" + id + " .plot");
        const w = Math.max(200, box.clientWidth);
        if (Math.abs(w - p.u.width) > 4) p.u.setSize({ width: w, height: 180 });
      }
    });
    document.querySelectorAll(".chart").forEach((c) => ro.observe(c));
  }

  /* ---------------- start ---------------- */
  connect();
  loadServices(); setInterval(loadServices, 5000);
  if (typeof uPlot === "function") scheduleHistory();
  else setText("hist-src", "Chart library not loaded.");
})();
