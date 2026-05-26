from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .models import VehicleContext, VehicleType
from .providers import Provider, parse_ocr_text, parse_sign_image
from .rule_engine import generate_weekly_grid, get_current_verdict

app = FastAPI(
    title="Can I Park Here?",
    description="AI-powered parking sign reader — photo or OCR text → Park / Do Not Park",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

_STATIC = Path(__file__).parent / "static"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ctx(
    vehicle_type: str,
    has_disabled: bool,
    has_permit:   bool,
    permit_zone:  str,
    is_loading:   bool,
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


def _build_response(parsed: dict, ctx: VehicleContext) -> dict:
    rules = parsed.get("rules", [])
    return {
        "sign_text":      parsed.get("sign_text", ""),
        "interpretation": parsed.get("interpretation", ""),
        "rules":          rules,
        "grid":           generate_weekly_grid(rules, ctx=ctx),
        "verdict":        get_current_verdict(rules, ctx=ctx),
    }


def _provider(name: str) -> Provider:
    try:
        return Provider(name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{name}'. Use: anthropic, openai, google")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/api/check", summary="Check parking sign from photo")
async def check_image(
    image:        UploadFile = File(..., description="Parking sign photo (JPEG/PNG/WEBP)"),
    provider:     str  = Form(..., description="AI provider: anthropic | openai | google"),
    api_key:      str  = Form(..., description="Your API key for the chosen provider"),
    vehicle_type: str  = Form(default="regular"),
    has_disabled: bool = Form(default=False),
    has_permit:   bool = Form(default=False),
    permit_zone:  str  = Form(default=""),
    is_loading:   bool = Form(default=False),
):
    contents   = await image.read()
    media_type = image.content_type or "image/jpeg"

    try:
        parsed = parse_sign_image(contents, media_type, _provider(provider), api_key)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _build_response(parsed, _ctx(vehicle_type, has_disabled, has_permit, permit_zone, is_loading))


class TextRequest(BaseModel):
    sign_text:    str
    provider:     str
    api_key:      str
    vehicle_type: str  = "regular"
    has_disabled: bool = False
    has_permit:   bool = False
    permit_zone:  str  = ""
    is_loading:   bool = False

    model_config = {"json_schema_extra": {"examples": [{
        "sign_text":    "NO PARKING\n8AM-6PM\nMON THRU FRI",
        "provider":     "anthropic",
        "api_key":      "sk-ant-...",
        "vehicle_type": "regular",
    }]}}


@app.post("/api/check-text", summary="Check parking sign from OCR text")
async def check_text(req: TextRequest):
    if not req.sign_text.strip():
        raise HTTPException(status_code=422, detail="sign_text must not be empty")

    try:
        parsed = parse_ocr_text(req.sign_text, _provider(req.provider), req.api_key)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _build_response(
        parsed,
        _ctx(req.vehicle_type, req.has_disabled, req.has_permit, req.permit_zone, req.is_loading),
    )


@app.get("/")
async def index():
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
