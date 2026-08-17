"""Authoritative transcript from the AUDIO, not from the live relay.

Why: the live transcript is a log of intent (what was generated / what STT heard first-pass), not a record of what
actually aired. Interrupted sentences, mis-heard names and numbers, and processing-time timestamps all lie a
little. Bugs are only filed against audio-derived text with timestamps.

How (two sources of truth, each used for what it is good at):
1. TIMING from the audio energy: split the stereo MP3 (LEFT = agent, RIGHT = patient) into mono tracks and run
   ffmpeg `silencedetect` on each to get speech regions. Turn-taking metrics come from these regions.
2. WORDS from Whisper: each speech region is cut out and transcribed on its own (Groq `whisper-large-v3-turbo`).
   Transcribing whole tracks with long silences makes Whisper drift and hallucinate; per-region clips do not.
Speaker attribution is the channel itself — no diarization guesswork.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from openai import OpenAI, RateLimitError

from .brain import GROQ_BASE_URL
from .config import Settings

WHISPER_MODEL = "whisper-large-v3-turbo"
SILENCE_DB = -32  # below this is "silence" (phone audio is quiet; tune if a channel is very hot/cold)
MIN_SILENCE_S = 0.45  # a pause shorter than this does not split a turn
MIN_SPEECH_S = 0.35  # ignore blips shorter than this
PAD_S = 0.15  # padding around each clip so Whisper hears word onsets/offsets
MIN_REQUEST_GAP_S = 3.1  # Groq free tier: ~20 Whisper requests/min


@dataclass
class Segment:
    start: float
    end: float
    speaker: str  # "AGENT" | "PATIENT"
    text: str


def split_stereo(mp3: Path, out_dir: Path) -> tuple[Path, Path]:
    """LEFT channel -> <stem>-L.wav (agent), RIGHT -> <stem>-R.wav (patient). 16 kHz mono PCM."""
    out_dir.mkdir(parents=True, exist_ok=True)
    left, right = out_dir / f"{mp3.stem}-L.wav", out_dir / f"{mp3.stem}-R.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(mp3),
            "-filter_complex",
            "[0:a]channelsplit=channel_layout=stereo[L][R]",
            "-map",
            "[L]",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(left),
            "-map",
            "[R]",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(right),
        ],
        check=True,
    )
    return left, right


def _duration(wav: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out or 0)


def speech_regions(
    wav: Path, silence_db: int = SILENCE_DB, min_silence_s: float = MIN_SILENCE_S
) -> list[tuple[float, float]]:
    """Speech regions (start, end) from ffmpeg silencedetect — the inverse of the silence intervals."""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(wav),
            "-af",
            f"silencedetect=noise={silence_db}dB:d={min_silence_s}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    log_text = proc.stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log_text)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log_text)]
    total = _duration(wav)
    silences: list[tuple[float, float]] = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else total
        silences.append((s, e))
    regions: list[tuple[float, float]] = []
    cursor = 0.0
    for s, e in silences:
        if s - cursor >= MIN_SPEECH_S:
            regions.append((cursor, s))
        cursor = e
    if total - cursor >= MIN_SPEECH_S:
        regions.append((cursor, total))
    return regions


def _cut(wav: Path, start: float, end: float, out: Path) -> Path:
    s = max(0.0, start - PAD_S)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            f"{s:.3f}",
            "-t",
            f"{end - s + PAD_S:.3f}",
            "-i",
            str(wav),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(out),
        ],
        check=True,
    )
    return out


class _Pacer:
    def __init__(self, gap: float):
        self.gap, self.last = gap, 0.0

    def wait(self) -> None:
        dt = time.monotonic() - self.last
        if dt < self.gap:
            time.sleep(self.gap - dt)
        self.last = time.monotonic()


def transcribe_clip(client: OpenAI, clip: Path, prompt: str, pacer: _Pacer) -> str:
    for attempt in range(3):
        pacer.wait()
        try:
            with clip.open("rb") as f:
                resp = client.audio.transcriptions.create(
                    model=WHISPER_MODEL,
                    file=f,
                    response_format="json",
                    language="en",
                    temperature=0.0,
                    prompt=prompt or None,
                )
            return (resp.text or "").strip()
        except RateLimitError:
            time.sleep(10 * (attempt + 1))
    return ""


def transcribe_track(client: OpenAI, wav: Path, speaker: str, prompt: str, work: Path, pacer: _Pacer) -> list[Segment]:
    out: list[Segment] = []
    for i, (s, e) in enumerate(speech_regions(wav)):
        clip = _cut(wav, s, e, work / f"{wav.stem}-{i:03d}.wav")
        text = transcribe_clip(client, clip, prompt, pacer)
        text = re.sub(r"\s+", " ", text).strip()
        if text and not _looks_like_hallucination(text):
            out.append(Segment(round(s, 2), round(e, 2), speaker, text))
    return out


_HALLU = re.compile(r"^(thank you\.?|thanks for watching\.?|\.+|you\.?|bye\.?)$", re.I)


def _looks_like_hallucination(text: str) -> bool:
    return bool(_HALLU.match(text.strip())) and len(text) < 20


def merge(agent: list[Segment], patient: list[Segment]) -> list[Segment]:
    return sorted(agent + patient, key=lambda s: (s.start, s.end))


def render_md(stem: str, segments: list[Segment]) -> str:
    lines = [
        f"# {stem} — authoritative transcript (Whisper per speech region, per channel)",
        "",
        "Timestamps = seconds into the recording, from the audio energy of each channel. "
        "AGENT = left channel (target agent); PATIENT = right channel (our bot).",
        "",
    ]
    for s in segments:
        lines.append(f"[{int(s.start) // 60:02d}:{int(s.start) % 60:02d}] {s.speaker:7s}: {s.text}")
    return "\n".join(lines) + "\n"


def retranscribe(settings: Settings, mp3: Path, stem: str, hint: str = "") -> dict:
    """Produce transcripts/<stem>.whisper.md + .whisper.json. Returns the dict that was written."""
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY needed for Whisper re-transcription")
    client = OpenAI(base_url=GROQ_BASE_URL, api_key=settings.groq_api_key, timeout=120, max_retries=0)
    work = settings.recordings_dir / "raw" / f"{stem}-clips"
    work.mkdir(parents=True, exist_ok=True)
    left, right = split_stereo(mp3, settings.recordings_dir / "raw")
    pacer = _Pacer(MIN_REQUEST_GAP_S)
    agent = transcribe_track(client, left, "AGENT", hint, work, pacer)
    patient = transcribe_track(client, right, "PATIENT", hint, work, pacer)
    merged = merge(agent, patient)
    md_path = settings.transcripts_dir / f"{stem}.whisper.md"
    md_path.write_text(render_md(stem, merged))
    data = {
        "stem": stem,
        "model": WHISPER_MODEL,
        "timing": "ffmpeg silencedetect per channel",
        "segments": [asdict(s) for s in merged],
    }
    (settings.transcripts_dir / f"{stem}.whisper.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return data
