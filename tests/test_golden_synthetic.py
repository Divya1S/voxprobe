"""Golden calibration test for the measurement pipeline — no API keys, ffmpeg only.

tests/fixtures/synthetic-stereo-call.mp3 was built by scripts/make_synthetic_call.py: macOS `say` voices, agent on the LEFT
channel, caller on the RIGHT, with SCRIPTED response gaps (0.8 / 1.1 / 0.7 / 3.2 / 0.9 / 1.0 / −0.6 / 0.8 s). The scripted
values are the ground truth; the pipeline's speech-region timing must reproduce them within a tolerance that covers TTS
onset ramps and the 0.45 s silence threshold. This is what makes "timing from audio" a checked claim rather than a slogan.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from voxprobe.metrics import compute
from voxprobe.retranscribe import speech_regions, split_stereo

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic-stereo-call.mp3"
# (speaker of the NEXT turn, scripted gap seconds) in conversation order — from make_synthetic_call.SCRIPT
SCRIPTED_GAPS = [
    ("PATIENT", 0.8),
    ("AGENT", 1.1),
    ("PATIENT", 0.7),
    ("AGENT", 3.2),
    ("PATIENT", 0.9),
    ("AGENT", 1.0),
    ("PATIENT", -0.6),
    ("AGENT", 0.8),
]
TOL = 0.25  # seconds: TTS onset/offset ramps + region padding

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def timeline(tmp_path_factory):
    work = tmp_path_factory.mktemp("golden")
    left, right = split_stereo(FIXTURE, work)
    agent = [{"speaker": "AGENT", "start": a, "end": b, "text": "…"} for a, b in speech_regions(left)]
    caller = [{"speaker": "PATIENT", "start": a, "end": b, "text": "…"} for a, b in speech_regions(right)]
    return sorted(agent + caller, key=lambda s: s["start"])


def test_every_scripted_utterance_is_found_as_one_region(timeline):
    speakers = [s["speaker"] for s in timeline]
    assert speakers == ["AGENT", "PATIENT", "AGENT", "PATIENT", "AGENT", "PATIENT", "AGENT", "PATIENT", "AGENT"]


def test_measured_response_gaps_match_the_script(timeline):
    measured = []
    for prev, nxt in zip(timeline, timeline[1:], strict=False):
        measured.append((nxt["speaker"], round(nxt["start"] - prev["end"], 2)))
    assert len(measured) == len(SCRIPTED_GAPS)
    for (spk_m, gap_m), (spk_s, gap_s) in zip(measured, SCRIPTED_GAPS, strict=True):
        assert spk_m == spk_s
        assert abs(gap_m - gap_s) <= TOL, f"{spk_s}: scripted {gap_s} s, measured {gap_m} s"


def test_metrics_report_the_planted_dead_air_and_overlap(timeline):
    m = compute(timeline)
    assert m["turns"] == {"AGENT": 5, "PATIENT": 4}
    # the 3.2 s scripted silence before the agent's third line → dead air attributed to the AGENT
    assert len(m["dead_air"]) == 1
    assert m["dead_air"][0]["slow_party"] == "AGENT" and abs(m["dead_air"][0]["gap_s"] - 3.2) <= TOL
    # the −0.6 s scripted talk-over → one overlap started by the caller (PATIENT)
    assert len(m["overlaps"]) == 1
    assert m["overlaps"][0]["who_started"] == "PATIENT" and abs(m["overlaps"][0]["overlap_s"] - 0.6) <= TOL
    # medians: caller gaps scripted 0.8/0.7/0.9/(−0.6) → p50 ≈ 0.75±; agent gaps 1.1/3.2/1.0/0.8 → p50 ≈ 1.05
    assert abs(m["patient_response"]["p50_s"] - 0.75) <= 0.35
    assert abs(m["agent_response"]["p50_s"] - 1.05) <= 0.35
