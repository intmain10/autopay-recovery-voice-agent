from datetime import date

from app import policy, voices
from app.assistant import build_assistant, call_overrides
from app.db import get_customer


def test_hindi_override_uses_hindi_voice_transcriber_and_greeting():
    o = call_overrides(get_customer("C001"), "hi", "")
    assert o["voice"]["provider"] == "cartesia" and o["voice"]["language"] == "hi"
    assert o["transcriber"]["language"] == "hi" and o["transcriber"]["model"] == "nova-3"
    assert "Priya Sharma" in o["transcriber"]["keyterm"] and "UPI" in o["transcriber"]["keyterm"]
    assert o["transcriber"]["fallbackPlan"]["transcribers"][0]["language"] == "hi-IN"
    assert "नमस्ते" in o["firstMessage"] and "{merchant}" not in o["firstMessage"]
    assert o["variableValues"]["customer_id"] == "C001" and o["variableValues"]["agent_name"] == "Kavita"


def test_male_hindi_voice_uses_masculine_verb():
    o = call_overrides(get_customer("C001"), "hi", "amrit")
    assert "बोल रहा हूँ" in o["firstMessage"] and o["variableValues"]["agent_gender"] == "male"


def test_voice_from_other_language_falls_back_to_default():
    assert voices.resolve("en", "kavita") == ("en", "naina")
    assert voices.resolve("xx", "") == ("en", "naina")


def test_prompt_has_no_unrendered_python_placeholders():
    prompt = build_assistant()["model"]["messages"][0]["content"]
    assert "{merchant}" not in prompt and "{{agent_name}}" in prompt and "{{language}}" in prompt


def test_spoken_dates_have_correct_weekday():
    assert policy.spoken_date(date(2026, 9, 30)) == "Wednesday, 30 September"
    days = policy.next_days(date(2026, 10, 4))
    assert len(days) == 7 and days[0] == {"date": "2026-10-05", "spoken": "Monday, 5 October"}
