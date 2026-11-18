import hashlib

from fit_ai.ai import ChatMessage, load_system_prompt


def test_system_prompt_loads_with_version_language_and_a_stable_fingerprint():
    p = load_system_prompt()
    assert (p.version, p.language) == ("1", "pt-BR")
    assert p.sha256 == hashlib.sha256(p.text.encode("utf-8")).hexdigest()
    assert load_system_prompt() == p


def test_system_prompt_states_the_required_rules():
    t = load_system_prompt().text.lower()
    for needle in ("português do brasil", "ferramenta", "nunca invente", "simulados", "não controla", "não os confirme",
                   "não está disponível", "atenção na estrada"):
        assert needle in t, needle


def test_system_prompt_contains_no_vehicle_facts_or_personal_data():
    t = load_system_prompt().text
    # no concrete readings, VIN, plates or contact data may live in the prompt
    assert not any(ch.isdigit() for ch in t)
    for forbidden in ("@", "http", "VIN", "placa"):
        assert forbidden not in t


def test_system_prompt_becomes_a_system_message():
    m = load_system_prompt().as_message()
    assert isinstance(m, ChatMessage) and m.role == "system" and m.content.startswith("Você é o assistente")
