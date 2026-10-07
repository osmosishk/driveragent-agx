"""T1 test: docs/MODELS.md lists each engine file of the old model folder with its input and output tensors
(name, shape, type) as read from the REAL file now (tools.inspect_engines deserializes each engine).
The old model folder is machine data of AGX02 (docs/MODELS.md): AGX_OLD_MODELS, default /home/tonyho/model.
The test is skipped when that folder does not exist (another unit, a fresh clone)."""
import os
import re

import pytest

from tools import inspect_engines as ie

DOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "MODELS.md")
OLD_MODELS = os.environ.get("AGX_OLD_MODELS", "/home/tonyho/model")


@pytest.mark.skipif(not os.path.isdir(OLD_MODELS), reason=f"{OLD_MODELS} does not exist (the old engines of AGX02)")
def test_every_engine_and_tensor_is_in_models_md():
    text = open(DOC, encoding="utf-8").read()
    norm = re.sub(r"\s+", "", text)  # shapes may be written "(1, 3, 384, 640)" or "1x3x384x640"
    engines = ie.scan([OLD_MODELS])
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
