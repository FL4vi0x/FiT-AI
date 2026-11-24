"""Strict validation of the audio a browser sends. The only accepted container is a canonical RIFF/WAVE file with PCM, mono,
16-bit, 16 kHz samples: the UI converts and resamples on the client (so the Core never has to guess a format) and the Core
refuses everything else. Standard library only: the STT engine itself is optional.

Nothing here writes audio anywhere. The bytes live in memory for the duration of one request."""
from __future__ import annotations

import struct
import sys
from array import array
from dataclasses import dataclass
from math import sqrt
from operator import mul

from fit_ai.speech.errors import AudioEmpty, AudioTooLong, AudioTooShort, InvalidAudio

SAMPLE_RATE = 16000
SAMPLE_BYTES = 2
CHANNELS = 1
MIN_DURATION_S = 0.3
MAX_CHUNKS = 16  # a canonical file has fmt + data, maybe LIST; a pile of chunks is a malformed or hostile file


@dataclass(frozen=True)
class PcmAudio:
    pcm: bytes  # little-endian int16, mono, 16 kHz
    duration_s: float
    peak: float  # 0..1 of full scale
    rms: float  # 0..1 of full scale

    @property
    def frames(self) -> int:
        return len(self.pcm) // SAMPLE_BYTES


def max_body_bytes(max_duration_s: float) -> int:
    """Largest request body that can still hold `max_duration_s` of audio (44-byte header plus slack for a LIST chunk)."""
    return int(max_duration_s * SAMPLE_RATE * SAMPLE_BYTES) + 4096


def _levels(pcm: bytes) -> tuple[float, float]:
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder == "big":
        samples.byteswap()
    peak = max(max(samples), -min(samples)) / 32768
    rms = sqrt(sum(map(mul, samples, samples)) / len(samples)) / 32768
    return peak, rms


def parse_wav(data: bytes, *, max_bytes: int, max_duration_s: float) -> PcmAudio:
    """Validate and unwrap a WAV file. Raises a SpeechError subclass; the messages never echo the content."""
    if not data:
        raise AudioEmpty()
    if len(data) > max_bytes:
        raise AudioTooLong("The audio file is larger than the allowed maximum.")
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise InvalidAudio("The audio is not a WAV file.")

    fmt: tuple[int, int, int, int, int, int] | None = None
    pcm: bytes | None = None
    offset = 12
    for _ in range(MAX_CHUNKS):
        if offset + 8 > len(data):
            break
        chunk_id, size = data[offset : offset + 4], struct.unpack_from("<I", data, offset + 4)[0]
        body = offset + 8
        if chunk_id == b"fmt ":
            if size < 16 or body + 16 > len(data):
                raise InvalidAudio("The WAV header is incomplete.")
            fmt = struct.unpack_from("<HHIIHH", data, body)  # tag, channels, rate, byte rate, block align, bits
        elif chunk_id == b"data":
            if fmt is None:
                raise InvalidAudio("The WAV data comes before its format description.")
            if body + size > len(data):
                raise InvalidAudio("The audio file is truncated.")
            pcm = data[body : body + size]
            break
        offset = body + size + (size & 1)  # chunks are word-aligned
    if fmt is None or pcm is None:
        raise InvalidAudio("The WAV file has no audio data.")

    tag, channels, rate, byte_rate, block_align, bits = fmt
    if tag != 1:
        raise InvalidAudio("Only uncompressed PCM audio is accepted.")
    if channels != CHANNELS or bits != 16 or rate != SAMPLE_RATE:
        raise InvalidAudio("The audio must be mono, 16-bit, 16 kHz.")
    if block_align != SAMPLE_BYTES or byte_rate != SAMPLE_RATE * SAMPLE_BYTES or len(pcm) % SAMPLE_BYTES:
        raise InvalidAudio("The WAV header is inconsistent.")
    if not pcm:
        raise AudioEmpty()

    duration = len(pcm) / (SAMPLE_RATE * SAMPLE_BYTES)
    if duration > max_duration_s:
        raise AudioTooLong(f"The audio is longer than {max_duration_s:g} seconds.")
    if duration < MIN_DURATION_S:
        raise AudioTooShort()
    peak, rms = _levels(pcm)
    return PcmAudio(pcm=pcm, duration_s=round(duration, 3), peak=peak, rms=rms)
