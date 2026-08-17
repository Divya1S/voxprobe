"""Dev tool: build a synthetic stereo "call" (LEFT = agent, RIGHT = patient) with macOS `say`, plus the meta/events files
the post-call pipeline expects — so `voxprobe analyze` can be exercised with zero telephony spend.

Usage:  uv run python scripts/make_synthetic_call.py
Produces recordings/call-00-synthetic-<date>-synth0.mp3 and the matching reports/*.meta.json.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from voxprobe.config import load_settings  # noqa: E402

# (speaker, gap_before_seconds, text). Gaps model realistic response latency; one deliberate overlap and one long silence.
SCRIPT = [
    ("AGENT", 0.5, "Thank you for calling Sunrise Orthopedics. This call may be recorded. May I have your first and last name?"),
    ("PATIENT", 0.8, "Hi, sure. It's Maya Thompson. I'm calling because my knee's been hurting and I'd like to book a first appointment."),
    ("AGENT", 1.1, "Thanks Maya. Could I get your date of birth?"),
    ("PATIENT", 0.7, "March twelfth, nineteen ninety-one."),
    ("AGENT", 3.2, "Great. We have Sunday at nine in the morning with Doctor Chen. Does that work?"),
    ("PATIENT", 0.9, "Sunday at nine works. What should I bring?"),
    ("AGENT", 1.0, "Bring a photo ID and your insurance card, and arrive fifteen minutes early. Is there anything else I can help with?"),
    ("PATIENT", -0.6, "No, that's all. Thanks so much, bye now."),
    ("AGENT", 0.8, "You're welcome. Goodbye."),
]
VOICES = {"AGENT": "Samantha", "PATIENT": "Daniel"}


def say(text: str, voice: str, out: Path) -> float:
    subprocess.run(["say", "-v", voice, "-o", str(out), "--data-format=LEI16@16000", text], check=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(dur)


def main() -> None:
    settings = load_settings()
    tmp = Path(tempfile.mkdtemp(prefix="voxprobe-synth-"))
    # Build a timeline: absolute start times per utterance
    t = 0.0
    items = []
    for i, (spk, gap, text) in enumerate(SCRIPT):
        wav = tmp / f"u{i}.wav"
        dur = say(text, VOICES[spk], wav)
        start = max(0.0, t + gap)
        items.append((spk, start, dur, wav))
        t = start + dur
    total = t + 1.0
    # Mix each channel: adelay each utterance to its start, sum, pad to total
    def channel(spk: str, out: Path) -> None:
        ins, filters, labels = [], [], []
        for k, (s, start, dur, wav) in enumerate([x for x in items if x[0] == spk]):
            ins += ["-i", str(wav)]
            filters.append(f"[{k}:a]adelay={int(start*1000)}|{int(start*1000)}[a{k}]")
            labels.append(f"[a{k}]")
        n = len(labels)
        fc = ";".join(filters) + f";{''.join(labels)}amix=inputs={n}:normalize=0,apad=whole_dur={total}[out]"
        subprocess.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", fc, "-map", "[out]", "-ar", "16000", "-ac", "1", str(out)], check=True)
    left, right = tmp / "left.wav", tmp / "right.wav"
    channel("AGENT", left)
    channel("PATIENT", right)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    stem = f"call-00-synthetic-{day}-synth0"
    settings.recordings_dir.mkdir(exist_ok=True)
    mp3 = settings.recordings_dir / f"{stem}.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(left), "-i", str(right),
                    "-filter_complex", "[0:a][1:a]join=inputs=2:channel_layout=stereo[a]", "-map", "[a]", "-b:a", "96k", str(mp3)], check=True)
    # meta + a couple of fake brain events so metrics can be exercised
    settings.reports_dir.mkdir(exist_ok=True)
    (settings.reports_dir / "events").mkdir(exist_ok=True)
    events = settings.reports_dir / "events" / "synthetic-call.jsonl"
    with events.open("w") as f:
        for i in range(4):
            f.write(json.dumps({"type": "brain-turn", "turn": i + 1, "provider": "groq", "model": "llama-3.3-70b-versatile",
                                "latency_ms": 300 + 40 * i, "prompt_tokens": 650 + 60 * i, "failed_over_from": []}) + "\n")
    meta = {"stem": stem, "scenario_id": "01-schedule-new-patient", "target_id": "local-clinic", "title": "SYNTHETIC — pipeline smoke test",
            "call_id": "synthetic-call", "started_at": datetime.now(timezone.utc).isoformat(), "ended_at": None,
            "ended_reason": "synthetic", "from": settings.caller_number or "local", "to": "local-clinic", "cost_usd": 0,
            "performance_metrics": None, "files": {"recording_mp3": f"recordings/{stem}.mp3", "transcript_md": None,
                                                   "call_json": None, "events_jsonl": "reports/events/synthetic-call.jsonl"}}
    (settings.reports_dir / f"{stem}.meta.json").write_text(json.dumps(meta, indent=2))
    print(f"synthetic call → {mp3.relative_to(settings.repo_root)}  ({total:.1f}s)   stem={stem}")


if __name__ == "__main__":
    main()
