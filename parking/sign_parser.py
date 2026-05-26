"""
Sign parser: vision-based (image) and text-based (OCR string) inputs.
Both return the same structured dict consumed by rule_engine.
"""
import anthropic
import base64
import json
import re

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# ── Shared schema / rules ──────────────────────────────────────────────────

_SCHEMA_AND_RULES = """\
Return ONLY a JSON object — no markdown, no code fences, no explanation.

Schema:
{
  "sign_text": "verbatim text from sign",
  "rules": [
    {
      "restriction": "<see types below>",
      "days": ["MON","TUE","WED","THU","FRI","SAT","SUN"],
      "all_week": false,
      "start_time": "HH:MM",
      "end_time":   "HH:MM",
      "all_day":    false,
      "duration_limit_minutes": null,
      "permit_type": null,
      "conditions":  null,
      "vehicle_type": null
    }
  ],
  "interpretation": "plain English summary of when you can and cannot park"
}

Restriction types — use EXACTLY one of these values:
  NO_PARKING      General no-parking restriction
  NO_STOPPING     Tow-away zone / no stopping / no standing at any time
  STREET_CLEANING Street sweeping / street cleaning (usually 1-2 hrs/week per block)
  TIMED_PARKING   Can park but only for the stated duration (e.g. "2 HOUR PARKING")
  PERMIT_ONLY     Residential or area permit required (e.g. "PERMIT ZONE A")
  DISABLED_ONLY   Disabled / handicap placard or plate required (blue wheelchair sign)
  LOADING_ZONE    Commercial loading and unloading only
  BUS_ZONE        Bus stop / transit zone — no public parking
  FIRE_LANE       Fire lane or fire hydrant clearance zone
  EV_CHARGING     Electric vehicle charging only
  FREE_PARKING    Explicitly unrestricted / free parking

Parsing rules:
- Times: 24-hour format (08:00 = 8 AM, 18:00 = 6 PM)
- "MON THRU FRI"        → days: ["MON","TUE","WED","THU","FRI"]
- "EXCEPT SUNDAYS"      → exclude SUN from days array
- "MON, WED, FRI"       → days: ["MON","WED","FRI"]
- No time stated        → all_day: true
- "NO PARKING ANY TIME" → restriction: NO_PARKING, all_week: true, all_day: true
- "2 HOUR PARKING"      → restriction: TIMED_PARKING, duration_limit_minutes: 120
- "30 MINUTE PARKING"   → restriction: TIMED_PARKING, duration_limit_minutes: 30
- Multiple stacked signs → one rule object per sign
- "STREET SWEEPING / CLEANING" on specific days → STREET_CLEANING
- "TOWING ENFORCED" / "TOW AWAY ZONE" → NO_STOPPING
- "HANDICAPPED PARKING" / "ACCESSIBLE PARKING" → DISABLED_ONLY
- "LOADING ZONE", "COMMERCIAL LOADING" → LOADING_ZONE
- "BUS STOP", "BUS ZONE" → BUS_ZONE
- "EV CHARGING", "ELECTRIC VEHICLE ONLY" → EV_CHARGING
- permit_type: the permit zone letter/number if stated (e.g. "A", "B", "12")
- vehicle_type: only set if restriction explicitly targets a vehicle type (e.g. "TRUCKS")
"""

_IMAGE_PROMPT = f"You are a parking sign expert. Analyze the attached image of a parking sign.\n\n{_SCHEMA_AND_RULES}"

_TEXT_PROMPT  = f"You are a parking sign expert. Parse the following parking sign text into structured rules.\n\nSign text:\n{{sign_text}}\n\n{_SCHEMA_AND_RULES}"


# ── Helpers ────────────────────────────────────────────────────────────────

def _clean_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text.strip())
    return json.loads(text.strip())


# ── Public functions ────────────────────────────────────────────────────────

def parse_sign_image(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Extract parking rules from a sign photograph via Claude Vision."""
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type":       "base64",
                        "media_type": media_type,
                        "data":       b64,
                    },
                },
                {"type": "text", "text": _IMAGE_PROMPT},
            ],
        }],
    )

    return _clean_json(message.content[0].text)


def parse_ocr_text(sign_text: str) -> dict:
    """Extract parking rules from OCR-extracted plain text (no image needed)."""
    prompt = _TEXT_PROMPT.format(sign_text=sign_text.strip())

    message = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    return _clean_json(message.content[0].text)
