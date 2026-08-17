"""The virtual phone line must behave like one: real-time pacing, silence between utterances, flush on interruption."""

from __future__ import annotations

import asyncio
import time

import pytest

from voxprobe.arena.loopback import CHUNK_MS, SAMPLE_RATE, LoopbackOutputTransport, VirtualMicrophone, loopback_params

BYTES_PER_CHUNK = (SAMPLE_RATE * CHUNK_MS // 1000) * 2  # 640 bytes of 16-bit mono per 20 ms


@pytest.mark.asyncio
async def test_microphone_ticks_silence_in_real_time_when_idle():
    mic = VirtualMicrophone()
    stamps: list[float] = []
    frames: list[bytes] = []

    async def push(pcm: bytes) -> None:
        stamps.append(time.monotonic())
        frames.append(pcm)

    task = asyncio.create_task(mic.run(push))
    await asyncio.sleep(0.5)
    task.cancel()
    # ~25 ticks in 0.5 s at 20 ms cadence (allow scheduler jitter), every frame is one silent chunk
    assert 18 <= len(frames) <= 30, len(frames)
    assert all(len(f) == BYTES_PER_CHUNK and set(f) == {0} for f in frames)
    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert 0.012 <= sorted(gaps)[len(gaps) // 2] <= 0.03  # median tick ≈ 20 ms


@pytest.mark.asyncio
async def test_microphone_plays_queued_speech_at_real_time_then_returns_to_silence():
    mic = VirtualMicrophone()
    speech = b"\x01\x02" * (SAMPLE_RATE * 100 // 1000)  # 100 ms of non-silent audio = 5 chunks
    played: list[bytes] = []

    async def push(pcm: bytes) -> None:
        played.append(pcm)

    task = asyncio.create_task(mic.run(push))
    await asyncio.sleep(0.05)
    mic.add_audio(speech)
    await asyncio.sleep(0.3)
    task.cancel()
    speech_frames = [f for f in played if set(f) != {0}]
    assert len(speech_frames) == 5  # never burst: 100 ms of speech becomes exactly five 20 ms frames
    assert mic.speech_bytes_played == len(speech)
    assert set(played[-1]) == {0}  # back to silence afterwards


def test_flush_drops_unplayed_audio_and_reports_bytes():
    mic = VirtualMicrophone()
    mic.add_audio(b"\x01" * 1000)
    mic.add_audio(b"\x01" * 500)
    assert mic.flush() == 1500
    assert mic.flush() == 0
    assert mic._next_chunk() == b""  # nothing left to play


@pytest.mark.asyncio
async def test_output_transport_paces_writes_like_a_sound_card():
    out = LoopbackOutputTransport(loopback_params())
    out._send_interval = CHUNK_MS / 1000  # what start() computes for 20 ms chunks
    t0 = time.monotonic()
    for _ in range(10):
        await out._write_audio_sleep()
    elapsed = time.monotonic() - t0
    # 10 chunks × 20 ms: the first write is immediate, the rest are paced → ≈ 180 ms, never a burst
    assert 0.15 <= elapsed <= 0.35, elapsed
