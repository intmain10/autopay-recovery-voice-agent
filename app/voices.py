"""Language + voice catalogue. Every combination below was validated against the Vapi API.

A call picks a language (en / hi) and a voice; both are applied as per-call assistantOverrides,
so a single assistant serves every language and voice.
"""
from __future__ import annotations

import os

from . import config

# Words the recognizer should expect in a collections call (Deepgram nova-3 "keyterm" boosting).
KEYTERMS = ["AutoPay", "UPI", "PIN code", "payment link", "installment", "late fee", "mandate", "Razorpay"]

# Hindi speech-to-text. Deepgram nova-3 "multi" was tried first and dropped Hindi speech entirely
# (only digits and English survived), so Hindi uses a dedicated Hindi model, with Azure as fallback.
# Switch with HINDI_STT=deepgram|azure|11labs|google in .env if one works better for your accent.
HINDI_STT = {
    "deepgram": {"provider": "deepgram", "model": "nova-3", "language": "hi",
                 "fallbackPlan": {"transcribers": [{"provider": "azure", "language": "hi-IN"}]}},
    "azure": {"provider": "azure", "language": "hi-IN"},
    "11labs": {"provider": "11labs", "model": "scribe_v1", "language": "hi"},
    "google": {"provider": "google", "model": "gemini-2.0-flash", "language": "Hindi"},
}

LANGUAGES = {
    "en": {
        "label": "English",
        "default_voice": "naina",
        "transcriber": {"provider": "deepgram", "model": "nova-2", "language": "en-IN"},
        "first_message": ("Hi, this is {{agent_name}}, an AI assistant calling from {merchant}. This call may be "
                          "recorded for quality. Am I speaking with {{customer_name}}?"),
        "voicemail": ("Hi, this is {{agent_name}} from {merchant} with a message for {{customer_name}}. "
                      "Please call us back at {support} regarding your account. Thank you."),
        "end_call": "Thank you for your time. Have a great day!",
    },
    "hi": {
        "label": "हिंदी (Hindi)",
        "default_voice": "kavita",
        "transcriber": HINDI_STT.get(os.getenv("HINDI_STT", "deepgram"), HINDI_STT["deepgram"]),
        "first_message": ("नमस्ते, मैं {{agent_name}} बोल रही हूँ, {merchant} की AI assistant. यह call quality के लिए "
                          "record हो सकती है. क्या मेरी बात {{customer_name}} जी से हो रही है?"),
        "voicemail": ("नमस्ते, मैं {merchant} से {{agent_name}} बोल रही हूँ, {{customer_name}} जी के लिए message है. "
                      "कृपया अपने account के बारे में हमें {support} पर call करें. धन्यवाद."),
        "end_call": "आपके समय के लिए धन्यवाद. आपका दिन शुभ हो!",
    },
}

# agent_name follows the voice so a male voice doesn't introduce itself as "Asha".
VOICES = {
    "naina":   {"label": "Naina · female · Indian English", "lang": "en", "agent_name": "Naina", "gender": "f",
                "voice": {"provider": "vapi", "voiceId": "Naina"}},
    "aarti":   {"label": "Aarti HD · female · Indian English", "lang": "en", "agent_name": "Aarti", "gender": "f",
                "voice": {"provider": "azure", "voiceId": "en-IN-Aarti:DragonHDLatestNeural"}},
    "rohan":   {"label": "Rohan · male · Indian English", "lang": "en", "agent_name": "Rohan", "gender": "m",
                "voice": {"provider": "vapi", "voiceId": "Rohan"}},
    "kavita":  {"label": "Kavita · female · customer care", "lang": "hi", "agent_name": "Kavita", "gender": "f",
                "voice": {"provider": "cartesia", "voiceId": "56e35e2d-6eb6-4226-ab8b-9776515a7094",
                          "model": "sonic-3", "language": "hi"}},
    "diya":    {"label": "Diya · female · service specialist", "lang": "hi", "agent_name": "Diya", "gender": "f",
                "voice": {"provider": "cartesia", "voiceId": "d2d3584d-1b44-428e-aab1-30255d28d978",
                          "model": "sonic-3", "language": "hi"}},
    "esha":    {"label": "Esha · female · calm", "lang": "hi", "agent_name": "Esha", "gender": "f",
                "voice": {"provider": "cartesia", "voiceId": "72656902-fb4b-4c31-af52-c3b68e2cae26",
                          "model": "sonic-3", "language": "hi"}},
    "amrit":   {"label": "Amrit · male · helpful guide", "lang": "hi", "agent_name": "Amrit", "gender": "m",
                "voice": {"provider": "cartesia", "voiceId": "97303aad-1a66-4edf-870a-58e6ba545005",
                          "model": "sonic-3", "language": "hi"}},
}


def resolve(lang: str, voice_key: str = "") -> tuple:
    lang = lang if lang in LANGUAGES else "en"
    if voice_key not in VOICES or VOICES[voice_key]["lang"] != lang:
        voice_key = LANGUAGES[lang]["default_voice"]
    return lang, voice_key


def _fmt(text: str) -> str:
    return text.replace("{merchant}", config.MERCHANT_NAME).replace("{support}", config.SUPPORT_NUMBER)


def overrides(lang: str, voice_key: str, variables: dict) -> dict:
    """assistantOverrides for one call: voice, transcriber, greeting and prompt variables."""
    lang, voice_key = resolve(lang, voice_key)
    L, V = LANGUAGES[lang], VOICES[voice_key]
    first, voicemail = L["first_message"], L["voicemail"]
    if V["gender"] == "m":  # Hindi verbs are gendered
        first, voicemail = first.replace("बोल रही", "बोल रहा"), voicemail.replace("बोल रही", "बोल रहा")
    transcriber = dict(L["transcriber"])
    if transcriber["provider"] == "deepgram" and transcriber.get("model") == "nova-3":
        transcriber["keyterm"] = KEYTERMS + [variables.get("customer_name", "")] if variables.get("customer_name") else KEYTERMS
    return {
        "voice": V["voice"],
        "transcriber": transcriber,
        "firstMessage": _fmt(first),
        "voicemailMessage": _fmt(voicemail),
        "endCallMessage": L["end_call"],
        "variableValues": {**variables, "agent_name": V["agent_name"], "language": lang,
                           "agent_gender": "male" if V["gender"] == "m" else "female"},
    }


def catalogue() -> dict:
    return {
        "languages": {k: {"label": v["label"], "default_voice": v["default_voice"]} for k, v in LANGUAGES.items()},
        "voices": {k: {"label": v["label"], "lang": v["lang"]} for k, v in VOICES.items()},
    }
