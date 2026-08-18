"""Targets: the voice agent under test, described as data.

A target says (1) how to reach the agent — a bundled local sample agent, a websocket endpoint, or a phone number
through an optional phone adapter — and (2) the *ground truth* about the business the agent represents (hours,
providers, address, policies, insurance). The simulator's persona speaks about the business by name; the judge
uses the ground truth to tell a real bug (a Saturday booking at a Monday–Friday clinic) from a preference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class Business(BaseModel):
    name: str
    kind: str = Field(default="medical practice", description="e.g. orthopedics clinic, dental office, salon")
    hours: str = Field(description="Human-readable hours, e.g. 'Monday–Friday 8am–5pm; closed weekends'")
    providers: list[str] = Field(default_factory=list)
    address: str = ""
    phone_display: str = ""
    policies: list[str] = Field(default_factory=list)
    insurance_accepted: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, description="Any other facts the judge may treat as true")

    def as_ground_truth(self) -> str:
        parts = [f"Business: {self.name} ({self.kind})", f"Hours: {self.hours}"]
        if self.providers:
            parts.append("Providers: " + "; ".join(self.providers))
        if self.address:
            parts.append(f"Address: {self.address}")
        if self.policies:
            parts.append("Policies: " + " | ".join(self.policies))
        if self.insurance_accepted:
            parts.append("Insurance accepted: " + ", ".join(self.insurance_accepted))
        if self.notes:
            parts.append("Notes: " + " | ".join(self.notes))
        return "\n".join(parts)


class LocalConnection(BaseModel):
    """The bundled sample agent, run in-process. `planted_bugs` deliberately degrade it so detection can be demoed."""

    kind: Literal["local"] = "local"
    planted_bugs: list[str] = Field(default_factory=list, description="e.g. weekend_booking, fabricated_dob, phi_leak")
    interruptions: bool = Field(
        default=True, description="Whether the sample agent stops talking when the caller barges in"
    )
    voice: str = Field(
        default="", description="Deepgram Aura-2 voice for the sample agent (audio arena), e.g. aura-2-athena-en"
    )


class WebsocketConnection(BaseModel):
    """Any agent that speaks Pipecat's websocket protocol (Protobuf frames, 16 kHz PCM), e.g. a Pipecat bot behind
    `WebsocketServerTransport`, or `voxprobe serve-agent`. Used by `voxprobe simulate --mode audio`."""

    kind: Literal["websocket"] = "websocket"
    url: str


class VapiConnection(BaseModel):
    """Phone target dialed through the optional Vapi adapter (bring your own paid telephony)."""

    kind: Literal["vapi"] = "vapi"
    phone_number: str = Field(description="E.164 number to dial; must ALSO be in ALLOWED_NUMBERS_E164")


class Target(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    description: str = ""
    business: Business
    connection: LocalConnection | WebsocketConnection | VapiConnection = Field(discriminator="kind")

    @property
    def kind(self) -> str:
        return self.connection.kind


def load_target(path: Path) -> Target:
    with path.open() as f:
        return Target.model_validate(yaml.safe_load(f))


def load_all_targets(directory: Path) -> list[Target]:
    return [load_target(p) for p in sorted(directory.glob("*.yaml"))]


def find_target(directory: Path, target_id: str) -> Target:
    for t in load_all_targets(directory):
        if t.id == target_id:
            return t
    raise FileNotFoundError(f"no target {target_id!r} in {directory}")
