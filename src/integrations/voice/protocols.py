"""
Phase 7 voice I/O abstractions.

Orchestrator stays text-in / text-out. These adapters only convert audio ↔ text.
"""

from __future__ import annotations

from typing import Iterator, Optional, Protocol, runtime_checkable


@runtime_checkable
class SpeechToText(Protocol):
    """
    Stream or batch speech recognition.

    Partial transcripts are for UX only; commit a turn with ``finalize()``
    (or ``transcribe()``) when the utterance is complete (VAD / end-of-utterance).
    """

    def feed(self, pcm_chunk: bytes) -> Optional[str]:
        """Ingest a PCM chunk; return latest partial transcript if available."""
        ...

    def finalize(self) -> str:
        """End-of-utterance → final transcript string (same contract as chat text)."""
        ...

    def reset(self) -> None:
        """Clear buffers between utterances."""
        ...

    def transcribe(self, pcm: bytes) -> str:
        """Batch helper: feed all audio then finalize."""
        ...


@runtime_checkable
class TextToSpeech(Protocol):
    """Synthesize assistant text to PCM; cancellable for barge-in."""

    def synthesize(self, text: str) -> bytes:
        """Return PCM16 mono bytes for ``text`` (may be empty if cancelled mid-run)."""
        ...

    def synthesize_stream(self, text: str) -> Iterator[bytes]:
        """Optional streaming chunks; default impls may yield a single chunk."""
        ...

    def cancel(self) -> None:
        """Barge-in: stop current synthesis / mark playback abandoned."""
        ...

    @property
    def cancelled(self) -> bool:
        ...


@runtime_checkable
class AudioIO(Protocol):
    """Platform-specific mic/speaker chunk I/O."""

    def read_chunk(self) -> Optional[bytes]:
        """Blocking or non-blocking mic frame; ``None`` when no data."""
        ...

    def write_chunk(self, pcm: bytes) -> None:
        """Play a PCM frame to the speaker."""
        ...

    def stop_playback(self) -> None:
        """Barge-in: flush / stop speaker output."""
        ...
