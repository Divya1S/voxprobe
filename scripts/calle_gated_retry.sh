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
  out=$(calle mcp call plan_call --args-json '{"user_input":"Call +12025550123 and ask whether the clinic is open on Saturday, then end the call politely.","to_phones":["+12025550123"],"region":"US","language":"en"}' --json 2>&1)
  if echo "$out" | grep -q "credit_balance_exhausted\|insufficient_quota\|Error calling tool"; then
    echo "$(date '+%H:%M:%S') probe $n: planner still down ($(echo "$out" | grep -oE 'status_code: [0-9]+' | head -1))"
    sleep "$INTERVAL"; continue
  fi
  echo "$(date '+%H:%M:%S') probe $n: planner answered without the 429 — placing call #1 now"
  echo "$out" | head -c 600; echo
  uv run voxprobe calle run --scenario "$SCENARIO" --yes --timeout 540
  echo "GATED-RETRY-DONE exit=$?"
  exit 0
done
echo "GATED-RETRY-GAVE-UP after $n probes"
