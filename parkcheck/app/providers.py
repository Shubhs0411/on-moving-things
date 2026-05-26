"""
Multi-provider AI sign parser.
Supports Anthropic Claude, OpenAI GPT-4o, and Google Gemini.
Each provider uses its vision API for images and its text API for OCR strings.
"""
from __future__ import annotations

import base64
import json
import re
from enum import Enum


class Provider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI    = "openai"
    GOOGLE    = "google"


PROVIDER_MODELS = {
    Provider.ANTHROPIC: "claude-sonnet-4-6",
    Provider.OPENAI:    "gpt-4o",
    Provider.GOOGLE:    "gemini-1.5-flash",
}

PROVIDER_LABELS = {
    Provider.ANTHROPIC: "Anthropic Claude",
    Provider.OPENAI:    "OpenAI GPT-4o",
    Provider.GOOGLE:    "Google Gemini",
}


# ── Shared prompt ─────────────────────────────────────────────────────────────

_SCHEMA = """\
Return ONLY a JSON object — no markdown, no code fences, no explanation.

{
  "sign_text": "verbatim text visible on the sign",
  "rules": [
    {
      "restriction": "<see types below>",
      "days":        ["MON","TUE","WED","THU","FRI","SAT","SUN"],
      "all_week":    false,
      "start_time":  "HH:MM",
      "end_time":    "HH:MM",
      "all_day":     false,
      "duration_limit_minutes": null,
      "permit_type":  null,
      "conditions":   null,
      "vehicle_type": null
    }
  ],
  "interpretation": "plain English: when you can and cannot park here"
}

Restriction types — use EXACTLY one value per rule:
  NO_PARKING       General no-parking restriction
  NO_STOPPING      Tow-away zone / no stopping / no standing
  STREET_CLEANING  Street sweeping (weekly, specific days/hours)
  TIMED_PARKING    Can park but only for a stated duration
  PERMIT_ONLY      Residential or area permit required
  DISABLED_ONLY    Disabled/handicap placard or plate required
  LOADING_ZONE     Commercial loading and unloading only
  BUS_ZONE         Bus stop — no public parking
  FIRE_LANE        Fire lane or fire-hydrant clearance zone
  EV_CHARGING      Electric vehicle charging only
  FREE_PARKING     Explicitly unrestricted / free

Parsing rules:
- Times are 24-hour format  (08:00 = 8 AM,  18:00 = 6 PM)
- "MON THRU FRI"             → days: ["MON","TUE","WED","THU","FRI"]
- "EXCEPT SUNDAYS"           → exclude SUN from days array
- No time stated             → all_day: true
- "NO PARKING ANY TIME"      → restriction: NO_PARKING, all_week: true, all_day: true
- "2 HOUR PARKING"           → TIMED_PARKING, duration_limit_minutes: 120
- "30 MINUTE PARKING"        → TIMED_PARKING, duration_limit_minutes: 30
- Multiple stacked signs     → one rule object per sign panel
- "TOWING ENFORCED"          → NO_STOPPING
- "HANDICAPPED" / "ACCESSIBLE PARKING" → DISABLED_ONLY
- "STREET SWEEPING"          → STREET_CLEANING
- permit_type                → zone letter/number if stated (e.g. "A", "B", "12")
- vehicle_type               → only set if the rule explicitly targets one type (e.g. "TRUCKS")"""

_VISION_PROMPT = f"You are a parking sign expert. Analyze this parking sign image.\n\n{_SCHEMA}"
_TEXT_PROMPT   = "You are a parking sign expert. Parse this parking sign text:\n\n{{text}}\n\n" + _SCHEMA


# ── JSON cleaner ──────────────────────────────────────────────────────────────

def _clean(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw.strip())
    return json.loads(raw.strip())


# ── Anthropic ─────────────────────────────────────────────────────────────────

def _anth_image(image_bytes: bytes, media_type: str, api_key: str) -> dict:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("Run: pip install anthropic")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=PROVIDER_MODELS[Provider.ANTHROPIC],
        max_tokens=1024,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(image_bytes).decode(),
            }},
            {"type": "text", "text": _VISION_PROMPT},
        ]}],
    )
    return _clean(msg.content[0].text)


def _anth_text(sign_text: str, api_key: str) -> dict:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("Run: pip install anthropic")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=PROVIDER_MODELS[Provider.ANTHROPIC],
        max_tokens=1024,
        messages=[{"role": "user", "content": _TEXT_PROMPT.format(text=sign_text)}],
    )
    return _clean(msg.content[0].text)


# ── OpenAI ────────────────────────────────────────────────────────────────────

def _oai_image(image_bytes: bytes, media_type: str, api_key: str) -> dict:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("Run: pip install openai")
    client = OpenAI(api_key=api_key)
    b64 = base64.standard_b64encode(image_bytes).decode()
    resp = client.chat.completions.create(
        model=PROVIDER_MODELS[Provider.OPENAI],
        max_tokens=1024,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
            {"type": "text",      "text": _VISION_PROMPT},
        ]}],
    )
    return _clean(resp.choices[0].message.content)


def _oai_text(sign_text: str, api_key: str) -> dict:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("Run: pip install openai")
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=PROVIDER_MODELS[Provider.OPENAI],
        max_tokens=1024,
        messages=[{"role": "user", "content": _TEXT_PROMPT.format(text=sign_text)}],
    )
    return _clean(resp.choices[0].message.content)


# ── Google Gemini ─────────────────────────────────────────────────────────────

def _goog_image(image_bytes: bytes, _media_type: str, api_key: str) -> dict:
    try:
        import google.generativeai as genai
        import PIL.Image
        import io as _io
    except ImportError:
        raise RuntimeError("Run: pip install google-generativeai pillow")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(PROVIDER_MODELS[Provider.GOOGLE])
    img   = PIL.Image.open(_io.BytesIO(image_bytes))
    resp  = model.generate_content([_VISION_PROMPT, img])
    return _clean(resp.text)


def _goog_text(sign_text: str, api_key: str) -> dict:
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("Run: pip install google-generativeai")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(PROVIDER_MODELS[Provider.GOOGLE])
    resp  = model.generate_content(_TEXT_PROMPT.format(text=sign_text))
    return _clean(resp.text)


# ── Dispatch ──────────────────────────────────────────────────────────────────

_IMAGE_FNS = {
    Provider.ANTHROPIC: _anth_image,
    Provider.OPENAI:    _oai_image,
    Provider.GOOGLE:    _goog_image,
}

_TEXT_FNS = {
    Provider.ANTHROPIC: _anth_text,
    Provider.OPENAI:    _oai_text,
    Provider.GOOGLE:    _goog_text,
}


def parse_sign_image(
    image_bytes: bytes,
    media_type:  str,
    provider:    Provider,
    api_key:     str,
) -> dict:
    return _IMAGE_FNS[provider](image_bytes, media_type, api_key)


def parse_ocr_text(sign_text: str, provider: Provider, api_key: str) -> dict:
    return _TEXT_FNS[provider](sign_text, api_key)
