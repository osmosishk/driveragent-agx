/* Hash router of the agx02 dashboard: pure functions, no DOM. Loaded before app.js; also used by the QuickJS test
   (tests/test_dashboard_pages.py).

   A hash is "#/<page>" or "#/<page>/<argument>". Example: "#/models/driverguard_yolopx%401" opens the Models page
   with the details of driverguard_yolopx@1. An empty or unknown hash gives the Overview page.

   polls(page): the poll periods (ms) of the data that is NOT in the SSE stream /api/stream, for the page that shows.
   The page polls only these. The SSE stream (1 s), the camera tiles (250 ms), the snapshots (1 s) and the history
   (10 s for 1 h, 60 s for 24 h) do not depend on the page. The logs poll (5 s) runs only while the Services page
   shows and the logs are open (logsWanted).                                                                          */
(function (root) {
  "use strict";
  var PAGES = [
    { id: "overview", label: "Overview" },
    { id: "cameras", label: "Cameras" },
    { id: "models", label: "Models" },
    { id: "rklink", label: "RK link" },
    { id: "system", label: "System" },
    { id: "services", label: "Services" },
    { id: "history", label: "History" },
    { id: "settings", label: "Settings" },
  ];
  var DEFAULT = "overview";
  var POLLS = {
    // the Overview tiles use the SSE data; the model catalog (counts, control mode) comes from a slower poll
    overview: { catalog: 10000 },
    models: { catalog: 2000, models: 2000, events: 5000, control: 5000 },
    services: { services: 5000 },
    settings: { control: 10000 },
    // the power log card (dashboard/power_api.py): app.js loadPower; the chart and the energy have longer periods
    system: { power: 5000 },
  };
  var LOGS_MS = 5000;

  function isPage(id) {
    for (var i = 0; i < PAGES.length; i++) if (PAGES[i].id === id) return true;
    return false;
  }

  function parse(hash) {
    var h = String(hash == null ? "" : hash);
    if (h.charAt(0) === "#") h = h.slice(1);
    if (h.charAt(0) === "/") h = h.slice(1);
    var i = h.indexOf("/");
    var id = (i < 0 ? h : h.slice(0, i)).toLowerCase();
    var arg = i < 0 ? "" : h.slice(i + 1);
    try { arg = decodeURIComponent(arg); } catch (e) { arg = ""; }  // a bad %-sequence: no argument
    if (!isPage(id)) return { page: DEFAULT, arg: null, known: h === "" };
    return { page: id, arg: arg || null, known: true };
  }

  function href(id, arg) {
    if (!isPage(id)) id = DEFAULT;
    return "#/" + id + (arg ? "/" + encodeURIComponent(String(arg)) : "");
  }

  function label(id) {
    for (var i = 0; i < PAGES.length; i++) if (PAGES[i].id === id) return PAGES[i].label;
    return label(DEFAULT);
  }

  function polls(id) {
    var src = POLLS[isPage(id) ? id : DEFAULT] || {}, out = {};
    for (var k in src) if (Object.prototype.hasOwnProperty.call(src, k)) out[k] = src[k];
    return out;
  }

  function logsWanted(id, open) { return id === "services" && !!open; }

  function pages() {
    var out = [];
    for (var i = 0; i < PAGES.length; i++) out.push({ id: PAGES[i].id, label: PAGES[i].label });
    return out;
  }

  root.AGXRouter = { DEFAULT: DEFAULT, LOGS_MS: LOGS_MS, pages: pages, isPage: isPage, parse: parse, href: href,
                     label: label, polls: polls, logsWanted: logsWanted };
})(typeof globalThis !== "undefined" ? globalThis : this);
