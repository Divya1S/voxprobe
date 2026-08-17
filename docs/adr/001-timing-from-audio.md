# ADR-001 — Timing from audio energy, words from Whisper

**Status:** accepted (2026-08-16) · **Context:** transcripts drive every metric and every finding.

## Problem
The first transcriber ran Whisper over each whole channel and used Whisper's segment timestamps. On a synthetic stereo call
with scripted gaps it dropped two agent lines and mis-stamped the rest (Whisper drifts across long silences), which made the
turn-taking metrics garbage and the judge blame the agent for "ending the call abruptly".

## Decision
Split responsibilities:
- **timing** — `ffmpeg silencedetect` per channel (noise −32 dB, min silence 0.45 s, min speech 0.35 s) yields speech regions;
- **words** — Whisper transcribes each region as its own clip (+150 ms padding), stamped with the region's start.

Speaker attribution is the channel itself (L = agent, R = caller); no diarization guesswork.

## Consequences
- On the synthetic fixture the scripted 0.8 / 0.7 / 0.9 s response gaps measured 0.88 / 0.91 / 1.04 s; a scripted 3.2 s silence
  measured 3.25 s; a scripted 0.6 s overlap measured 0.51 s. (Becoming golden tests in P4.)
- Region-per-request means ~20 Whisper calls per call; Groq's free tier is paced at ~3 s/request in `retranscribe.py`.
- Live transcripts are still saved (they show what each side *heard*) but findings cite the audio-derived one only.
