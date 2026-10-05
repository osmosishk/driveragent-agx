import csv, sys, collections
SP = "/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad"
ev = {l.split()[0]: float(l.split()[1]) for l in open(f"{SP}/t5_events.txt") if l.startswith("SIG")}
t_stop, t_cont = int(ev["SIGSTOP"] * 1e9), int(ev["SIGCONT"] * 1e9)
R, S = [], []
for row in csv.DictReader(open(f"{SP}/t5_rec.csv")):
    (R if row["kind"] == "R" else S).append(row)
print(f"recorder: {len(R)} results, {len(S)} status")
keys = collections.Counter((r["model"], r["cam"], r["seq"]) for r in R)
print("recorder duplicates (model,cam,frameSeq seen twice):", sum(1 for v in keys.values() if v > 1))
age_ready = [(int(r["t_result_ns"]) - int(r["t_ready_ns"])) / 1e6 for r in R]
age_recv_client = [(int(r["t_client_ns"]) - int(r["t_recv_ns"])) / 1e6 for r in R]
print(f"all results: max (tAgxResultNs - tAgxReadyNs) = {max(age_ready):.1f} ms; max (t_client - tAgxRecvNs) = {max(age_recv_client):.1f} ms")
print(f"pause: SIGSTOP at +0.000 s, SIGCONT at +{(t_cont - t_stop) / 1e9:.3f} s")
# last result per stream before / first after SIGCONT, and results in the pause window
streams = sorted({(r["model"], r["cam"]) for r in R})
print("stream                 last result before resume (t rel SIGSTOP, frame recv rel SIGSTOP, age at result)   first result after resume")
for st in streams:
    rs = [r for r in R if (r["model"], r["cam"]) == st]
    before = [r for r in rs if int(r["t_client_ns"]) < t_cont]
    after = [r for r in rs if int(r["t_client_ns"]) >= t_cont]
    lb = before[-1]; fa = after[0]
    inpause = [r for r in rs if t_stop <= int(r["t_client_ns"]) < t_cont]
    print(f"{st[0]:18} cam{st[1]}  last: client {(int(lb['t_client_ns'])-t_stop)/1e9:+.3f} s, frame recv {(int(lb['t_recv_ns'])-t_stop)/1e9:+.3f} s, "
          f"seq {lb['seq']}, frame age at result {(int(lb['t_result_ns'])-int(lb['t_ready_ns']))/1e6:.1f} ms | "
          f"results in pause window {len(inpause)} | first after: client {(int(fa['t_client_ns'])-t_stop)/1e9:+.3f} s seq {fa['seq']} "
          f"(seq jump {int(fa['seq'])-int(lb['seq'])}), frame recv {(int(fa['t_recv_ns'])-t_stop)/1e9:+.3f} s")
# results received in the pause window with frame received before SIGSTOP
win = [r for r in R if t_stop <= int(r["t_client_ns"]) < t_cont]
old = [r for r in win if (int(r["t_client_ns"]) - int(r["t_recv_ns"])) > 500e6]
print(f"results received between SIGSTOP and SIGCONT: {len(win)}; of these, frame received at the AGX > 500 ms before: {len(old)}")
if win:
    print(f"  latest result in the window: {(max(int(r['t_client_ns']) for r in win)-t_stop)/1e6:.1f} ms after SIGSTOP; "
          f"max e2e_recv in window {max((int(r['t_client_ns'])-int(r['t_recv_ns']))/1e6 for r in win):.1f} ms")
print("status messages from SIGSTOP-1 s to SIGCONT+2 s (camera state:frameAgeMs):")
for s in S:
    t = int(s["t_client_ns"])
    if t_stop - 1e9 <= t <= t_cont + 2e9:
        print(f"  {(t - t_stop)/1e9:+.3f} s node {s['model']} | {s['cam']} | {s['seq']}")
