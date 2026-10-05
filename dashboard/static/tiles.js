/* Camera tile state: pure functions, no DOM. Used by app.js and by the QuickJS test
   (tests/test_dashboard_v2.py). Same rule as camera_state() in dashboard/infer_views.py.

   nowS   = Date.now() / 1000 + serverOffset   (server clock, seconds)
   doc    = the "cameras" document of /api/cameras or of the SSE event
   known  = doc.status_t - cam.last_frame_t    frame age when agx-infer made the status
   upper  = nowS - cam.last_frame_t            time since the newest frame we know of
   hold   = doc.hold_s (status interval + jitter, max doc.hold_cap_s = no_signal_s + 0.5): frames after
            the status are not known yet. The server sends an SSE event at once for each new status,
            so the page has each new last_frame_t without a delay.
   Result: { state, age_s, cls, label }
     NO DATA    no camera document, agx-infer not available, or no status for no_data_s (3 s)
     NO SIGNAL  no frame, known >= no_signal_s, or upper >= max(no_signal_s, hold)
     STALE      known >= stale_s, or upper >= max(stale_s, hold)
     SIMULATED  frames from a simulated source (R13)
     OK         live frames                                                                  */
(function (root) {
  "use strict";
  var CLS = { "OK": "st-ok", "SIMULATED": "st-sim", "STALE": "st-stale", "NO SIGNAL": "st-nosig", "NO DATA": "st-nodata" };

  function isNum(v) { return typeof v === "number" && isFinite(v); }

  function tileState(cam, nowS, doc) {
    var noData = { state: "NO DATA", age_s: null, cls: CLS["NO DATA"], label: null };
    if (!doc || !doc.available || !cam) return noData;
    var lim = isNum(doc.no_data_s) ? doc.no_data_s : 3;
    if (!isNum(doc.status_rx_t) || nowS - doc.status_rx_t >= lim) return noData;
    if (cam.state === "NO DATA") return noData;
    var label = cam.simulated ? "SIMULATED" : null;
    var stale = isNum(doc.stale_s) ? doc.stale_s : 0.5;
    var nosig = isNum(doc.no_signal_s) ? doc.no_signal_s : 1.0;
    var hold = isNum(doc.hold_s) ? doc.hold_s : 0;
    hold = Math.min(hold, isNum(doc.hold_cap_s) ? doc.hold_cap_s : nosig + 0.5);
    if (!isNum(cam.last_frame_t)) return { state: "NO SIGNAL", age_s: null, cls: CLS["NO SIGNAL"], label: label };
    var upper = Math.max(0, nowS - cam.last_frame_t);
    var known = isNum(doc.status_t) ? Math.max(0, doc.status_t - cam.last_frame_t) : upper;
    var st = (known >= nosig || upper >= Math.max(nosig, hold)) ? "NO SIGNAL"
      : (known >= stale || upper >= Math.max(stale, hold)) ? "STALE"
      : (cam.simulated ? "SIMULATED" : "OK");
    return { state: st, age_s: upper, cls: CLS[st], label: label };
  }

  root.AGXTiles = { tileState: tileState, CLS: CLS };
})(typeof globalThis !== "undefined" ? globalThis : this);
