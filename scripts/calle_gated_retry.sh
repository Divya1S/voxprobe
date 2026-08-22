#!/usr/bin/env bash
# Gate CALL-E call #1 on planner health: probe plan_call via MCP (no dial, no CallTask) every INTERVAL seconds;
# when the planner stops answering with the upstream 429, place the real call once via `voxprobe calle run`.
set -u
export CALLE_SOURCE=skills_sh CALLE_INTEGRATION=skills_sh_skill CALLE_INTEGRATION_VERSION=0.1.0
SCENARIO="${1:-02}"; INTERVAL="${2:-600}"; MAX_HOURS="${3:-10}"
deadline=$(( $(date +%s) + MAX_HOURS*3600 ))
n=0
while [ "$(date +%s)" -lt "$deadline" ]; do
  n=$((n+1))
  out=$(calle mcp call plan_call --timeout-seconds 90 --args-json '{"user_input":"Call +12025550123 and ask whether the clinic is open on Saturday, then end the call politely.","to_phones":["+12025550123"],"region":"US","language":"en"}' --json 2>&1)
  # UP only when plan_call returned a real plan (ready_to_run / plan_id / questions); timeouts, 429s and any isError are DOWN
  if echo "$out" | grep -qE '"(ready_to_run|plan_id|questions)"' && ! echo "$out" | grep -qE 'isError": ?true|credit_balance_exhausted|insufficient_quota|Error calling tool|timed out'; then
    echo "$(date '+%H:%M:%S') probe $n: planner returned a real plan — placing call #1 now"
  else
    why=$(echo "$out" | grep -oE 'status_code: [0-9]+|timed out[a-z ]*|credit_balance_exhausted' | head -1)
    echo "$(date '+%H:%M:%S') probe $n: planner still down (${why:-no plan in response})"
    sleep "$INTERVAL"; continue
  fi
  echo "$out" | head -c 600; echo
  for k in 1 2 3; do
    uv run voxprobe calle run --scenario "$SCENARIO" --yes --timeout 540 && { echo "GATED-RETRY-DONE exit=0"; exit 0; }
    echo "$(date '+%H:%M:%S') calle run failed (try $k) — waiting 120s"; sleep 120
  done
  echo "GATED-RETRY-DONE exit=1 (3 run failures after planner came back)"; exit 1
done
echo "GATED-RETRY-GAVE-UP after $n probes"
