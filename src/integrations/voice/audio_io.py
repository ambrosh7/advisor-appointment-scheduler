"""Audio I/O adapters — memory buffers for tests; null for headless."""

from __future__ import annotations

from collections import deque
from typing import Deque, List, Optional


class MemoryAudioIO:
    """In-memory mic/speaker queues (no OS audio devices)."""

    def __init__(self) -> None:
        self._mic: Deque[bytes] = deque()
        self._speaker: List[bytes] = []
        self._playback_stopped = False

    def push_mic(self, pcm: bytes) -> None:
        self._mic.append(pcm)

    def read_chunk(self) -> Optional[bytes]:
        if not self._mic:
            return None
        return self._mic.popleft()

    def write_chunk(self, pcm: bytes) -> None:
        if self._playback_stopped:
            return
        if pcm:
            self._speaker.append(pcm)

    def stop_playback(self) -> None:
        self._playback_stopped = True

    def resume_playback(self) -> None:
        self._playback_stopped = False

    @property
    def speaker_bytes(self) -> bytes:
        return b"".join(self._speaker)

    def clear_speaker(self) -> None:
        self._speaker.clear()
        self._playback_stopped = False


class NullAudioIO:
    """Discards speaker output; mic always empty."""

    def read_chunk(self) -> Optional[bytes]:
        return None

    def write_chunk(self, pcm: bytes) -> None:
        _ = pcm

    def stop_playback(self) -> None:
        return
