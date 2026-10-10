"""
Voice turn pipeline: STT → Orchestrator.handle → TTS → AudioIO.

No booking logic lives here — only I/O adapters around the chat contract.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from integrations.voice.audio_io import MemoryAudioIO
from integrations.voice.prepare import prepare_assistant_for_tts
from integrations.voice.protocols import AudioIO, SpeechToText, TextToSpeech
from integrations.voice.stt import PassthroughSpeechToText
from integrations.voice.tts import RecordingTextToSpeech
from session.context import AgentTurn, SessionContext
from session.orchestrator import Orchestrator
from session.states import State


@dataclass
class LatencyBreakdown:
    stt_ms: float = 0.0
    orchestrator_ms: float = 0.0
    tts_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return self.stt_ms + self.orchestrator_ms + self.tts_ms


@dataclass
class VoiceTurnResult:
    final_transcript: str
    messages: List[str]
    spoken_messages: List[str]
    state: State
    session_id: str
    barge_in: bool = False
    latency: LatencyBreakdown = field(default_factory=LatencyBreakdown)
    audio_bytes_played: int = 0


class VoicePipeline:
    """
    One completed utterance → one ``Orchestrator.handle`` call → TTS each message.

    Partial STT is exposed via ``feed_audio`` for UX only.
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        *,
        stt: Optional[SpeechToText] = None,
        tts: Optional[TextToSpeech] = None,
        audio_io: Optional[AudioIO] = None,
        spell_booking_codes: bool = True,
    ) -> None:
        self._orch = orchestrator
        self._stt = stt or PassthroughSpeechToText()
        self._tts = tts or RecordingTextToSpeech()
        self._audio = audio_io or MemoryAudioIO()
        self._spell_codes = spell_booking_codes
        self._session: Optional[SessionContext] = None
        self._speaking = False

    @property
    def session(self) -> Optional[SessionContext]:
        return self._session

    @property
    def stt(self) -> SpeechToText:
        return self._stt

    @property
    def tts(self) -> TextToSpeech:
        return self._tts

    @property
    def audio_io(self) -> AudioIO:
        return self._audio

    def start_session(self) -> VoiceTurnResult:
        """Create session and speak the opening turn (greet + disclaimer)."""
        turn = self._orch.create_session()
        self._session = self._orch.store.get(turn.session_id)
        assert self._session is not None
        return self._speak_turn(turn, final_transcript="", latency=LatencyBreakdown())

    def feed_audio(self, pcm_chunk: bytes) -> Optional[str]:
        """
        Mic chunk → STT partial.

        On first speech while TTS is playing, barge-in cancels TTS (session state
        already matches chat history — no rollback).
        """
        barged = False
        if self._speaking and pcm_chunk:
            self.on_speech_start()
            barged = True
        partial = self._stt.feed(pcm_chunk)
        return partial

    def on_speech_start(self) -> None:
        """Barge-in: cancel TTS and stop speaker."""
        self._tts.cancel()
        self._audio.stop_playback()
        self._speaking = False

    def commit_utterance(self, text: Optional[str] = None) -> VoiceTurnResult:
        """
        End-of-utterance → final string → same contract as chat ``handle``.

        If ``text`` is provided, it is used as the final transcript (CLI / WS text path).
        """
        if self._session is None:
            raise RuntimeError("Voice session not started; call start_session() first")

        latency = LatencyBreakdown()
        t0 = time.perf_counter()
        if text is not None:
            push = getattr(self._stt, "push_text", None)
            if callable(push):
                push(text)
            else:
                self._stt.reset()
                self._stt.feed(text.encode("utf-8"))
            final = self._stt.finalize()
        else:
            final = self._stt.finalize()
        latency.stt_ms = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        turn = self._orch.handle(final, self._session)
        # Refresh session reference from store
        refreshed = self._orch.store.get(turn.session_id)
        if refreshed is not None:
            self._session = refreshed
        latency.orchestrator_ms = (time.perf_counter() - t1) * 1000.0

        return self._speak_turn(turn, final_transcript=final, latency=latency)

    def _speak_turn(
        self,
        turn: AgentTurn,
        *,
        final_transcript: str,
        latency: LatencyBreakdown,
    ) -> VoiceTurnResult:
        spoken: List[str] = []
        audio_len = 0
        barged = False
        t2 = time.perf_counter()
        self._speaking = True
        # Allow playback after prior barge-in
        resume = getattr(self._audio, "resume_playback", None)
        if callable(resume):
            resume()

        for message in turn.messages:
            if self._tts.cancelled:
                barged = True
                break
            prepared = prepare_assistant_for_tts(
                message, spell_codes=self._spell_codes
            )
            spoken.append(prepared)
            for chunk in self._tts.synthesize_stream(prepared):
                if self._tts.cancelled:
                    barged = True
                    self._audio.stop_playback()
                    break
                self._audio.write_chunk(chunk)
                audio_len += len(chunk)
            if barged:
                break

        self._speaking = False
        latency.tts_ms = (time.perf_counter() - t2) * 1000.0
        return VoiceTurnResult(
            final_transcript=final_transcript,
            messages=list(turn.messages),
            spoken_messages=spoken,
            state=turn.state,
            session_id=turn.session_id,
            barge_in=barged,
            latency=latency,
            audio_bytes_played=audio_len,
        )
