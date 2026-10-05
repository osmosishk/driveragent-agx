import time, collections, capnp, zmq
mod = capnp.load("/home/tonyho/driveragent-agx/proto/agx_infer.capnp")
s = zmq.Context().socket(zmq.SUB); s.setsockopt(zmq.SUBSCRIBE, b""); s.connect("tcp://127.0.0.1:5560")
c = collections.Counter(); ex = {}
t = time.monotonic() + 5
while time.monotonic() < t:
    if not s.poll(200): continue
    with mod.AgxPerceptionResult.from_bytes(s.recv()[32:]) as m:
        for k in m.masks:
            c[(m.model, m.camId, k.name)] += 1
            ex.setdefault(k.name, f"{k.width}x{k.height} enc={k.encoding} {len(k.data)} B")
        c[(m.model, m.camId, "results")] += 1
for k in sorted(c): print(k, c[k])
print(ex)
