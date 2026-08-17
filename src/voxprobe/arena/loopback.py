"""In-process loopback transport pair for Pipecat: two pipelines "on a phone call" with each other.

Pipecat 1.7 has websocket, PyAudio and WebRTC transports, and its eval harness (`pipecat.evals`) plays scripted
utterances through a virtual microphone over a websocket into ONE agent pipeline. voxprobe needs TWO full pipelines
(an adaptive simulated caller and the agent under test) to talk in the same process with no socket, so this module
provides an in-process loopback pair:

* ``LoopbackTransport`` is a normal Pipecat transport (``.input()`` / ``.output()``).
* ``link(a, b)`` wires A's output to B's input and vice-versa — like a phone line.
* The OUTPUT side paces its writes in real time (one 20 ms chunk per 20 ms), exactly like a sound card would.
  Pacing is what makes barge-in real: audio still queued in the sender can be dropped on interruption, audio
  already "played" cannot.
* The INPUT side is a virtual microphone: every 20 ms it pushes one frame downstream — the peer's speech when
  there is some, locally generated silence otherwise — because VAD/turn detection needs a *continuous* stream
  (silence is how a turn ends). This mirrors Pipecat's own eval microphone (pipecat/evals/transport.py).

Everything on the wire is 16 kHz mono PCM16.
"""

from __future__ import annotations

import asyncio
import time

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    StartFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import BaseTransport, TransportParams

SAMPLE_RATE = 16000
CHUNK_MS = 20


def loopback_params() -> TransportParams:
    return TransportParams(
        audio_in_enabled=True,
        audio_in_sample_rate=SAMPLE_RATE,
        audio_in_channels=1,
        audio_in_passthrough=True,  # STT, VAD and turn analyzers all read the passthrough audio
        audio_out_enabled=True,
        audio_out_sample_rate=SAMPLE_RATE,
        audio_out_channels=1,
        audio_out_10ms_chunks=CHUNK_MS // 10,  # 20 ms writes — same cadence as the virtual microphone
        audio_out_end_silence_secs=0,  # no synthetic silence burst on EndFrame
    )


class VirtualMicrophone:
    """Real-time playout of whatever the peer sends, with silence in between (see module docstring)."""

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self._rate = sample_rate
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._pcm = b""
        self._offset = 0
        self.bytes_per_chunk = (sample_rate * CHUNK_MS // 1000) * 2
        self._silence = b"\x00\x00" * (sample_rate * CHUNK_MS // 1000)
        self.speech_bytes_played = 0

    def add_audio(self, pcm: bytes) -> None:
        self._queue.put_nowait(pcm)

    def flush(self) -> int:
        """Drop everything not yet played (used on interruption). Returns bytes dropped."""
        dropped = len(self._pcm) - self._offset if self._pcm else 0
        while not self._queue.empty():
            dropped += len(self._queue.get_nowait())
        self._pcm, self._offset = b"", 0
        return dropped

    def _next_chunk(self) -> bytes:
        while self._offset >= len(self._pcm):
            try:
                self._pcm = self._queue.get_nowait()
                self._offset = 0
            except asyncio.QueueEmpty:
                return b""
        chunk = self._pcm[self._offset : self._offset + self.bytes_per_chunk]
        self._offset += self.bytes_per_chunk
        return chunk

    async def run(self, push) -> None:
        """Emit one frame per tick forever (cancel to stop). ``push(pcm: bytes)`` is awaited each tick."""
        tick = CHUNK_MS / 1000
        loop = asyncio.get_running_loop()
        next_send = loop.time()
        while True:
            chunk = self._next_chunk()
            speaking = bool(chunk)
            if speaking:
                self.speech_bytes_played += len(chunk)
                if len(chunk) < self.bytes_per_chunk:  # tail of an utterance: pad to a full frame
                    chunk = chunk + b"\x00" * (self.bytes_per_chunk - len(chunk))
            else:
                chunk = self._silence
            await push(chunk)
            next_send += tick
            now = loop.time()
            if not speaking:
                next_send = max(next_send, now)  # never burst silence to catch up: end-of-turn gaps stay honest
            if next_send > now:
                await asyncio.sleep(next_send - now)


class LoopbackInputTransport(BaseInputTransport):
    def __init__(self, params: TransportParams, **kwargs):
        super().__init__(params, **kwargs)
        self.mic = VirtualMicrophone(params.audio_in_sample_rate or SAMPLE_RATE)
        self._mic_task = None
        self._initialized = False

    async def start(self, frame: StartFrame):
        await super().start(frame)
        if self._initialized:
            return
        self._initialized = True
        await self.set_transport_ready(frame)  # creates the audio-in queue/task; base start() does not
        self._mic_task = self.create_task(self.mic.run(self._push_pcm))

    async def _push_pcm(self, pcm: bytes) -> None:
        await self.push_audio_frame(InputAudioRawFrame(audio=pcm, sample_rate=self.mic._rate, num_channels=1))

    async def _stop_mic(self) -> None:
        if self._mic_task:
            await self.cancel_task(self._mic_task)
            self._mic_task = None

    async def stop(self, frame: EndFrame):
        await self._stop_mic()
        await super().stop(frame)

    async def cancel(self, frame: CancelFrame):
        await self._stop_mic()
        await super().cancel(frame)

    async def cleanup(self):
        await self._stop_mic()
        await super().cleanup()


class LoopbackOutputTransport(BaseOutputTransport):
    def __init__(self, params: TransportParams, **kwargs):
        super().__init__(params, **kwargs)
        self._peer: LoopbackInputTransport | None = None
        self._send_interval = 0.0
        self._next_send_time = 0.0
        self._initialized = False
        self.bytes_written = 0

    def set_peer(self, peer: LoopbackInputTransport) -> None:
        self._peer = peer

    async def start(self, frame: StartFrame):
        await super().start(frame)
        if self._initialized:
            return
        self._initialized = True
        # full chunk duration: we ARE the playback device (websocket transports use half because the client buffers)
        self._send_interval = self.audio_chunk_size / (self.sample_rate * 2)  # bytes -> seconds (mono 16-bit)
        await self.set_transport_ready(frame)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            # Barge-in: whatever the peer has not played yet is gone, like flushing a device buffer.
            self._next_send_time = 0
            if self._peer:
                dropped = self._peer.mic.flush()
                if dropped:
                    logger.debug(f"{self}: interruption — dropped {dropped} unplayed bytes at peer")

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        if not self._peer:
            return False
        self._peer.mic.add_audio(frame.audio)
        self.bytes_written += len(frame.audio)
        await self._write_audio_sleep()
        return True

    async def _write_audio_sleep(self):
        """Simulate a sound card clock: one chunk per chunk-duration."""
        now = time.monotonic()
        sleep_for = max(0.0, self._next_send_time - now)
        await asyncio.sleep(sleep_for)
        if sleep_for == 0:
            self._next_send_time = time.monotonic() + self._send_interval
        else:
            self._next_send_time += self._send_interval


class LoopbackTransport(BaseTransport):
    """One end of the virtual phone line. Use ``link(a, b)`` to connect two of them."""

    def __init__(self, params: TransportParams | None = None, *, name: str | None = None):
        super().__init__(name=name)
        self._params = params or loopback_params()
        self._input: LoopbackInputTransport | None = None
        self._output: LoopbackOutputTransport | None = None

    def input(self) -> FrameProcessor:
        if not self._input:
            self._input = LoopbackInputTransport(self._params, name=self._input_name)
        return self._input

    def output(self) -> FrameProcessor:
        if not self._output:
            self._output = LoopbackOutputTransport(self._params, name=self._output_name)
        return self._output


def link(a: LoopbackTransport, b: LoopbackTransport) -> None:
    """Connect two transports like a phone line: A's output plays into B's microphone and vice-versa."""
    a.output().set_peer(b.input())  # type: ignore[union-attr]
    b.output().set_peer(a.input())  # type: ignore[union-attr]
