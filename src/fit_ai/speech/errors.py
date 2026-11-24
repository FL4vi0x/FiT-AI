"""Speech errors. Independent of HTTP: a stable machine-readable `code` and a SAFE message (never audio, never a transcript,
never a filesystem path). The HTTP layer maps `code` to a status."""
from __future__ import annotations


class SpeechError(Exception):
    code = "speech_error"
    safe_message = "The audio could not be processed."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.safe_message)
        self.safe_message = message or type(self).safe_message


# ---- the request is wrong -------------------------------------------------------------------
class InvalidAudio(SpeechError):
    code = "invalid_audio"
    safe_message = "The audio is not a valid 16 kHz mono 16-bit PCM WAV file."


class AudioEmpty(SpeechError):
    code = "audio_empty"
    safe_message = "The audio is empty."


class AudioTooShort(SpeechError):
    code = "audio_too_short"
    safe_message = "The audio is too short to contain speech."


class AudioTooLong(SpeechError):
    code = "audio_too_long"
    safe_message = "The audio is longer than the allowed maximum."


# ---- the engine ---------------------------------------------------------------------------------
class STTDisabled(SpeechError):
    code = "stt_disabled"
    safe_message = "Speech recognition is turned off in this installation."


class STTUnavailable(SpeechError):
    code = "stt_unavailable"
    safe_message = "Speech recognition is not available."


class STTModelMissing(SpeechError):
    code = "stt_model_missing"
    safe_message = "The speech recognition model is not installed. See docs/poc-09-01-local-stt.md."


class STTBusy(SpeechError):
    code = "stt_busy"
    safe_message = "Another transcription is in progress. Try again in a moment."
    retry_after_s = 2


class STTTimeout(SpeechError):
    code = "stt_timeout"
    safe_message = "The transcription took too long and was abandoned."


class STTFailed(SpeechError):
    code = "stt_failed"
    safe_message = "The transcription failed."
