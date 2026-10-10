"""Text-to-speech adapters (recording double + silent stub)."""

from __future__ import annotations

from typing import Iterator, List


class RecordingTextToSpeech:
    """
    Captures spoken strings for tests; emits tiny silence as fake PCM.

    ``cancel()`` stops further chunks for the in-flight synthesize (barge-in).
    """

    def __init__(self, *, bytes_per_char: int = 2) -> None:
        self._bytes_per_char = max(1, bytes_per_char)
        self.spoken: List[str] = []
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def clear_cancel(self) -> None:
        self._cancelled = False

    def synthesize(self, text: str) -> bytes:
        self.clear_cancel()
        chunks = list(self.synthesize_stream(text))
        return b"".join(chunks)

    def synthesize_stream(self, text: str) -> Iterator[bytes]:
        self._cancelled = False
        if not text:
            return
        self.spoken.append(text)
        # Emit one fake frame per ~40 chars so barge-in can cut mid-stream in tests
        step = 40
        for i in range(0, len(text), step):
            if self._cancelled:
                return
            piece = text[i : i + step]
            yield b"\x00" * (len(piece) * self._bytes_per_char)


class NullTextToSpeech:
    """No-op TTS for headless runs that only need orchestrator turns."""

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def synthesize(self, text: str) -> bytes:
        _ = text
        self._cancelled = False
        return b""

    def synthesize_stream(self, text: str) -> Iterator[bytes]:
        _ = text
        self._cancelled = False
        if False:  # pragma: no cover
            yield b""
