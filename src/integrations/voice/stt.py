"""Speech-to-text adapters (test doubles + text-injection for demos)."""

from __future__ import annotations

from typing import List, Optional


class PassthroughSpeechToText:
    """
    Test/demo STT: UTF-8 text framed as “PCM”, or inject finals via ``push_text``.

    Real providers (Whisper, cloud STT) implement the same ``SpeechToText`` surface.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._partial: Optional[str] = None
        self._injected: Optional[str] = None

    def push_text(self, text: str) -> None:
        """Inject a final transcript (WebSocket text_utterance / CLI)."""
        self._injected = (text or "").strip()
        self._partial = self._injected

    def feed(self, pcm_chunk: bytes) -> Optional[str]:
        if not pcm_chunk:
            return self._partial
        self._buf.extend(pcm_chunk)
        try:
            self._partial = bytes(self._buf).decode("utf-8")
        except UnicodeDecodeError:
            # Incomplete multi-byte sequence mid-stream — keep prior partial
            pass
        return self._partial

    def finalize(self) -> str:
        if self._injected is not None:
            text = self._injected
            self.reset()
            return text
        try:
            text = bytes(self._buf).decode("utf-8").strip()
        except UnicodeDecodeError:
            text = ""
        self.reset()
        return text

    def reset(self) -> None:
        self._buf.clear()
        self._partial = None
        self._injected = None

    def transcribe(self, pcm: bytes) -> str:
        self.reset()
        self.feed(pcm)
        return self.finalize()


class ScriptedSpeechToText:
    """Yield predetermined finals for automated E2E voice tests."""

    def __init__(self, utterances: List[str]) -> None:
        self._queue = list(utterances)
        self._current: Optional[str] = None

    def feed(self, pcm_chunk: bytes) -> Optional[str]:
        _ = pcm_chunk
        return self._current

    def finalize(self) -> str:
        if self._current is not None:
            text = self._current
            self._current = None
            return text
        if not self._queue:
            return ""
        return self._queue.pop(0)

    def reset(self) -> None:
        self._current = None

    def transcribe(self, pcm: bytes) -> str:
        _ = pcm
        return self.finalize()

    def push_next(self) -> str:
        """Peek-load next scripted line as the active utterance."""
        if not self._queue:
            self._current = ""
            return ""
        self._current = self._queue.pop(0)
        return self._current
