"""Proof-of-concept for the loopback transport: caller TTS -> virtual phone line -> agent STT/VAD/recorder.

Asserts (printed): the agent hears a user turn start/stop roughly one utterance apart in wall-clock time,
transcribes it, records it on the LEFT channel, and the run takes real time (pacing works).
Usage: uv run python scripts/arena_poc.py
"""

from __future__ import annotations

import asyncio
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loguru import logger  # noqa: E402
from pipecat.audio.vad.silero import SileroVADAnalyzer  # noqa: E402
from pipecat.audio.vad.vad_analyzer import VADParams  # noqa: E402
from pipecat.frames.frames import TTSSpeakFrame  # noqa: E402
from pipecat.pipeline.pipeline import Pipeline  # noqa: E402
from pipecat.pipeline.worker import PipelineParams, PipelineWorker  # noqa: E402
from pipecat.processors.aggregators.llm_context import LLMContext  # noqa: E402
from pipecat.processors.aggregators.llm_response_universal import (  # noqa: E402
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor  # noqa: E402
from pipecat.processors.filters.null_filter import NullFilter  # noqa: E402
from pipecat.services.deepgram.stt import DeepgramSTTService  # noqa: E402
from pipecat.services.deepgram.tts import DeepgramTTSService  # noqa: E402
from pipecat.turns.user_start.vad_user_turn_start_strategy import VADUserTurnStartStrategy  # noqa: E402
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (  # noqa: E402
    SpeechTimeoutUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies  # noqa: E402
from pipecat.workers.runner import WorkerRunner  # noqa: E402

from voxprobe.arena.loopback import SAMPLE_RATE, LoopbackTransport, link  # noqa: E402
from voxprobe.config import load_settings  # noqa: E402

UTTERANCE = "Hi, my name is Maya Thompson and I'd like to book an appointment for my knee, please."


async def main() -> None:
    settings = load_settings()
    assert settings.deepgram_api_key, "DEEPGRAM_API_KEY needed"
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss.SSS} {level:<7} {name}:{line} {message}")

    caller_tx, agent_tx = LoopbackTransport(name="caller"), LoopbackTransport(name="agent")
    link(caller_tx, agent_tx)

    # --- caller: just speaks one line ---
    caller_tts = DeepgramTTSService(
        api_key=settings.deepgram_api_key,
        sample_rate=SAMPLE_RATE,
        settings=DeepgramTTSService.Settings(voice="aura-2-thalia-en"),
    )
    caller = Pipeline([caller_tx.input(), caller_tts, caller_tx.output()])

    # --- agent: listens, detects the turn, transcribes, records ---
    stt = DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramSTTService.Settings(model="nova-3", language="en", interim_results=True, smart_format=False),
    )
    context = LLMContext()
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.3)),
            user_turn_strategies=UserTurnStrategies(
                start=[VADUserTurnStartStrategy(enable_interruptions=True)],
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)],
            ),
        ),
    )
    recorder = AudioBufferProcessor(sample_rate=SAMPLE_RATE, num_channels=2, auto_start_recording=True)
    agent = Pipeline([agent_tx.input(), stt, user_agg, NullFilter(), agent_tx.output(), recorder, assistant_agg])

    t0 = time.monotonic()
    events: dict = {}
    done = asyncio.Event()

    @user_agg.event_handler("on_user_turn_started")
    async def _started(agg, *args):
        events["started_at"] = time.monotonic() - t0
        print(f"[agent] user turn STARTED at +{events['started_at']:.2f}s")

    @user_agg.event_handler("on_user_turn_stopped")
    async def _stopped(agg, strategy, message, *args):
        events["stopped_at"] = time.monotonic() - t0
        events["content"] = getattr(message, "content", message)
        print(f"[agent] user turn STOPPED at +{events['stopped_at']:.2f}s: {events['content']!r}")
        done.set()

    tracks: dict = {}

    @recorder.event_handler("on_track_audio_data")
    async def _tracks(proc, user_audio: bytes, bot_audio: bytes, sample_rate: int, num_channels: int):
        tracks["user"], tracks["bot"], tracks["rate"] = user_audio, bot_audio, sample_rate

    params = PipelineParams(audio_in_sample_rate=SAMPLE_RATE, audio_out_sample_rate=SAMPLE_RATE, enable_metrics=True)
    caller_worker = PipelineWorker(
        caller, params=params, enable_rtvi=False, idle_timeout_secs=None, cancel_runner_on_idle_timeout=False
    )
    agent_worker = PipelineWorker(
        agent, params=params, enable_rtvi=False, idle_timeout_secs=None, cancel_runner_on_idle_timeout=False
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(caller_worker, agent_worker)

    async def heartbeat():
        while True:
            await asyncio.sleep(2)
            print(
                f"[hb +{time.monotonic() - t0:.1f}s] caller.out bytes_written={caller_tx.output().bytes_written} "
                f"agent.mic speech_played={agent_tx.input().mic.speech_bytes_played} "
                f"agent.out bytes_written={agent_tx.output().bytes_written} caller.mic played={caller_tx.input().mic.speech_bytes_played}",
                flush=True,
            )

    async def script():
        hb = asyncio.create_task(heartbeat())
        await asyncio.sleep(1.5)  # let both pipelines start
        print(f"[caller] speaking at +{time.monotonic() - t0:.2f}s", flush=True)
        await caller_worker.queue_frames([TTSSpeakFrame(UTTERANCE)])
        try:
            await asyncio.wait_for(done.wait(), timeout=20)
        except TimeoutError:
            print("!! timed out waiting for the agent to detect the turn", flush=True)
        await asyncio.sleep(1.0)
        hb.cancel()
        try:
            await recorder.stop_recording()
        except Exception as e:
            print("stop_recording error:", e)
        await asyncio.sleep(0.5)
        print("cancelling runner", flush=True)
        await runner.cancel(reason="poc done")

    asyncio.create_task(script())
    await runner.run()

    elapsed = time.monotonic() - t0
    print("\n--- POC results ---")
    print(
        f"elapsed {elapsed:.1f}s | caller bytes written {caller_tx.output().bytes_written} | "
        f"agent mic speech bytes played {agent_tx.input().mic.speech_bytes_played}"
    )
    if tracks:
        u, b = tracks["user"], tracks["bot"]
        print(
            f"recorded LEFT(user=caller) {len(u) / (2 * SAMPLE_RATE):.1f}s, RIGHT(bot=agent) {len(b) / (2 * SAMPLE_RATE):.1f}s"
        )
        out = Path("recordings/raw/arena_poc.wav")
        out.parent.mkdir(parents=True, exist_ok=True)
        n = max(len(u), len(b))
        u, b = u.ljust(n, b"\x00"), b.ljust(n, b"\x00")
        inter = bytearray()
        for i in range(0, n, 2):
            inter += u[i : i + 2] + b[i : i + 2]
        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(bytes(inter))
        print(f"wrote {out}")
    ok = (
        "content" in events
        and "maya" in events["content"].lower()
        and events.get("stopped_at", 0) - events.get("started_at", 0) > 2.0
    )
    print("PASS" if ok else "FAIL", events)


if __name__ == "__main__":
    asyncio.run(main())
