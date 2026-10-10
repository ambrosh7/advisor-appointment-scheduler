"""Per-connection voice session state for the WebSocket bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from integrations.voice.pipeline import VoicePipeline


@dataclass
class VoiceConnection:
    pipeline: VoicePipeline
    session_id: str = ""
    partial_transcript: str = ""
    tts_active: bool = False
    meta: dict = field(default_factory=dict)

    def note_partial(self, text: Optional[str]) -> None:
        if text is not None:
            self.partial_transcript = text
