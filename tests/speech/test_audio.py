import pytest

from fit_ai.speech.audio import MAX_CHUNKS, max_body_bytes, parse_wav
from fit_ai.speech.errors import AudioEmpty, AudioTooLong, AudioTooShort, InvalidAudio

from .wavs import make_wav, pcm_sine

LIMIT = max_body_bytes(30.0)


def parse(data, **kw):
    return parse_wav(data, max_bytes=kw.pop("max_bytes", LIMIT), max_duration_s=kw.pop("max_duration_s", 30.0))


def test_valid_audio_is_unwrapped_with_its_levels():
    audio = parse(make_wav(1.5, amplitude=0.5))
    assert audio.duration_s == 1.5 and audio.frames == 24000 and len(audio.pcm) == 48000
    assert 0.49 < audio.peak <= 0.5 and 0.34 < audio.rms < 0.36  # a sine's rms is peak / sqrt(2)


def test_silence_has_zero_levels():
    audio = parse(make_wav(pcm=bytes(32000)))
    assert audio.peak == 0 and audio.rms == 0


def test_unknown_chunks_before_the_data_are_skipped():
    assert parse(make_wav(1.0, extra_chunks=3)).duration_s == 1.0


@pytest.mark.parametrize("data, error", [
    (b"", AudioEmpty),
    (b"RIFF", InvalidAudio),
    (b"not a wav file at all, just text" * 10, InvalidAudio),
    (b"RIFF\x00\x00\x00\x00AVI " + bytes(40), InvalidAudio),  # RIFF but not WAVE
    (b"\x89PNG\r\n\x1a\n" + bytes(100), InvalidAudio),
])
def test_not_a_wav_file(data, error):
    with pytest.raises(error):
        parse(data)


def test_truncated_file_is_refused():
    wav = make_wav(2.0)
    with pytest.raises(InvalidAudio, match="truncated"):
        parse(wav[: len(wav) // 2])


def test_header_declaring_more_data_than_present_is_refused():
    with pytest.raises(InvalidAudio, match="truncated"):
        parse(make_wav(1.0, declared_extra=1000))


def test_data_without_fmt_is_refused():
    with pytest.raises(InvalidAudio):
        parse(make_wav(1.0, data_before_fmt=True))


def test_header_without_audio_chunk_is_refused():
    wav = make_wav(1.0)
    with pytest.raises(InvalidAudio):
        parse(wav[:36])  # RIFF + WAVE + fmt only


@pytest.mark.parametrize("kw", [
    {"rate": 44100}, {"rate": 8000}, {"rate": 48000}, {"channels": 2}, {"bits": 8}, {"bits": 24}, {"bits": 32}, {"tag": 3}, {"tag": 0xFFFE},
])
def test_only_16khz_mono_16bit_pcm_is_accepted(kw):
    with pytest.raises(InvalidAudio):
        parse(make_wav(1.0, **kw))


def test_inconsistent_header_is_refused():
    with pytest.raises(InvalidAudio):
        parse(make_wav(1.0, byte_rate=12345))
    with pytest.raises(InvalidAudio):
        parse(make_wav(1.0, block_align=4))


def test_odd_number_of_data_bytes_is_refused():
    with pytest.raises(InvalidAudio):
        parse(make_wav(pcm=pcm_sine(1.0) + b"\x01"))


def test_empty_data_chunk_is_empty_audio():
    with pytest.raises(AudioEmpty):
        parse(make_wav(pcm=b""))


def test_too_short():
    with pytest.raises(AudioTooShort):
        parse(make_wav(0.1))


def test_too_long_by_duration():
    with pytest.raises(AudioTooLong):
        parse(make_wav(5.0), max_duration_s=3.0)


def test_too_big_by_bytes_is_refused_before_looking_inside():
    with pytest.raises(AudioTooLong):
        parse(b"RIFF" + bytes(LIMIT), max_bytes=LIMIT)


def test_a_pile_of_chunks_is_not_followed_forever():
    with pytest.raises(InvalidAudio):
        parse(make_wav(1.0, extra_chunks=MAX_CHUNKS + 4))


def test_error_messages_never_echo_the_content():
    secret = b"RIFF" + b"SECRET-TRANSCRIPT" * 4
    with pytest.raises(InvalidAudio) as e:
        parse(secret)
    assert "SECRET" not in str(e.value)
