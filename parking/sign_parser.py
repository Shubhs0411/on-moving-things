import anthropic
import base64
import json
import re

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


_PROMPT = """You are a parking sign expert. Analyze this image of a parking sign and extract all rules as structured JSON.

Return ONLY a JSON object — no markdown, no explanation, no code fences.

Schema:
{
  "sign_text": "verbatim text from sign",
  "rules": [
    {
      "restriction": "NO_PARKING | TIMED_PARKING | PERMIT_ONLY | NO_STOPPING | FREE_PARKING",
      "days": ["MON","TUE","WED","THU","FRI","SAT","SUN"],
      "all_week": false,
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "all_day": false,
      "duration_limit_minutes": null,
      "permit_type": null,
      "conditions": null,
      "vehicle_type": null
    }
  ],
  "interpretation": "plain English summary"
}

Parsing rules:
- Times are 24-hour (08:00 = 8 AM, 18:00 = 6 PM)
- "MON THRU FRI" → days: ["MON","TUE","WED","THU","FRI"]
- "EXCEPT SUNDAYS" → exclude SUN from days
- No time on a rule → all_day: true
- "NO PARKING ANY TIME" → restriction: NO_PARKING, all_week: true, all_day: true
- "2 HOUR PARKING" → restriction: TIMED_PARKING, duration_limit_minutes: 120
- Multiple stacked signs → multiple rule objects
- If no restriction applies to a time period, outside-hours parking is FREE_PARKING
- "TOWING AWAY ZONE" = NO_STOPPING
"""


def parse_sign_image(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                },
                {"type": "text", "text": _PROMPT},
            ],
        }],
    )

    text = message.content[0].text.strip()
    # Strip any accidental markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text.strip())

    return json.loads(text.strip())
