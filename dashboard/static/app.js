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
        if (d.cameras) setCameras(d.cameras);
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


  /* ---------------- cameras (six tiles) ---------------- */
  // serverOffset = server clock - page clock (s). Tiles are evaluated every 250 ms with the page
  // clock + serverOffset, so a tile changes to NO SIGNAL also between two SSE events. The server
  // sends an SSE event at once for each new agx-infer status. No status for 3 s -> NO DATA.
  const T = window.AGXTiles;
  let camDoc = null, serverOffset = 0;
  const tiles = [];
  function buildTiles() {
    const box = $("cam-tiles");
    for (let n = 0; n < 6; n++) {
      const t = {
        state: el("span", { class: "badge state", text: "NO DATA" }),
        sim: el("span", { class: "badge sim", text: "SIMULATED", hidden: "" }),
        role: el("span", { class: "muted" }),
        img: el("img", { alt: "Camera " + n + " picture", width: "320", height: "180" }),
        over: el("span", { class: "over", text: "NO DATA" }),
        none: el("span", { class: "nopic", text: "No picture" }),
        fps: el("b"), rate: el("b"), lost: el("b"), dec: el("b"), age: el("b"),
        reason: el("div", { class: "note" }),
        url: null, snapT: 0, busy: false,
      };
      const kv = (k, v) => el("div", { class: "row" }, el("span", { class: "k" }, k), v);
      t.root = el("div", { class: "tile st-nodata", id: "cam-tile-" + n },
        el("div", { class: "tile-h" }, el("b", null, "Camera " + n), " ", t.role, el("span", { class: "sp" }), t.sim, " ", t.state),
        el("div", { class: "snap" }, t.none, t.img, t.over),
        kv("Frames per second", t.fps), kv("Bit rate", t.rate), kv("Lost packets (frames)", t.lost),
        kv("Decode time p50", t.dec), kv("Frame age", t.age), t.reason);
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
      t.root.className = "tile " + r.cls;
      t.state.textContent = r.state;
      t.over.textContent = r.state;
      t.sim.hidden = r.label !== "SIMULATED";
      t.role.textContent = c.role || "";
      const nd = r.state === "NO DATA";
      const nf = nd || r.state === "NO SIGNAL";  // no frame now: the rates of the last status are not current
      t.fps.textContent = nf ? NA : fmt(c.fps, 1);
      t.rate.textContent = nf ? NA : fmt(c.bitrate_kbps, 0, "kbit/s");
      t.lost.textContent = nd ? NA : (num(c.lost_packets) ? c.lost_packets : NA) + " (" + (num(c.lost_frames) ? c.lost_frames : NA) + ")";
      t.dec.textContent = nd ? NA : fmt(c.decode_p50_ms, 1, "ms");
      // OK / SIMULATED: the age that agx-infer measured; else the time since the newest known frame
      t.age.textContent = (r.state === "OK" || r.state === "SIMULATED") && num(c.frame_age_ms) ? c.frame_age_ms.toFixed(0) + " ms"
        : num(r.age_s) ? (r.age_s * 1000).toFixed(0) + " ms" : NA;
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

  /* ---------------- models ---------------- */
  function fmtSize(b) {
    if (!num(b)) return NA;
    if (b >= 1048576) return (b / 1048576).toFixed(1) + " MiB";
    return (b / 1024).toFixed(0) + " KiB";
  }
  const shp = (t) => (t.name || "?") + " " + (Array.isArray(t.shape) ? "[" + t.shape.join("x") + "]" : "") + (t.dtype ? " " + t.dtype : "");
  function ioCell(ins, outs) {
    if (!(ins || []).length && !(outs || []).length) return el("td", { class: "muted" }, NA);
    return el("td", { class: "io" },
      el("div", null, el("span", { class: "k" }, "In: "), (ins || []).map(shp).join("; ") || NA),
      el("div", null, el("span", { class: "k" }, "Out: "), (outs || []).map(shp).join("; ") || NA));
  }
  function trtCell(m) {
    const w = m.load_warnings || [];
    const txt = m.trt_match === true ? "yes" : m.trt_match === false ? "no" : NA;
    const cls = m.trt_match === true ? "lv-ok" : m.trt_match === false ? "lv-crit" : "muted";
    return el("td", { title: w.join("\n") || null },
      el("span", { class: cls }, txt), m.trt_version ? el("span", { class: "muted" }, " TensorRT " + m.trt_version) : null,
      m.engine_load === "FAILED" ? el("div", { class: "lv-crit small" }, "Load FAILED" + (m.engine_error ? ": " + m.engine_error : "")) : null,
      w.length ? el("div", { class: "lv-warn small" }, w.length + " load message(s): " + w[0].slice(0, 120)) : null);
  }
  const STATE_LV = { RUNNING: "lv-ok", LOADED: "lv-warn", OFF: "lv-na", FAILED: "lv-crit" };
  const p3 = (o) => o ? [o.p50, o.p95, o.p99].map((v) => fmt(v, 1)).join(" / ") : NA;
  async function loadModels() {
    try {
      const d = await getJSON("/api/models");
      setText("models-reason", d.available ? "" : "agx-infer gives no status: " + (d.reason || NA) + ". Live values show n/a.");
      $("models-sim").hidden = !d.simulated;
      setText("models-note", d.config_error ? d.config_error : "");
      const rows = [];
      for (const m of d.models || []) {
        const lat = m.lat_ms || {};
        const st = m.state || NA;
        rows.push(el("tr", { class: "mrow" },
          el("td", null, el("b", null, m.name || NA), m.in_config ? null : el("div", { class: "lv-warn small" }, "Not in config/models.yaml"),
            m.group ? el("div", { class: "muted small" }, "group " + m.group) : null),
          el("td", { title: m.engine_realpath || null }, m.engine_file || el("span", { class: "muted" }, "no engine file"),
            m.engine && !m.engine_exists ? el("div", { class: "lv-crit small" }, "File not found") : null),
          el("td", { class: "n" }, fmtSize(m.size_bytes)),
          el("td", null, m.mtime || NA),
          trtCell(m),
          ioCell(m.inputs, m.outputs),
          el("td", null, el("span", { class: "badge " + (STATE_LV[st] || "lv-na") }, st), " ", simBadge(m.simulated),
            m.error ? el("div", { class: "lv-crit small" }, m.error) : null,
            m.reason ? el("div", { class: "muted small" }, m.reason) : null),
          el("td", null, (m.cameras || []).join(", ") || "-"),
          el("td", { class: "n" }, fmt(m.fps, 1)),
          el("td", { class: "n", title: "ms. pre " + p3(lat.pre) + "\ninfer " + p3(lat.infer) + "\npost " + p3(lat.post) }, p3(lat.total) + " ms"),
          el("td", { class: "n", title: m.gpu_mem_note || "estimate" }, num(m.gpu_mem_mb) ? m.gpu_mem_mb.toFixed(0) + " MB (estimate)" : NA + " (estimate)")));
        rows.push(el("tr", { class: "detail" }, el("td", { colspan: "11" },
          "Latency per stage p50 / p95 / p99 (ms): pre " + p3(lat.pre) + ", infer " + p3(lat.infer) + ", post " + p3(lat.post) +
          ". sha256 (16): " + (m.sha256_16 || NA) + ". Path: " + (m.engine_realpath || NA) +
          (num(m.results_total) ? ". Results: " + m.results_total : "") + ".")));
      }
      fill($("models-tbl").tBodies[0], rows);
      const ex = d.engines_not_in_config || [];
      setText("extra-sum", "(" + ex.length + ")");
      fill($("extra-tbl").tBodies[0], ex.length ? ex.map((e) => el("tr", null,
        el("td", { title: e.engine_realpath || null }, e.engine_realpath || e.engine || NA),
        el("td", { class: "n" }, fmtSize(e.size_bytes)), el("td", null, e.mtime || NA),
        el("td", null, e.sha256_16 || NA), trtCell(e), ioCell(e.inputs, e.outputs)))
        : [el("tr", null, el("td", { colspan: "6", class: "muted" }, "No other engine file found."))]);
      const sc = d.engine_scan || {};
      setText("scan-note", "Engine scan: " + (num(sc.t) ? new Date(sc.t * 1000).toLocaleString() : "not done yet") +
        (sc.running ? " (scan runs now)" : "") + ", " + (sc.count || 0) + " engine files in " + (sc.dirs || []).join(", ") +
        ". Scan interval " + fmt((sc.interval_s || 0) / 60, 0, "min") + "." + (sc.error ? " Error: " + sc.error : "") +
        " " + (d.gpu_mem_note || ""));
    } catch (e) { setText("models-reason", "Cannot read models: " + e.message); }
  }

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
      const op = d.old_processes || {};
      const ps = op.processes || [];
      setText("oldp-sum", op.error ? "(" + op.error + ")" : ps.length ? "(" + ps.length + " running)" : "(none running)");
      if (op.note) setText("oldp-note", op.note);
      fill($("oldp-tbl").tBodies[0], ps.length ? ps.map((x) => el("tr", null,
        el("td", { class: "n" }, x.pid), el("td", null, x.user || NA), el("td", null, x.match || ""),
        el("td", { class: "cmd" }, x.cmdline || ""))) : [el("tr", null, el("td", { colspan: "4", class: "muted" }, "none running"))]);
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
  buildTiles(); evalTiles();
  setInterval(evalTiles, 250);
  setInterval(() => { for (let n = 0; n < tiles.length; n++) loadSnap(n); }, 1000);
  connect();
  loadModels(); setInterval(loadModels, 2000);
  loadServices(); setInterval(loadServices, 5000);
  if (typeof uPlot === "function") scheduleHistory();
  else setText("hist-src", "Chart library not loaded.");
})();
