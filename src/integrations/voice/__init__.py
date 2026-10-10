"""Voice I/O adapters — STT / TTS / AudioIO around Orchestrator.handle."""

from integrations.voice.audio_io import MemoryAudioIO, NullAudioIO
from integrations.voice.pipeline import LatencyBreakdown, VoicePipeline, VoiceTurnResult
from integrations.voice.prepare import prepare_assistant_for_tts
from integrations.voice.stt import PassthroughSpeechToText, ScriptedSpeechToText
from integrations.voice.tts import NullTextToSpeech, RecordingTextToSpeech

__all__ = [
    "LatencyBreakdown",
    "MemoryAudioIO",
    "NullAudioIO",
    "NullTextToSpeech",
    "PassthroughSpeechToText",
    "RecordingTextToSpeech",
    "ScriptedSpeechToText",
    "VoicePipeline",
    "VoiceTurnResult",
    "prepare_assistant_for_tts",
]
