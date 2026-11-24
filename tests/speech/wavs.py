"""Builders for test audio. Synthetic sine tones only: no real speech, no recordings."""
from __future__ import annotations

import math
import struct
from array import array


def pcm_sine(seconds: float, *, rate: int = 16000, amplitude: float = 0.3, freq: float = 440.0) -> bytes:
    n = int(seconds * rate)
    samples = array("h", (int(amplitude * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)))
    return samples.tobytes()


def make_wav(seconds: float = 1.0, *, rate: int = 16000, channels: int = 1, bits: int = 16, tag: int = 1, amplitude: float = 0.3,
             pcm: bytes | None = None, extra_chunks: int = 0, data_before_fmt: bool = False, declared_extra: int = 0,
             byte_rate: int | None = None, block_align: int | None = None) -> bytes:
    """A canonical WAV (RIFF, fmt, data) with knobs to break one thing at a time."""
    body = pcm if pcm is not None else pcm_sine(seconds, rate=rate, amplitude=amplitude)
    block = block_align if block_align is not None else channels * bits // 8
    brate = byte_rate if byte_rate is not None else rate * block
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, tag, channels, rate, brate, block, bits)
    data = b"data" + struct.pack("<I", len(body) + declared_extra) + body + (b"\0" if len(body) & 1 else b"")
    junk = b"".join(b"JUNK" + struct.pack("<I", 4) + b"abcd" for _ in range(extra_chunks))
    chunks = (data + fmt) if data_before_fmt else (fmt + junk + data)
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks
