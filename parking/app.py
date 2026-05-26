from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .models import VehicleContext, VehicleType
from .sign_parser import parse_ocr_text, parse_sign_image
from .rule_engine import generate_weekly_grid, get_current_verdict

app = FastAPI(
    title="Can I Park Here?",
    description="Parking sign reader — image or OCR text → Park / Do Not Park decision",
)

_STATIC = Path(__file__).parent / "static"


def _build_ctx(
    vehicle_type:  str,
    has_disabled:  bool,
    has_permit:    bool,
    permit_zone:   str,
    is_loading:    bool,
) -> VehicleContext:
    try:
        vtype = VehicleType(vehicle_type)
    except ValueError:
        vtype = VehicleType.REGULAR
    return VehicleContext(
        vehicle_type=vtype,
        has_disabled_permit=has_disabled,
        has_residential_permit=has_permit,
        permit_zone=permit_zone,
        is_loading_unloading=is_loading,
    )


def _response(parsed: dict, ctx: VehicleContext) -> dict:
    rules   = parsed.get("rules", [])
    grid    = generate_weekly_grid(rules, ctx=ctx)
    verdict = get_current_verdict(rules, ctx=ctx)
    return {
        "sign_text":     parsed.get("sign_text", ""),
        "interpretation": parsed.get("interpretation", ""),
        "rules":         rules,
        "grid":          grid,
        "verdict":       verdict,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────


@app.post("/api/check")
async def check_sign_image(
    image:        UploadFile = File(...),
    vehicle_type: str  = Form(default="regular"),
    has_disabled: bool = Form(default=False),
    has_permit:   bool = Form(default=False),
    permit_zone:  str  = Form(default=""),
    is_loading:   bool = Form(default=False),
):
    """Accepts a parking-sign photo; returns verdict + weekly grid."""
    contents   = await image.read()
    media_type = image.content_type or "image/jpeg"

    try:
        parsed = parse_sign_image(contents, media_type)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse sign image: {exc}")

    ctx = _build_ctx(vehicle_type, has_disabled, has_permit, permit_zone, is_loading)
    return _response(parsed, ctx)


class TextCheckRequest(BaseModel):
    sign_text:    str
    vehicle_type: str  = "regular"
    has_disabled: bool = False
    has_permit:   bool = False
    permit_zone:  str  = ""
    is_loading:   bool = False


@app.post("/api/check-text")
async def check_sign_text(req: TextCheckRequest):
    """Accepts OCR-extracted parking sign text; returns verdict + weekly grid."""
    if not req.sign_text.strip():
        raise HTTPException(status_code=422, detail="sign_text must not be empty")

    try:
        parsed = parse_ocr_text(req.sign_text)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse sign text: {exc}")

    ctx = _build_ctx(
        req.vehicle_type, req.has_disabled, req.has_permit,
        req.permit_zone, req.is_loading,
    )
    return _response(parsed, ctx)


@app.get("/")
async def index():
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
