import pytest

from fit_ai.config import ConfigError
from fit_ai.speech.config import DEFAULT_INITIAL_PROMPT, SpeechSettings


def test_defaults_are_conservative():
    s = SpeechSettings.from_env({})
    assert s.enabled and s.language == "pt" and s.threads == 8 and s.beam_size == 5
    assert s.max_audio_s == 30.0 and s.timeout_s == 30.0 and s.initial_prompt == DEFAULT_INITIAL_PROMPT
    assert s.model_dir.name == "faster-whisper-small" and "runtime" in s.model_dir.parts  # outside the repository
    assert s.max_body_bytes == 30 * 32000 + 4096


def test_every_setting_is_read_from_the_environment(tmp_path):
    s = SpeechSettings.from_env({
        "FIT_AI_STT_ENABLED": "off", "FIT_AI_STT_MODEL_DIR": str(tmp_path), "FIT_AI_STT_THREADS": "2", "FIT_AI_STT_BEAM_SIZE": "1",
        "FIT_AI_STT_TIMEOUT_S": "10", "FIT_AI_STT_MAX_AUDIO_S": "12.5", "FIT_AI_STT_MIN_PEAK": "0.01",
        "FIT_AI_STT_INITIAL_PROMPT": "  Fit  ", "FIT_AI_STT_LANGUAGE": "PT"})
    assert (s.enabled, s.model_dir, s.threads, s.beam_size, s.timeout_s, s.max_audio_s, s.min_peak, s.initial_prompt, s.language) == (
        False, tmp_path, 2, 1, 10.0, 12.5, 0.01, "Fit", "pt")


def test_the_vocabulary_hint_can_be_turned_off():
    assert SpeechSettings.from_env({"FIT_AI_STT_INITIAL_PROMPT": ""}).initial_prompt == ""


@pytest.mark.parametrize("env", [
    {"FIT_AI_STT_THREADS": "0"}, {"FIT_AI_STT_THREADS": "99"}, {"FIT_AI_STT_THREADS": "x"},
    {"FIT_AI_STT_BEAM_SIZE": "0"}, {"FIT_AI_STT_BEAM_SIZE": "50"},
    {"FIT_AI_STT_TIMEOUT_S": "1"}, {"FIT_AI_STT_TIMEOUT_S": "nan"}, {"FIT_AI_STT_TIMEOUT_S": "9999"},
    {"FIT_AI_STT_MAX_AUDIO_S": "0"}, {"FIT_AI_STT_MAX_AUDIO_S": "300"},
    {"FIT_AI_STT_MIN_PEAK": "-1"}, {"FIT_AI_STT_MIN_PEAK": "0.9"},
    {"FIT_AI_STT_ENABLED": "maybe"},
    {"FIT_AI_STT_LANGUAGE": "en"}, {"FIT_AI_STT_LANGUAGE": "auto"},
    {"FIT_AI_STT_INITIAL_PROMPT": "x" * 201}, {"FIT_AI_STT_INITIAL_PROMPT": "a\nb"},
])
def test_invalid_values_are_refused(env):
    with pytest.raises(ConfigError):
        SpeechSettings.from_env(env)


@pytest.mark.parametrize("where", [
    "https://huggingface.co/Systran/faster-whisper-small", "http://127.0.0.1/model", "ftp://example/model", "s3://bucket/model",
    "\\\\server\\share\\model", "//server/share/model", "Systran/faster-whisper-small:main", "hf:Systran/faster-whisper-small",
])
def test_the_model_can_only_be_a_local_directory(where):
    with pytest.raises(ConfigError, match="local directory"):
        SpeechSettings.from_env({"FIT_AI_STT_MODEL_DIR": where})


@pytest.mark.parametrize("where", ["C:\\models\\fw", "D:/models/fw", "models/fw", "../runtime/stt-models/fw"])
def test_local_paths_are_accepted(where):
    assert SpeechSettings.from_env({"FIT_AI_STT_MODEL_DIR": where}).enabled
