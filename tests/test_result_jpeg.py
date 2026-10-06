"""tools/result_jpeg.py: frame choice (exact frameSeq match first) and nearest-result fallback. Pure logic,
no sockets, no GPU."""
from tools.result_jpeg import choose_frame, pick_results, side_record


def _r(model, seq):
    return {"model": model, "model_version": "x", "frame_seq": seq, "t_capture_ns": seq, "t_result_ns": seq,
            "frame_width": 1280, "frame_height": 720, "simulated": True, "source": "replay",
            "detections": [], "masks": [], "trajectory": None}


def test_prefers_newest_frame_with_all_models():
    hist = {"a": [_r("a", s) for s in (10, 11, 12, 13)], "b": [_r("b", s) for s in (10, 12)]}
    cands, count = choose_frame(hist, ["a", "b"])
    assert cands[0] == 12 and count[12] == 2          # newest seq with both models
    assert cands[1] == 10                              # then the older full match
    assert cands[2:] == [13, 11]                       # then single-model seqs, newest first


def test_nearest_fallback_marks_distance():
    hist = {"a": [_r("a", 20)], "b": [_r("b", 17), _r("b", 22)]}
    drawn = pick_results(hist, ["a", "b"], 20)
    by = {r["model"]: r for r in drawn}
    assert by["a"]["seq_delta"] == 0
    assert by["b"]["frame_seq"] == 22 and by["b"]["seq_delta"] == 2   # 22 is nearer than 17
    rec = side_record(0, {"seq": 20, "simulated": True}, drawn, ["a", "b"], 1)
    assert rec["exact_match"] is False and rec["models_missing"] == []


def test_missing_model_is_reported():
    hist = {"a": [_r("a", 5)]}
    drawn = pick_results(hist, ["a", "b"], 5)
    rec = side_record(1, {"seq": 5}, drawn, ["a", "b"], 1)
    assert rec["models_missing"] == ["b"] and rec["exact_match"] is False


def test_box_model_is_the_one_with_detections():
    from tools.result_jpeg import box_model
    a = _r("dtcp", 1)
    b = _r("yolopx", 1)
    b["detections"] = [{"class_name": "car"}]
    assert box_model({"dtcp": [a], "yolopx": [b]}, ["dtcp", "yolopx"]) == "yolopx"
