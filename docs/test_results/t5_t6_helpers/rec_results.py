"""Helper for T5: record the times of every result and the camera states of every status (CSV).
It strips the 32-byte envelope without checks (the RK result client does the envelope checks)."""
import sys, time, csv
import capnp, zmq

host, seconds, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
mod = capnp.load("/home/tonyho/driveragent-agx/proto/agx_infer.capnp")
ctx = zmq.Context()
socks = {}
for port, kind in ((5560, "R"), (5561, "S")):
    s = ctx.socket(zmq.SUB); s.setsockopt(zmq.SUBSCRIBE, b""); s.setsockopt(zmq.RCVHWM, 100000)
    s.connect(f"tcp://{host}:{port}"); socks[s] = kind
poller = zmq.Poller()
for s in socks: poller.register(s, zmq.POLLIN)
t_end = time.monotonic() + seconds
with open(out, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["kind", "t_client_ns", "model", "cam", "seq", "t_cap_ns", "t_recv_ns", "t_ready_ns", "t_result_ns"])
    while time.monotonic() < t_end:
        for s, _ in poller.poll(200):
            buf = s.recv(); tc = time.time_ns()
            if socks[s] == "R":
                with mod.AgxPerceptionResult.from_bytes(buf[32:]) as m:
                    w.writerow(["R", tc, m.model, m.camId, m.frameSeq, m.tCaptureNs, m.tAgxRecvNs, m.tAgxReadyNs, m.tAgxResultNs])
            else:
                with mod.AgxInferStatus.from_bytes(buf[32:]) as m:
                    w.writerow(["S", tc, m.nodeState, " ".join(f"{c.camId}:{c.state}:{c.frameAgeMs:.0f}" for c in m.cameras),
                                " ".join(f"{x.name}:{x.state}:{x.fps:.1f}" for x in m.models), "", "", "", m.tStatusNs])
for s in socks: s.close(0)
ctx.term()
