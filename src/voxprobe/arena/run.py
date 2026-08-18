"""Audio arena: simulated caller ↔ bundled sample agent over a virtual phone line, in one process.

Caller pipeline:  mic ← agent | Deepgram STT → user aggregator → CallerBrainLLM → Deepgram TTS → line | recorder
Agent pipeline:   mic ← caller | Deepgram STT → user aggregator → OpenAI-compatible LLM (Gemini) → Deepgram TTS → line

Recording is taken in the CALLER pipeline so the file follows voxprobe's convention: LEFT = the agent under test
(what the caller hears), RIGHT = the simulated caller. Transcript lines come from the aggregators' turn events;
response latencies from Pipecat's UserBotLatencyObserver on each side (VAD-hangover-corrected).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
import wave
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame, TTSSpeakFrame
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.turns.user_start.vad_user_turn_start_strategy import VADUserTurnStartStrategy
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from ..brain import GEMINI_BASE_URL, Brain, build_providers
from ..config import Settings
from ..director import looks_like_goodbye
from ..scenarios import Scenario
from ..simulate import sample_agent_prompt
from ..targets import LocalConnection, Target
from .caller_brain import CallerBrainLLM
from .loopback import SAMPLE_RATE, LoopbackTransport, link

AGENT_VOICE = "aura-2-athena-en"
GOODBYE_GRACE_S = 7.0  # after the caller says goodbye, wait this long for the agent's goodbye before hanging up

# Deliberate barge-in (scenario.barge_in = True): once the agent has been talking this long, the caller cuts in.
BARGE_IN_AFTER_S = 4.0
BARGE_IN_MAX = 2
BARGE_IN_PHRASES = ["Sorry, sorry — can I jump in for a second?", "Sorry to cut in —"]
BARGE_IN_FOLLOW_UP = (
    "You just interrupted the receptionist mid-sentence on purpose. Now say, in one sentence, what you actually want next "
    "according to your plan (change the day, the doctor, or take any available slot)."
)


@dataclass
class ArenaResult:
    stem: str
    scenario_id: str
    target_id: str
    started_at: str
    duration_s: float
    transcript: list[dict] = field(default_factory=list)  # {t, speaker, text, source}
    caller_latencies_s: list[float] = field(default_factory=list)  # agent stops → caller starts
    agent_latencies_s: list[float] = field(default_factory=list)  # caller stops → agent starts
    brain_records: list[dict] = field(default_factory=list)
    barge_ins: list[dict] = field(default_factory=list)  # deliberate interruptions and how the agent yielded
    files: dict = field(default_factory=dict)
    ended_reason: str = ""


def _user_params(*, enable_interruptions: bool) -> LLMUserAggregatorParams:
    return LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
        user_turn_strategies=UserTurnStrategies(
            start=[VADUserTurnStartStrategy(enable_interruptions=enable_interruptions)],
            stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)],
        ),
    )


def _voice_for(scenario: Scenario) -> str:
    v = scenario.patient.voice_id
    return v if v.startswith("aura-") else f"aura-2-{v}-en"


async def run_audio_arena(
    settings: Settings, scenario: Scenario, target: Target, max_duration_s: int | None = None
) -> ArenaResult:
    if not settings.deepgram_api_key:
        raise RuntimeError("audio arena needs DEEPGRAM_API_KEY (STT/TTS for both sides)")
    if not settings.google_api_key:
        raise RuntimeError("audio arena needs GOOGLE_API_KEY (the sample agent's LLM)")
    if not isinstance(target.connection, LocalConnection):
        raise RuntimeError(f"target {target.id} is not a local target")
    max_duration_s = max_duration_s or scenario.max_duration_seconds

    day = datetime.now(UTC).strftime("%Y%m%d")
    stem = f"arena-{scenario.id}-{day}-{uuid4().hex[:6]}"
    result = ArenaResult(
        stem=stem,
        scenario_id=scenario.id,
        target_id=target.id,
        started_at=datetime.now(UTC).isoformat(),
        duration_s=0.0,
    )
    t0 = time.monotonic()

    def now() -> float:
        return round(time.monotonic() - t0, 2)

    # ---- virtual phone line ----
    caller_tx, agent_tx = LoopbackTransport(name="caller-line"), LoopbackTransport(name="agent-line")
    link(caller_tx, agent_tx)

    # ---- caller pipeline ----
    caller_stt = DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramSTTService.Settings(model="nova-3", language="en", interim_results=True, smart_format=False),
    )
    caller_ctx = LLMContext()
    caller_user_agg, caller_asst_agg = LLMContextAggregatorPair(
        caller_ctx, user_params=_user_params(enable_interruptions=True)
    )
    caller_llm = CallerBrainLLM(Brain(build_providers(settings)), scenario, target.business.name)
    caller_tts = DeepgramTTSService(
        api_key=settings.deepgram_api_key,
        sample_rate=SAMPLE_RATE,
        settings=DeepgramTTSService.Settings(voice=_voice_for(scenario)),
    )
    recorder = AudioBufferProcessor(sample_rate=SAMPLE_RATE, num_channels=2, auto_start_recording=True)
    caller = Pipeline(
        [
            caller_tx.input(),
            caller_stt,
            caller_user_agg,
            caller_llm,
            caller_tts,
            caller_tx.output(),
            recorder,
            caller_asst_agg,
        ]
    )

    # ---- agent pipeline (the sample receptionist under test) ----
    agent_stt = DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramSTTService.Settings(model="nova-3", language="en", interim_results=True, smart_format=False),
    )
    agent_ctx = LLMContext(
        messages=[
            {"role": "system", "content": sample_agent_prompt(target)},
            {"role": "user", "content": "(The call connects. Greet the caller.)"},
        ]
    )
    agent_user_agg, agent_asst_agg = LLMContextAggregatorPair(
        agent_ctx, user_params=_user_params(enable_interruptions=target.connection.interruptions)
    )
    agent_llm = OpenAILLMService(api_key=settings.google_api_key, base_url=GEMINI_BASE_URL, model=settings.gemini_model)
    agent_tts = DeepgramTTSService(
        api_key=settings.deepgram_api_key,
        sample_rate=SAMPLE_RATE,
        settings=DeepgramTTSService.Settings(voice=target.connection.voice or AGENT_VOICE),
    )
    agent = Pipeline(
        [agent_tx.input(), agent_stt, agent_user_agg, agent_llm, agent_tts, agent_tx.output(), agent_asst_agg]
    )

    # ---- events: transcript, latency, ending ----
    caller_done = asyncio.Event()
    agent_goodbye = asyncio.Event()

    agent_speaking_since: dict = {"t": None}  # from the caller's point of view (its "user" is the agent)
    pending_barge: dict = {"t": None, "flushed_before": 0}

    @caller_user_agg.event_handler("on_user_turn_started")
    async def _agent_started(agg, *args):
        agent_speaking_since["t"] = time.monotonic()

    @caller_user_agg.event_handler("on_user_turn_stopped")
    async def _agent_said(agg, strategy, message):  # what the CALLER heard the AGENT say
        agent_speaking_since["t"] = None
        if pending_barge["t"] is not None:  # the agent stopped after our deliberate interruption
            flushed = agent_tx.output().bytes_flushed_at_peer - pending_barge["flushed_before"]
            result.barge_ins[-1].update(
                {
                    "agent_stopped_at": now(),
                    "yield_s": round(time.monotonic() - pending_barge["t"], 2),
                    "unheard_agent_speech_s": round(flushed / (2 * SAMPLE_RATE), 2),
                }
            )
            logger.info(
                f"[{now():6.2f}s] BARGE-IN: agent yielded after {result.barge_ins[-1]['yield_s']} s; "
                f"{result.barge_ins[-1]['unheard_agent_speech_s']} s of its speech went unheard"
            )
            pending_barge["t"] = None
        text = (getattr(message, "content", "") or "").strip()
        if text:
            result.transcript.append({"t": now(), "speaker": "AGENT", "text": text, "source": "caller-stt"})
            logger.info(f"[{now():6.2f}s] AGENT  : {text}")
            if looks_like_goodbye(text):
                agent_goodbye.set()

    @caller_asst_agg.event_handler("on_assistant_turn_stopped")
    async def _caller_said(agg, message):
        text = (getattr(message, "content", "") or "").strip()
        interrupted = bool(getattr(message, "interrupted", False))
        if text:
            result.transcript.append(
                {"t": now(), "speaker": "CALLER", "text": text, "source": "caller-llm", "interrupted": interrupted}
            )
            logger.info(f"[{now():6.2f}s] CALLER : {text}{'  (interrupted)' if interrupted else ''}")
        if caller_llm.log.said_goodbye:
            caller_done.set()

    caller_latency = UserBotLatencyObserver()
    agent_latency = UserBotLatencyObserver()

    @caller_latency.event_handler("on_latency_measured")
    async def _cl(obs, latency):
        result.caller_latencies_s.append(round(float(latency), 3))

    @agent_latency.event_handler("on_latency_measured")
    async def _al(obs, latency):
        result.agent_latencies_s.append(round(float(latency), 3))

    tracks: dict = {}

    @recorder.event_handler("on_track_audio_data")
    async def _tracks(proc, user_audio: bytes, bot_audio: bytes, sample_rate: int, num_channels: int):
        tracks["agent"], tracks["caller"], tracks["rate"] = user_audio, bot_audio, sample_rate

    params = PipelineParams(audio_in_sample_rate=SAMPLE_RATE, audio_out_sample_rate=SAMPLE_RATE, enable_metrics=True)
    caller_worker = PipelineWorker(
        caller,
        params=params,
        enable_rtvi=False,
        idle_timeout_secs=None,
        cancel_runner_on_idle_timeout=False,
        observers=[caller_latency],
    )
    agent_worker = PipelineWorker(
        agent,
        params=params,
        enable_rtvi=False,
        idle_timeout_secs=None,
        cancel_runner_on_idle_timeout=False,
        observers=[agent_latency],
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(caller_worker, agent_worker)

    async def barge_in_driver():
        """Scenario 09: when the agent talks for a while, the caller cuts in — and we measure how the agent yields."""
        while len(result.barge_ins) < BARGE_IN_MAX:
            await asyncio.sleep(0.25)
            since = agent_speaking_since["t"]
            if since is None or caller_llm.state.patient_turns < 1 or pending_barge["t"] is not None:
                continue
            if time.monotonic() - since < BARGE_IN_AFTER_S:
                continue
            phrase = BARGE_IN_PHRASES[len(result.barge_ins) % len(BARGE_IN_PHRASES)]
            pending_barge.update({"t": time.monotonic(), "flushed_before": agent_tx.output().bytes_flushed_at_peer})
            result.barge_ins.append(
                {"triggered_at": now(), "phrase": phrase, "agent_speaking_for_s": round(time.monotonic() - since, 2)}
            )
            caller_llm.state.pending_note = BARGE_IN_FOLLOW_UP
            logger.info(
                f"[{now():6.2f}s] BARGE-IN: caller cuts in ({phrase!r}) after the agent spoke "
                f"{result.barge_ins[-1]['agent_speaking_for_s']} s"
            )
            await caller_worker.queue_frames([TTSSpeakFrame(phrase)])
            await asyncio.sleep(6.0)  # give the exchange time before considering another interruption

    async def conductor():
        await asyncio.sleep(1.0)  # both pipelines up
        await agent_worker.queue_frames([LLMRunFrame()])  # the receptionist answers the phone
        driver = asyncio.create_task(barge_in_driver()) if scenario.barge_in else None
        try:
            await asyncio.wait_for(caller_done.wait(), timeout=max_duration_s)
            result.ended_reason = "caller-said-goodbye"
            try:
                await asyncio.wait_for(agent_goodbye.wait(), timeout=GOODBYE_GRACE_S)
                await asyncio.sleep(1.5)  # let the agent's goodbye finish playing
            except TimeoutError:
                pass
        except TimeoutError:
            result.ended_reason = "max-duration"
        if driver:
            driver.cancel()
        try:
            await recorder.stop_recording()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"stop_recording: {e}")
        await asyncio.sleep(0.5)
        await runner.cancel(reason=result.ended_reason)

    conductor_task = asyncio.create_task(conductor())
    await runner.run()
    await conductor_task
    result.duration_s = round(time.monotonic() - t0, 1)

    # ---- evidence ----
    result.brain_records = [
        {
            "turn": i + 1,
            "provider": r.provider,
            "model": r.model,
            "latency_ms": r.latency_ms,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "failed_over_from": r.failed_over_from,
            "reply": r.reply,
        }
        for i, r in enumerate(caller_llm.log.records)
    ]
    _write_bundle(settings, scenario, target, result, tracks)
    return result


def _write_bundle(settings: Settings, scenario: Scenario, target: Target, r: ArenaResult, tracks: dict) -> None:
    settings.recordings_dir.mkdir(exist_ok=True)
    settings.transcripts_dir.mkdir(exist_ok=True)
    (settings.reports_dir / "events").mkdir(parents=True, exist_ok=True)
    raw = settings.recordings_dir / "raw"
    raw.mkdir(exist_ok=True)

    mp3_rel = None
    if tracks:
        left, right = tracks["agent"], tracks["caller"]  # LEFT = agent under test, RIGHT = caller
        n = max(len(left), len(right))
        left, right = left.ljust(n, b"\x00"), right.ljust(n, b"\x00")
        wav_path = raw / f"{r.stem}.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(tracks["rate"])
            wf.writeframes(_interleave(left, right))
        mp3_path = settings.recordings_dir / f"{r.stem}.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(wav_path), "-c:a", "libmp3lame", "-q:a", "2", str(mp3_path)],
            check=True,
        )
        mp3_rel = str(mp3_path.relative_to(settings.repo_root))

    # transcript (live, from the aggregators)
    md = [
        f"# {r.stem} — {scenario.title}",
        "",
        f"- Target: {target.name} (`{target.id}`) · scenario `{scenario.id}` · started {r.started_at} · duration {r.duration_s}s · ended: {r.ended_reason}",
        f"- Recording: `{mp3_rel}` (LEFT = agent, RIGHT = caller)",
        "- Live transcript from the caller pipeline's aggregators (AGENT lines = what the caller's STT heard). "
        "The audio-derived transcript (`*.whisper.md`) is authoritative.",
        "",
    ]
    for line in r.transcript:
        md.append(f"[{int(line['t']) // 60:02d}:{int(line['t']) % 60:02d}] {line['speaker']:7s}: {line['text']}")
    (settings.transcripts_dir / f"{r.stem}.md").write_text("\n".join(md) + "\n")
    (settings.transcripts_dir / f"{r.stem}.json").write_text(
        json.dumps(
            {
                "stem": r.stem,
                "scenario_id": r.scenario_id,
                "target_id": r.target_id,
                "transcript": r.transcript,
                "caller_latencies_s": r.caller_latencies_s,
                "agent_latencies_s": r.agent_latencies_s,
            },
            indent=2,
        )
    )

    # brain events in the same shape the phone adapter's server writes (metrics.py reads them)
    events_path = settings.reports_dir / "events" / f"{r.stem}.jsonl"
    with events_path.open("w") as f:
        for rec in r.brain_records:
            f.write(json.dumps({"type": "brain-turn", **rec}) + "\n")

    meta = {
        "stem": r.stem,
        "scenario_id": r.scenario_id,
        "target_id": r.target_id,
        "title": scenario.title,
        "mode": "audio-arena",
        "started_at": r.started_at,
        "duration_s": r.duration_s,
        "ended_reason": r.ended_reason,
        "caller_response_latency_s": r.caller_latencies_s,
        "agent_response_latency_s": r.agent_latencies_s,
        "barge_ins": r.barge_ins,
        "cost_usd": 0,
        "performance_metrics": None,
        "files": {
            "recording_mp3": mp3_rel,
            "transcript_md": f"transcripts/{r.stem}.md",
            "call_json": f"transcripts/{r.stem}.json",
            "events_jsonl": f"reports/events/{r.stem}.jsonl",
        },
    }
    (settings.reports_dir / f"{r.stem}.meta.json").write_text(json.dumps(meta, indent=2))
    r.files = meta["files"]


def _interleave(left: bytes, right: bytes) -> bytes:
    """Interleave two mono PCM16 streams into stereo (L, R, L, R ...)."""
    import array

    la, ra = array.array("h", left), array.array("h", right)
    out = array.array("h", bytes(len(la) * 4))
    out[0::2] = la
    out[1::2] = ra
    return out.tobytes()


def main(settings: Settings, scenario: Scenario, target: Target, max_duration_s: int | None = None) -> ArenaResult:
    return asyncio.run(run_audio_arena(settings, scenario, target, max_duration_s))
