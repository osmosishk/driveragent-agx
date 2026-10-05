#!/usr/bin/env bash
# T5 orchestration: client 120 s + recorder + SIGSTOP/SIGCONT of agx-sim at about t=60 s.
set -u
P=/home/tonyho/driveragent-agx; SP=/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad
cd $P
export PYTHONPATH=$P
drops() { .venv/bin/python -m tools.model_ctl --json list | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print(' '.join(f\"{m['name']}:total={m.get('results_total')},dropped_stale={m.get('results_dropped_stale')},dropped_old={m.get('results_dropped_old')}\" for m in d['models'] if m.get('state')=='RUNNING'))"; }
echo "before: $(date +%T.%3N) $(drops)" > $SP/t5_events.txt
.venv/bin/python $SP/rec_results.py 127.0.0.1 124 $SP/t5_rec.csv &
RP=$!
sleep 1
echo "client start $(date +%s.%N)" >> $SP/t5_events.txt
.venv/bin/python -m tools.rk_result_client --host 127.0.0.1 --seconds 120 --json $P/docs/test_results/t5_client.json > $P/docs/test_results/t5_client.log 2>&1 &
CP=$!
sleep 60
echo "SIGSTOP $(date +%s.%N)" >> $SP/t5_events.txt
systemctl --user kill -s SIGSTOP agx-sim
sleep 3
systemctl --user kill -s SIGCONT agx-sim
echo "SIGCONT $(date +%s.%N)" >> $SP/t5_events.txt
wait $CP; echo "client exit code $?" >> $SP/t5_events.txt
wait $RP
echo "after: $(date +%T.%3N) $(drops)" >> $SP/t5_events.txt
