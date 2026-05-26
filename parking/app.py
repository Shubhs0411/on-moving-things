from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .sign_parser import parse_sign_image
from .rule_engine import generate_weekly_grid, get_current_verdict

app = FastAPI(title="Can I Park Here?", description="Parking sign reader with visual schedule")

_STATIC = Path(__file__).parent / "static"


@app.post("/api/check")
async def check_sign(
    image: UploadFile = File(...),
    vehicle_type: str = Form(default="regular"),
    has_permit: bool = Form(default=False),
    permit_type: str = Form(default=""),
):
    contents = await image.read()
    media_type = image.content_type or "image/jpeg"

    parsed = parse_sign_image(contents, media_type)
    rules = parsed.get("rules", [])

    grid = generate_weekly_grid(rules, vehicle_type, has_permit)
    verdict = get_current_verdict(rules, vehicle_type, has_permit)

    return {
        "sign_text": parsed.get("sign_text", ""),
        "interpretation": parsed.get("interpretation", ""),
        "rules": rules,
        "grid": grid,
        "verdict": verdict,
    }


@app.get("/")
async def index():
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
