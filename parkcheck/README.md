# 🅿 Can I Park Here?

> **Photograph a parking sign → get an instant Park / Do Not Park answer.**  
> Powered by Claude, GPT-4o, or Google Gemini. Bring your own API key.

---

## What it does

You photograph (or paste the text of) any US parking sign. The app:

1. Sends the image to your chosen AI model, which reads every restriction off the sign
2. Passes the extracted rules through a deterministic rule engine
3. Evaluates the rules against the **current date and time** and your **vehicle details**
4. Shows a clear **YES / NO verdict** plus a colour-coded weekly schedule so you can see the full picture at a glance

The weekly schedule is inspired by Nikki Sylianteng's famous *"To Park or Not to Park"* redesign — a simple colour grid that makes complex sign stacks instantly readable.

---

## Features

| Feature | Detail |
|---|---|
| 📷 **Photo or text** | Snap a sign or paste OCR-extracted text |
| 🤖 **Three AI providers** | Anthropic Claude · OpenAI GPT-4o · Google Gemini |
| 🔑 **Your own key** | Enter any API key in the browser — never stored server-side |
| 🚗 **Vehicle-aware** | Regular car, EV, motorcycle, pickup truck, commercial vehicle |
| ♿ **ADA/disabled permit** | Overrides timed restrictions and permit-only zones where US law allows |
| 🏘 **Residential permit** | Zone matching for permit-only streets |
| 📦 **Loading/unloading** | Grants access to commercial loading zones |
| 📅 **Full weekly grid** | See every restriction at a glance, Mon–Sun, 5 AM–11:30 PM |
| ⏰ **Next-change alert** | "Restriction lifts at 6 PM" or "Starts at 8 AM tomorrow" |
| 🔍 **Rule breakdown** | Every rule that fired, and why it was allowed or blocked |
| 🐳 **Docker-ready** | One command to run locally or in the cloud |

---

## Quick start

### Option A — Docker (recommended, no Python needed)

```bash
git clone https://github.com/shubhs0411/can-i-park-here.git
cd can-i-park-here
docker compose up
```

Open **http://localhost:8000**, choose your AI provider, paste your API key, and start checking signs.

---

### Option B — Manual (Python 3.11+)

```bash
git clone https://github.com/shubhs0411/can-i-park-here.git
cd can-i-park-here

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000**.

---

## Getting an API key

You need a key from **one** of these providers. All three work identically in the app.

### Anthropic Claude (recommended)

1. Go to **[console.anthropic.com](https://console.anthropic.com)**
2. Sign up / log in → **API Keys** → **Create Key**
3. New accounts get **$5 free credit** — enough for hundreds of sign checks
4. Your key starts with `sk-ant-`

Model used: `claude-sonnet-4-6`

---

### OpenAI GPT-4o

1. Go to **[platform.openai.com](https://platform.openai.com)**
2. Sign up / log in → **API Keys** → **Create new secret key**
3. Requires a paid account (no free tier for GPT-4o)
4. Your key starts with `sk-proj-` or `sk-`

Model used: `gpt-4o`

---

### Google Gemini

1. Go to **[aistudio.google.com](https://aistudio.google.com)**
2. Sign in → **Get API key** → **Create API key**
3. **Free tier available** — generous limits for personal use
4. Your key starts with `AIza`

Model used: `gemini-1.5-flash`

---

## Deploying online (share with others)

Once deployed, anyone with a browser can use it with their own API key.

### Render (free tier available)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

Or manually:

```bash
# 1. Push to GitHub (see below)
# 2. Go to render.com → New → Web Service → connect your repo
# 3. Render auto-detects render.yaml and deploys
```

The included `render.yaml` handles all the configuration automatically.

---

### Railway

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway init
railway up
```

Or use the Railway dashboard → New Project → Deploy from GitHub repo.

---

### Fly.io

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/

fly launch       # follow the prompts, accepts the Dockerfile
fly deploy
```

---

### Heroku

```bash
heroku create your-app-name
git push heroku main
heroku open
```

The `Procfile` is already included.

---

### Any VPS / server (nginx + systemd)

```bash
# On the server
git clone https://github.com/shubhs0411/can-i-park-here.git
cd can-i-park-here
pip install -r requirements.txt

# Run as a service
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Reverse-proxy with nginx (point to port 8000)
# Add HTTPS with certbot / Let's Encrypt
```

---

## Environment variables

These are optional. The app works without any environment variables — users enter their own API keys in the browser.

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Port the server listens on |
| `HOST` | `0.0.0.0` | Bind address |

Copy `.env.example` to `.env` to customise.

---

## API reference

The app exposes a REST API. Interactive docs are at `/api/docs` (Swagger) and `/api/redoc`.

### `POST /api/check` — check from photo

Multipart form data:

| Field | Type | Required | Description |
|---|---|---|---|
| `image` | file | ✓ | Sign photo (JPEG, PNG, WEBP) |
| `provider` | string | ✓ | `anthropic` · `openai` · `google` |
| `api_key` | string | ✓ | Your API key |
| `vehicle_type` | string | | `regular` · `ev` · `motorcycle` · `truck` · `commercial` |
| `has_disabled` | bool | | ADA/disabled permit |
| `has_permit` | bool | | Residential permit |
| `permit_zone` | string | | Zone letter/number (e.g. `A`, `Zone 3`) |
| `is_loading` | bool | | Actively loading/unloading |

### `POST /api/check-text` — check from OCR text

JSON body:

```json
{
  "sign_text":    "NO PARKING\n8AM-6PM\nMON THRU FRI",
  "provider":     "anthropic",
  "api_key":      "sk-ant-...",
  "vehicle_type": "regular",
  "has_disabled": false,
  "has_permit":   false,
  "permit_zone":  "",
  "is_loading":   false
}
```

### Response shape (both endpoints)

```json
{
  "sign_text": "NO PARKING 8AM-6PM MON THRU FRI",
  "interpretation": "You cannot park Mon–Fri 8 AM–6 PM.",
  "rules": [ { "restriction": "NO_PARKING", "days": ["MON",...], ... } ],
  "grid": { "MON": [ { "slot": 10, "time": "05:00", "status": "CAN_PARK" }, ... ], ... },
  "verdict": {
    "decision":             "DO_NOT_PARK",
    "status":               "CANNOT_PARK",
    "can_park":             false,
    "headline":             "NO, YOU CANNOT PARK HERE.",
    "reason":               "No parking · Mon/Tue/Wed/Thu/Fri · 8 AM–6 PM. Restriction lifts at 6 PM.",
    "warnings":             [],
    "triggered_rules":      [ { "restriction": "NO_PARKING", "description": "...", "blocking": true, "exemption_applied": null } ],
    "max_duration_minutes": null,
    "next_change_at":       "6 PM",
    "current_day":          "TUE",
    "current_time":         "3:30 PM",
    "current_day_full":     "Tuesday",
    "current_slot":         30,
    "day_index":            1
  }
}
```

### `GET /health`

Returns `{"status": "ok", "version": "1.0.0"}`. Used by load balancers / health checks.

---

## How the rule engine works

The engine evaluates a strict 8-level priority chain. Each level checks the current day and time, then applies any vehicle or permit exemptions before blocking:

```
Priority   Restriction      Exemptions
────────   ─────────────    ──────────────────────────────────────────
1 (high)   FIRE_LANE        None — absolute block always
2          NO_STOPPING      None — tow-away zone, absolute block
3          BUS_ZONE         None — transit zone, absolute block
4          STREET_CLEANING  None (EV exemption advisory only)
5          NO_PARKING       ADA permit overrides *timed* (non-all-day) restrictions
6          DISABLED_ONLY    ADA/disabled permit grants access
7          LOADING_ZONE     is_loading_unloading grants access (time-capped)
8          PERMIT_ONLY      Matching permit zone OR ADA permit grants access
9          EV_CHARGING      EV vehicle type grants access
10 (low)   TIMED_PARKING    ADA permit removes the time cap
──         (default)        CAN_PARK — no matching rules
```

**ADA/Disabled permit behaviour** (per US federal and most state laws):
- ✓ Overrides: timed NO_PARKING, PERMIT_ONLY zones, TIMED_PARKING limits
- ✗ Does NOT override: absolute all-day zones, street cleaning, tow-away, bus zones, fire lanes

---

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

19 deterministic tests cover every priority level and exemption combination. No network calls required.

---

## Project structure

```
can-i-park-here/
├── app/
│   ├── main.py          FastAPI endpoints
│   ├── providers.py     Anthropic · OpenAI · Google sign parsers
│   ├── rule_engine.py   8-level priority rule evaluator
│   ├── models.py        Dataclasses and enums
│   └── static/
│       └── index.html   Single-page frontend (no framework)
├── tests/
│   └── test_rule_engine.py
├── Dockerfile
├── docker-compose.yml
├── render.yaml          Render one-click deploy config
├── Procfile             Heroku config
└── requirements.txt
```

---

## Security notes

- API keys are transmitted over HTTPS (TLS) to the backend, used for exactly one AI call, and **never written to disk or a database**.
- The optional "Remember on this device" feature saves the key to **browser localStorage only** — it never leaves your browser to the server on subsequent visits (it's re-sent per request, but only when you click "Check").
- The backend does not log request bodies.
- For a shared/public deployment, consider adding rate limiting (e.g. `slowapi`) and auth.

---

## Contributing

Pull requests are welcome. For large changes, open an issue first.

```bash
git checkout -b feature/my-improvement
# make changes
pytest tests/ -v          # all tests must pass
git push origin feature/my-improvement
# open a pull request
```

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgements

- Weekly schedule visualization inspired by **[Nikki Sylianteng's](https://nikkisylianteng.com) "To Park or Not to Park"** redesign project.
- Built with [FastAPI](https://fastapi.tiangolo.com), [Anthropic Claude](https://docs.anthropic.com), [OpenAI](https://platform.openai.com/docs), [Google Gemini](https://ai.google.dev).
