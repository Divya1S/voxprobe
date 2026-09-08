"""Idempotency probe: POST the same /v1/calls request twice with the same Idempotency-Key, back to back.

Docs promise: retries with the same key + body are safe. If honored, the second create returns the same call id and no second
call is placed (cost: 1 call). If not, two calls ring the line (cost: 2) — which would be a top-tier feedback item.
Run only with the line up (it dials the allow-listed test number). Evidence lands in reports/calle/<stem>.calle.json + a
sidecar <stem>.idempotency.json.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import UTC, datetime

from voxprobe import calle_client
from voxprobe.config import assert_allowed_target, load_settings
from voxprobe.scenarios import find_scenario


def main() -> int:
    settings = load_settings()
    scenario = find_scenario(settings.scenarios_dir, "02")
    number = assert_allowed_target(settings.calle_target_number, settings.allowed_numbers)
    payload = calle_client.dry_run(scenario, number, "Sunrise Orthopedics")
    key = f"voxprobe-idem-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
    client = calle_client._client(settings)
    try:
        t0 = time.time()
        first = client.calls.create(
            task=payload["task"],
            recipients=payload["recipients"],
            result_schema=payload["result_schema"],
            metadata={**payload["metadata"], "probe": "idempotency"},
            idempotency_key=key,
        )
        t1 = time.time()
        try:
            second = client.calls.create(
                task=payload["task"],
                recipients=payload["recipients"],
                result_schema=payload["result_schema"],
                metadata={**payload["metadata"], "probe": "idempotency"},
                idempotency_key=key,
            )
            second_err = None
        except Exception as e:  # noqa: BLE001 - record whatever the API says
            second, second_err = (
                None,
                {k: getattr(e, k, None) for k in ("status_code", "code", "message")} | {"str": str(e)[:300]},
            )
        t2 = time.time()
        same = bool(second) and second.get("id") == first.get("id")
        print(
            f"first id {first.get('id')} ({t1 - t0:.2f}s); second: {'same id' if same else (second.get('id') if second else second_err)} ({t2 - t1:.2f}s)"
        )
        task = client.calls.wait_for_result(first["id"], interval_seconds=3.0, timeout_seconds=540)
        events = client.calls.list_events(first["id"], limit=100).get("data") or []
    finally:
        client.close()
    stem = key.replace("voxprobe-idem", "calle-idem")
    out = settings.reports_dir / "calle"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.calle.json").write_text(
        json.dumps(
            {
                "stem": stem,
                "scenario": scenario.id,
                "request": payload,
                "created": first,
                "task": task,
                "events": events,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    (out / f"{stem}.idempotency.json").write_text(
        json.dumps(
            {
                "key": key,
                "first": first,
                "second": second,
                "second_error": second_err,
                "same_id": same,
                "t_first_s": round(t1 - t0, 2),
                "t_second_s": round(t2 - t1, 2),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(
        f"IDEMPOTENCY same_id={same} status={task.get('status')} task_completed={task.get('task_completed')} → {out / (stem + '.idempotency.json')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
