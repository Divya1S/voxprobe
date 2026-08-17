"""The simulated caller's brain as a Pipecat LLM service.

Pipecat's user aggregator turns the *agent's* speech (transcribed) into "user" messages and asks the LLM
service for the next assistant turn by pushing an ``LLMContextFrame``. We answer with our own persona-driven
brain (persona + per-turn director + Groq→Gemini failover), so the same conversational logic runs in the
audio arena and in the phone adapter. Mirrors ``BaseOpenAILLMService.process_frame`` (services/openai/base_llm.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipecat.frames.frames import Frame, LLMContextFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService

from ..brain import Brain, TurnRecord, window_history
from ..director import CallState, director_note, looks_like_goodbye
from ..persona import compose_system_prompt
from ..scenarios import Scenario


@dataclass
class CallerTurnLog:
    records: list[TurnRecord] = field(default_factory=list)
    said_goodbye: bool = False


class CallerBrainLLM(LLMService):
    def __init__(self, brain: Brain, scenario: Scenario, business_name: str, **kwargs):
        super().__init__(**kwargs)
        self._brain = brain
        self._scenario = scenario
        self._business = business_name
        self.state = CallState(scenario=scenario, business_name=business_name)
        self.log = CallerTurnLog()

    def can_generate_metrics(self) -> bool:
        return True  # otherwise TTFB/processing metrics silently no-op

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            try:
                await self.push_frame(LLMFullResponseStartFrame())
                await self.start_processing_metrics()
                await self._respond(frame.context)
            except Exception as e:  # keep the pipeline alive; the error frame is logged upstream
                await self.push_error(error_msg=f"caller brain error: {e}", exception=e)
            finally:
                await self.stop_processing_metrics()
                await self.push_frame(LLMFullResponseEndFrame())
        else:
            await self.push_frame(frame, direction)  # mandatory: the base pushes nothing itself

    async def _respond(self, context) -> None:
        # OpenAI-format messages; from the caller's point of view the agent is "user", the caller "assistant".
        messages = [m for m in context.get_messages() if isinstance(m, dict)]
        history = window_history(messages)
        agent_last = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
        note = director_note(self.state, agent_last)
        system_prompt = compose_system_prompt(self._scenario, self._business, note)

        await self.start_ttfb_metrics()
        rec = await self._brain.reply(system_prompt, history)
        await self.stop_ttfb_metrics()

        self.state.patient_turns += 1
        self.state.previous_replies.append(rec.reply)
        self.log.records.append(rec)
        if looks_like_goodbye(rec.reply):
            self.log.said_goodbye = True
        await self._push_llm_text(rec.reply)
