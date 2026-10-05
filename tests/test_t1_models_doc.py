"""T1 test: docs/MODELS.md lists each engine file on this machine with its input and output tensors
(name, shape, type) as read from the REAL file now (tools.inspect_engines deserializes each engine)."""
import os
import re

from tools import inspect_engines as ie

DOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "MODELS.md")


def test_every_engine_and_tensor_is_in_models_md():
    text = open(DOC, encoding="utf-8").read()
    norm = re.sub(r"\s+", "", text)  # shapes may be written "(1, 3, 384, 640)" or "1x3x384x640"
    engines = ie.scan(ie.DEFAULT_SCAN)
    assert len(engines) >= 5, engines
    missing = []
    for path in engines:
        info = ie.inspect(path)
        assert info["load"] == "OK", (path, info.get("error"))
        if path not in text:
            missing.append(("engine", path))
        for t in info["io"]:
            shape_a = "(" + ",".join(str(x) for x in t["shape"]) + ")"
            shape_b = "x".join(str(x) for x in t["shape"])
            if t["name"] not in text or (shape_a not in norm and shape_b not in norm) or t["dtype"] not in text:
                missing.append((path, t["name"], t["shape"], t["dtype"]))
    assert not missing, missing
