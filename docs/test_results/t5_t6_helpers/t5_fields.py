"""Helper for T5 Section 6 checklist: decode one result per model (envelope checked with the RK
reference dabus_envelope.unpack) and one status, and print the fields. No control values (R8)."""
import sys, time, importlib.util
import capnp, zmq
spec = importlib.util.spec_from_file_location("dabus_envelope", "/home/tonyho/driveragent-agx/common/dabus_envelope.py")
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
mod = capnp.load("/home/tonyho/driveragent-agx/proto/agx_infer.capnp")
ctx = zmq.Context()
def sub(port):
    s = ctx.socket(zmq.SUB); s.setsockopt(zmq.SUBSCRIBE, b""); s.connect(f"tcp://127.0.0.1:{port}"); return s
rs, ss = sub(5560), sub(5561)
want = {"driverguard_yolopx", "driverguard_dtcp"}; seen = set(); t_end = time.monotonic() + 10
while seen != want and time.monotonic() < t_end:
    if not rs.poll(200): continue
    buf = rs.recv()
    e = d.unpack(buf)
    with mod.AgxPerceptionResult.from_bytes(e["payload"]) as m:
        if m.model in seen or (m.model == "driverguard_yolopx" and len(m.detections) == 0): continue
        seen.add(m.model)
        print(f"=== SIMULATED result (source={m.source}, simulated={m.simulated}) envelope: { {k: (hex(v) if k == 'schema_hash' else v) for k, v in e.items() if k != 'payload'} }")
        print(f"schemaVersion={m.schemaVersion} model={m.model} modelVersion={m.modelVersion} camId={m.camId}")
        print(f"frameSeq={m.frameSeq} tCaptureNs={m.tCaptureNs} tAgxRecvNs={m.tAgxRecvNs} tAgxReadyNs={m.tAgxReadyNs} tAgxResultNs={m.tAgxResultNs}")
        print(f"frameWidth x frameHeight = {m.frameWidth} x {m.frameHeight}")
        print(f"detections: {len(m.detections)}")
        for x in list(m.detections)[:3]:
            print(f"  classId={x.classId} className={x.className} score={x.score:.3f} box=({x.x1:.1f},{x.y1:.1f},{x.x2:.1f},{x.y2:.1f}) trackId={x.trackId}")
        t = m.trajectory
        print(f"trajectory: points={len(t.points)} inputsValid={t.inputsValid}")
        print(f"  frame='{t.frame}'")
        print(f"  note='{t.note}'")
        print(f"masks: " + ", ".join(f"{k.name} {k.width}x{k.height} enc={k.encoding} {len(k.data)} B" for k in m.masks))
        tm = m.timing
        print(f"timing ms: queue={tm.queueMs:.1f} pre={tm.preMs:.1f} infer={tm.inferMs:.1f} post={tm.postMs:.1f} total={tm.totalMs:.1f}")
ss.poll(3000); buf = ss.recv(); e = d.unpack(buf)
with mod.AgxInferStatus.from_bytes(e["payload"]) as s:
    print(f"=== status: schemaVersion={s.schemaVersion} host={s.hostname} version={s.version} nodeState={s.nodeState} simulated={s.simulated} sourceMode={s.sourceMode} uptimeS={s.uptimeS} resultsPort={s.resultsPort} subscribers={s.resultSubscribers} rateHz={s.resultsRateHz:.1f}")
    print("  cameras: " + " ".join(f"{c.camId}/{c.role}:{c.state}:{c.fps:.1f}fps" for c in s.cameras))
    print("  models: " + " ".join(f"{x.name}:{x.state}" for x in s.models))
    print("  temps: " + " ".join(f"{x.zone}={x.celsius:.1f}C" for x in s.temps))
    print(f"  errors: {list(s.errors)}")
