"""Dashboard page rules (N6: sidebar pages in the rk console look). Static checks of dashboard/static, no server.

Run: .venv/bin/python -m pytest -p no:cacheprovider -q tests/test_dashboard_pages.py

- tokens.css: a copy of the rk console tokens with the source line; it loads before style.css.
- style.css: every colour, corner radius, shadow and font value is a token (var(--da-...)).
- Pages and nav: one section and one nav link per page; the element ids of the old page (inventory) exist.
- Writes: the only POST is in postWrite() and goes to /api/models/ (model control) or /api/pair/ (pairing, Settings
  page); no delete anywhere; no service control words on the page.
- The TensorRT device warning is only in the model details code path.
- router.js: pure functions, tested in QuickJS (like tiles.js in tests/test_dashboard_v2.py).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "dashboard" / "static"
PAGE = (STATIC / "index.html").read_text()
APP = (STATIC / "app.js").read_text()
ROUTER = (STATIC / "router.js").read_text()
STYLE = (STATIC / "style.css").read_text()
TOKENS = (STATIC / "tokens.css").read_text()

PAGES = ["overview", "cameras", "models", "rklink", "system", "services", "history", "settings"]
LABELS = ["Overview", "Cameras", "Models", "RK link", "System", "Services", "History", "Settings"]
# every element id of the page before N6 (docs/DASHBOARD_PAGES.md says where each one is now)
INVENTORY_IDS = """host node-state sim-badge time uptime nvp conn state-reasons c-cams cams-sim cams-note cam-tiles
cams-limits c-models models-sim models-note models-reason models-tbl extra-sum extra-tbl scan-note c-cpu cpu-avg
cpu-cores c-gpu gpu-load gpu-bar gpu-freq ram ram-bar swap c-temp temp-max temp-tbl c-power power-total power-src
power-tbl fan c-disk disks c-net net-tbl c-link rk-ip ping loss-k loss clock clock-note link-sim frame-age res-rate
subs res-total res-last c-infer infer-state infer-sim infer-reason infer-wait infer-summary c-svc agx-tbl docker-sum
docker-tbl oldp-sum oldp-note oldp-tbl old-det old-sum old-tbl svc-err c-logs logs-det logs-unit logs-t logs c-hist
hist-src ch-load ch-ram ch-temp ch-power ch-fps ch-lat""".split()
NEW_IDS = """shell nav side-host ov-tiles ov-banner mc-mode mc-change mc-rollback mc-notice mc-last mc-dlg mc-dlg-ok
mc-dlg-cams models-events c-extra c-audit theme-seg set-mode set-page-ver refresh-tbl""".split()


def _section(page_id: str) -> str:
    """The HTML of <section ... data-page="<id>"> up to the next page section."""
    m = re.search(r'<section class="page" data-page="%s".*?(?=<section class="page" data-page=|<footer)' % page_id,
                  PAGE, re.S)
    assert m, page_id
    return m.group(0)


def _function_body(src: str, name: str) -> str:
    i = src.index("function " + name + "(")
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError(name)


# ---------------------------------------------------------------- design values
def test_tokens_copy_source_line_and_load_order():
    first = TOKENS.splitlines()[0]
    assert re.fullmatch(r"/\* source: driveragent rk/console/ui/src/styles/tokens\.css, commit [0-9a-f]{7,40}\. "
                        r"Do not edit this copy\. \*/", first), first
    assert "--da-bg:" in TOKENS and ":root[data-theme='dark']" in TOKENS and "prefers-color-scheme: dark" in TOKENS
    i_tok, i_style = PAGE.index('href="/static/tokens.css"'), PAGE.index('href="/static/style.css"')
    assert i_tok < i_style
    assert PAGE.index('src="/static/router.js"') < PAGE.index('src="/static/app.js"')
    assert PAGE.index('src="/static/tiles.js"') < PAGE.index('src="/static/app.js"')


def test_style_uses_only_tokens():
    css = re.sub(r"/\*.*?\*/", "", STYLE, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "a literal colour in style.css"
    assert not re.search(r"\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(", css), "a literal colour in style.css"
    assert not re.search(r":\s*(white|black|red|green|blue|gray|grey|orange|yellow)\b", css)
    defined = set(re.findall(r"(--da-[a-z0-9-]+)\s*:", TOKENS))
    used = set(re.findall(r"var\((--da-[a-z0-9-]+)", css))
    assert used and used <= defined, f"unknown tokens: {sorted(used - defined)}"
    for prop in ("border-radius", "box-shadow", "font-family", "font-size", "font-weight", "color", "background",
                 "border-color", "line-height", "letter-spacing"):
        for m in re.finditer(r"(?<![-\w])%s\s*:\s*([^;]+);" % prop, css):
            v = m.group(1).strip()
            ok = ("var(--da-" in v or v in ("inherit", "transparent", "currentColor", "none", "0", "1", "normal")
                  or (prop == "background" and v.startswith("color-mix(") and "var(--da-" in v))
            assert ok, f"{prop}: {v}"
    # font shorthand only as "inherit"
    for m in re.finditer(r"(?<![-\w])font\s*:\s*([^;]+);", css):
        assert m.group(1).strip() == "inherit", m.group(0)


def test_light_default_dark_by_theme_and_saved_choice():
    assert '<meta name="color-scheme" content="light dark">' in PAGE
    assert "data-theme" in APP and "localStorage" in APP
    for t in ("system", "light", "dark"):
        assert f'data-theme-set="{t}"' in PAGE


# ---------------------------------------------------------------- shell, pages, inventory
def test_title_no_external_url():
    assert "<title>agx02 dashboard</title>" in PAGE
    for name, text in (("index.html", PAGE), ("app.js", APP), ("router.js", ROUTER), ("style.css", STYLE),
                       ("tokens.css", TOKENS), ("tiles.js", (STATIC / "tiles.js").read_text())):
        assert "http://" not in text and "https://" not in text, name
        assert not re.search(r"""(src|href)=["']//""", text), name


def test_every_page_section_and_nav_link():
    for pid, label in zip(PAGES, LABELS):
        assert PAGE.count(f'<section class="page" data-page="{pid}"') == 1, pid
        assert f'<a href="#/{pid}" data-page="{pid}">' in PAGE, pid
        assert f"<span>{label}</span>" in PAGE, label
        _section(pid)
    assert 'class="brand__name">agx dashboard<' in PAGE and 'id="side-host"' in PAGE
    assert '<aside class="side"' in PAGE and '<header class="topbar">' in PAGE
    assert "@media (max-width: 900px)" in STYLE                      # the bottom tab bar


def test_inventory_ids_exist_once():
    ids = re.findall(r'\bid="([^"]+)"', PAGE)
    for i in INVENTORY_IDS + NEW_IDS:
        assert ids.count(i) == 1, i
    # where the old cards are now
    where = {"models": ["c-models", "models-tbl", "extra-tbl", "scan-note", "models-events", "mc-rollback"],
             "cameras": ["c-cams", "cam-tiles", "cams-limits"], "rklink": ["c-link", "frame-age", "res-last"],
             "system": ["c-cpu", "c-gpu", "c-temp", "c-power", "c-disk", "c-net"],
             "services": ["c-svc", "c-logs", "oldp-note", "logs-unit"], "history": ["c-hist", "ch-lat"],
             "overview": ["c-infer", "ov-tiles"], "settings": ["theme-seg", "set-mode", "refresh-tbl"]}
    for pid, ids_ in where.items():
        sec = _section(pid)
        for i in ids_:
            assert f'id="{i}"' in sec, (pid, i)
    # the confirmation dialog is outside every page section (a hidden section must not hold an open modal dialog)
    for pid in PAGES:
        assert 'id="mc-dlg"' not in _section(pid), pid
    assert PAGE.index('<dialog id="mc-dlg"') > PAGE.index("</main>")
    # the header keeps host, node state, SIMULATED, time, uptime, power mode and the connection pill
    head = PAGE[PAGE.index('<header class="topbar">'):PAGE.index("</header>")]
    for i in ("host", "node-state", "sim-badge", "time", "uptime", "nvp", "conn"):
        assert f'id="{i}"' in head, i
    assert 'value="agx-infer"' in PAGE and 'value="agx-dashboard"' in PAGE and 'value="agx-sim"' in PAGE


def test_inventory_values_kept_in_app_js():
    for s in ("m.last_error", "m.queue_ms", "m.errors_total", "m.auto_restarts", "c.last_error", "m.sha256_16",
              "m.engine_realpath", "m.gpu_mem_mb", "(estimate)", "lat.pre", "lat.infer", "lat.post", "m.results_total",
              "Not in config/models.yaml", "File not found", "Load FAILED", "m.group", "e.description", "e.precision",
              "e.notes", "e.output_kinds", "f.sha256", "c.inference_ms", "e.job", "build_warning", "job.progress",
              "job.elapsed_s", "last.reason", "control_mode", "cameras_permitted", "cameras_default",
              "oldp-note", "clock_note", "total_source", "ping_error", "time_since_last_frame_basis",
              "loss_window_s", "hold_cap_s", "limits_source", "status_period_s", "db_error", "engine_scan",
              "engines_not_in_config", "config_error", "camText(c)", "c.cam_note"):
        assert s in APP, s
    assert "No systemd unit exists for the old DriverAgent stack; it starts by hand (~/s.sh)" in PAGE


def test_info_controls():
    btns = re.findall(r'<button type="button" class="info-btn" aria-expanded="false" aria-controls="([^"]+)"', PAGE)
    assert len(btns) >= 8
    for b in btns:
        assert re.search(r'<div class="info-text" id="%s" hidden>' % re.escape(b), PAGE), b
    # the long explanations are behind an info control
    for pid in ("cams-limits", "clock-note", "scan-note", "oldp-note"):
        m = re.search(r'<div class="info-text" id="[^"]+" hidden>(?:(?!</div>).)*id="%s"' % pid, PAGE, re.S)
        assert m, pid
    assert "On Jetson, the GPU and the CPU use the same RAM." in PAGE


# ---------------------------------------------------------------- model control
def test_post_only_in_one_function_and_only_to_api_models_or_pair():
    assert APP.count('"POST"') == 1 and re.findall(r"\bmethod\s*:\s*[\"']([A-Z]+)[\"']", APP) == ["POST"]
    body = _function_body(APP, "postWrite")
    assert 'method: "POST"' in body and "fetch(path, {" in body
    assert 'if (!WRITE_PREFIXES.some((p) => path.startsWith(p))) throw' in body
    assert 'const WRITE_PREFIXES = ["/api/models/", "/api/pair/"];' in APP
    assert '"X-AGX-CSRF": "1"' in body and '"Content-Type": "application/json"' in body
    assert 'credentials: "same-origin"' in body
    # one definition; each call names its path: /api/models/ (rollback or name/version/{build|activate|deactivate})
    # or /api/pair/ (code, settings, boards/{id}/remove)
    assert APP.count("async function postWrite(") == 1
    calls = re.findall(r"await postWrite\(\"(/api/[a-z]+/[a-z]*)", APP)
    assert len(calls) == APP.count("await postWrite(") == 4, calls
    assert sorted(calls) == ["/api/models/", "/api/pair/boards", "/api/pair/code", "/api/pair/settings"], calls
    assert '"rollback"' in APP and "encodeURIComponent(entry.name)" in APP
    for k in ("build", "activate", "deactivate"):
        assert f'"{k}"' in APP
    # every other fetch is a GET: a method is only in postWrite (above), 3 fetch calls in all
    assert len(re.findall(r"\bfetch\(", APP)) == 3   # getJSON, the snapshot, postWrite
    for bad in ('"PUT"', '"PATCH"', '"DELETE"'):
        assert bad not in APP
    assert not re.search(r"delete", APP, re.I) and not re.search(r"delete", ROUTER, re.I)


def test_no_service_control_words_and_no_delete_control():
    low = PAGE.lower()
    for bad in (">stop<", ">start<", ">restart<", ">kill<", ">delete<", ">remove<"):
        assert bad not in low
    # button labels made by app.js
    labels = set(re.findall(r'btn\("([A-Za-z ]+)"', APP))
    assert labels == {"Deactivate", "Build", "Activate"}, labels
    # the one "Remove" of the page: the removal of a pairing (Settings, RK link), with its confirmation dialog
    a, b = APP.index("/* ---------------- Settings, RK link: pairing"), APP.index("/* ---------------- pages (hash")
    hits = [m.start() for m in re.finditer('"Remove"', APP)]
    assert hits and all(a < i < b for i in hits)
    assert '<dialog id="pr-dlg"' in PAGE and PAGE.index('<dialog id="pr-dlg"') > PAGE.index("</main>")
    assert 'id="mc-rollback">Rollback</button>' in PAGE
    assert "showModal" in APP and '<dialog id="mc-dlg"' in PAGE   # the confirmation step (native <dialog>)


def test_refusal_reason_shown_as_is_and_buttons_not_disabled_by_mode():
    assert "res.doc.reason" in APP
    # no rule that disables the action buttons in vehicle mode: the server gives the reason
    assert not re.search(r"vehicle[^\n]*disabled|disabled[^\n]*vehicle", APP)


def test_device_warning_only_in_details_code_path():
    start = APP.index("/* == model details")
    end = APP.index("/* == end of the model details == */")
    outside = APP[:start] + APP[end:]
    for s in ("trt_device_warning", "Device warning", "load_warnings"):
        assert s in APP[start:end], s
        assert s not in outside, s
    assert "device warning" not in PAGE.lower() and "different models of devices" not in PAGE


# ---------------------------------------------------------------- QuickJS: router.js and compile checks
def _quickjs():
    pl = os.environ.get("AGX_DASH_TEST_PYLIB")
    if pl and pl not in sys.path:
        sys.path.insert(0, pl)
    try:
        import quickjs
    except ImportError:
        pytest.skip("quickjs not installed (set AGX_DASH_TEST_PYLIB)")
    return quickjs


def test_router_quickjs():
    ctx = _quickjs().Context()
    ctx.eval(ROUTER)

    def js(expr):
        return json.loads(ctx.eval("JSON.stringify(" + expr + ")"))

    assert [p["id"] for p in js("AGXRouter.pages()")] == PAGES
    assert [p["label"] for p in js("AGXRouter.pages()")] == LABELS
    assert js('AGXRouter.parse("")') == {"page": "overview", "arg": None, "known": True}
    assert js('AGXRouter.parse("#")') == {"page": "overview", "arg": None, "known": True}
    assert js('AGXRouter.parse("#/models")') == {"page": "models", "arg": None, "known": True}
    assert js('AGXRouter.parse("#/Models/")') == {"page": "models", "arg": None, "known": True}
    assert js('AGXRouter.parse("#/models/driverguard_yolopx%401")') == \
        {"page": "models", "arg": "driverguard_yolopx@1", "known": True}
    assert js('AGXRouter.parse("#/nothing")') == {"page": "overview", "arg": None, "known": False}
    assert js('AGXRouter.parse("#/models/%E0%A4%A")') == {"page": "models", "arg": None, "known": True}
    assert js("AGXRouter.parse(null)")["page"] == "overview"
    assert js('AGXRouter.href("models", "driverguard_yolopx@1")') == "#/models/driverguard_yolopx%401"
    assert js('AGXRouter.href("nothing")') == "#/overview"
    for p in PAGES:   # href and parse agree
        assert js(f'AGXRouter.parse(AGXRouter.href("{p}", "a b@1"))') == {"page": p, "arg": "a b@1", "known": True}
    assert js('AGXRouter.label("rklink")') == "RK link" and js('AGXRouter.label("x")') == "Overview"
    # poll plan: the Models and Services data only while their page shows; Overview: a slower catalog poll
    assert js('AGXRouter.polls("models")') == {"catalog": 2000, "models": 2000, "events": 5000, "control": 5000}
    assert js('AGXRouter.polls("services")') == {"services": 5000}
    assert js('AGXRouter.polls("overview")') == {"catalog": 10000}
    for p in ("cameras", "rklink", "system", "history"):
        assert js(f'AGXRouter.polls("{p}")') == {}, p
    assert js('AGXRouter.polls("nothing")') == js('AGXRouter.polls("overview")')
    ctx.eval('var q = AGXRouter.polls("models"); q.catalog = 1;')
    assert js('AGXRouter.polls("models").catalog') == 2000            # a copy: the plan does not change
    assert js('AGXRouter.logsWanted("services", true)') is True
    assert js('AGXRouter.logsWanted("services", false)') is False
    assert js('AGXRouter.logsWanted("overview", true)') is False
    assert js("AGXRouter.LOGS_MS") == 5000


def test_app_and_router_compile_quickjs():
    ctx = _quickjs().Context()
    for name, src in (("app.js", APP), ("router.js", ROUTER), ("tiles.js", (STATIC / "tiles.js").read_text())):
        assert ctx.eval("typeof new Function(" + json.dumps(src) + ")") == "function", name


# ---------------------------------------------------------------- the page list
def test_dashboard_pages_doc_lists_each_inventory_id():
    doc = (ROOT / "docs" / "DASHBOARD_PAGES.md").read_text()
    for i in INVENTORY_IDS:
        assert f"`{i}`" in doc, i
    for label in LABELS:
        assert label in doc, label
