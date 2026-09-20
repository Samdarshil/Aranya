"""
FastAPI entrypoint.

STATUS: written but not executed in the authoring sandbox — no network
access there to `pip install fastapi uvicorn`. The logic underneath
(backend/agents/orchestrator.py, backend/memory/store.py,
backend/vision/*, backend/security/*) IS executed and unit-tested (see
tests/). This file is the thin, standard FastAPI wiring on top of that
tested core. Run it with:

    pip install -r requirements.txt
    uvicorn backend.api.main:app --reload

Auth (spec section 19) is now wired: /api/v1/auth/request-otp and
/api/v1/auth/verify-otp issue sessions; every farm-scoped endpoint below
requires a valid bearer token and enforces that a farmer can only act on
their own farm (require_farm_access). See docs/STATUS.md for what's
still missing (SMS delivery provider, production JWT secret check at
startup).
"""

from __future__ import annotations

import io

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

from backend.agents.base import AgentError
from backend.agents.orchestrator import Orchestrator
from backend.api.deps import get_current_claims, require_farm_access
from backend.api.schemas_api import FieldHistoryOut, RecommendationOut
from backend.integrations.email_smtp import SMTPEmailProvider
from backend.integrations.llm_gemini import GeminiProvider
from backend.integrations.market_agmarknet import AgmarknetProvider
from backend.integrations.sms_twilio import TwilioSMSProvider
from backend.integrations.voice_google import GoogleSpeechProvider
from backend.integrations.weather_openweathermap import OpenWeatherMapProvider
from backend.memory.store import FarmMemory
from backend.security.auth_service import AuthError, AuthService
from backend.security.otp import OTPService
from backend.security.tokens import Role, SessionClaims, is_using_dev_secret
from backend.vision.preprocessing import pil_to_bgr

app = FastAPI(title="Aranya AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before production — see docs/STATUS.md
    allow_methods=["*"],
    allow_headers=["*"],
)

memory = FarmMemory()
# OpenWeatherMapProvider.from_env() returns None if WEATHER_API_KEY is
# unset — the orchestrator and WeatherAgent handle that honestly (an
# explicit "no provider configured" error, never a fabricated reading).
orchestrator = Orchestrator.default(
    memory=memory,
    weather_provider=OpenWeatherMapProvider.from_env(),
    market_provider=AgmarknetProvider.from_env(),
    llm_provider=GeminiProvider.from_env(),
    stt_provider=GoogleSpeechProvider.from_env(),
    tts_provider=GoogleSpeechProvider.from_env(),
)
auth_service = AuthService(
    memory=memory, otp_service=OTPService(),
    sms_provider=TwilioSMSProvider.from_env(),
    email_provider=SMTPEmailProvider.from_env(),
)


@app.on_event("startup")
def _warn_if_using_dev_jwt_secret() -> None:
    if is_using_dev_secret():
        import warnings
        warnings.warn(
            "JWT_SECRET_KEY is not set — using an insecure development "
            "default. Set it before serving real traffic.", stacklevel=1,
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# -- Auth -------------------------------------------------------------------

@app.post("/api/v1/auth/request-otp")
def request_otp(phone: str = Form(...), email: str | None = Form(None)) -> dict:
    """Attempts real delivery via SMS and/or email (whichever providers
    are configured — see backend/security/auth_service.py). If neither is
    configured, falls back to returning the code directly in
    "debug_code" so local development stays usable without real
    credentials — a real deployment with SMS/email configured never
    returns a code here at all."""
    try:
        result = auth_service.request_login_otp(phone, email)
    except AuthError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return result


@app.post("/api/v1/auth/verify-otp")
def verify_otp(
    phone: str = Form(...), code: str = Form(...), name: str = Form("New Farmer"),
    email: str | None = Form(None),
) -> dict[str, str]:
    try:
        token = auth_service.verify_login_otp(phone, code, name_if_new=name, email=email)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"access_token": token, "token_type": "bearer"}


# -- Vision -------------------------------------------------------------------

@app.post("/api/v1/vision/crop-scan", response_model=RecommendationOut)
async def crop_scan(
    farm_id: int = Form(...),
    field_ref: str = Form(...),
    crop_name: str = Form(...),
    is_demo: bool = Form(False),
    image: UploadFile = File(...),
    claims: SessionClaims = Depends(get_current_claims),
) -> RecommendationOut:
    require_farm_access(farm_id, claims, memory)
    contents = await image.read()
    pil_img = Image.open(io.BytesIO(contents))
    bgr = pil_to_bgr(pil_img)
    try:
        rec = orchestrator.handle_crop_scan(farm_id, bgr, field_ref, crop_name, is_demo)
    except AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecommendationOut.from_domain(rec)


@app.post("/api/v1/vision/livestock-scan", response_model=RecommendationOut)
async def livestock_scan(
    farm_id: int = Form(...),
    animal_ref: str = Form(...),
    species: str = Form(...),
    is_demo: bool = Form(False),
    image: UploadFile = File(...),
    claims: SessionClaims = Depends(get_current_claims),
) -> RecommendationOut:
    require_farm_access(farm_id, claims, memory)
    contents = await image.read()
    pil_img = Image.open(io.BytesIO(contents))
    bgr = pil_to_bgr(pil_img)
    try:
        rec = orchestrator.handle_livestock_scan(farm_id, bgr, animal_ref, species, is_demo=is_demo)
    except AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecommendationOut.from_domain(rec)


# -- History / Weather / Alerts -----------------------------------------------

@app.get("/api/v1/farms/{farm_id}/fields/{field_ref}/history", response_model=FieldHistoryOut)
def field_history(farm_id: int, field_ref: str, crop_name: str,
                   claims: SessionClaims = Depends(get_current_claims)) -> FieldHistoryOut:
    require_farm_access(farm_id, claims, memory)
    result = orchestrator.handle_field_history_query(farm_id, field_ref, crop_name)
    return FieldHistoryOut(**{k: v for k, v in result.items() if k != "history"})


@app.get("/api/v1/farms/{farm_id}/weather", response_model=RecommendationOut)
def weather_check(farm_id: int, lat: float, lng: float,
                   claims: SessionClaims = Depends(get_current_claims)) -> RecommendationOut:
    require_farm_access(farm_id, claims, memory)
    try:
        rec = orchestrator.handle_weather_check(farm_id, lat, lng)
    except AgentError as exc:
        # No provider configured, or the provider failed — honest 503,
        # never a silently fabricated forecast.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RecommendationOut.from_domain(rec)


@app.post("/api/v1/farms/{farm_id}/soil-test", response_model=RecommendationOut)
def soil_test(
    farm_id: int,
    field_ref: str = Form(...),
    crop_name: str = Form(...),
    ph: float | None = Form(None),
    nitrogen_ppm: float | None = Form(None),
    phosphorus_ppm: float | None = Form(None),
    potassium_ppm: float | None = Form(None),
    source: str = Form("farmer_reported"),
    claims: SessionClaims = Depends(get_current_claims),
) -> RecommendationOut:
    require_farm_access(farm_id, claims, memory)
    try:
        rec = orchestrator.handle_soil_test(
            farm_id, field_ref, crop_name, ph, nitrogen_ppm, phosphorus_ppm, potassium_ppm, source,
        )
    except AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecommendationOut.from_domain(rec)


@app.get("/api/v1/farms/{farm_id}/planning", response_model=RecommendationOut)
def planning_query(
    farm_id: int, field_ref: str, crop_name: str,
    lat: float | None = None, lng: float | None = None,
    claims: SessionClaims = Depends(get_current_claims),
) -> RecommendationOut:
    require_farm_access(farm_id, claims, memory)
    try:
        rec = orchestrator.handle_planning_query(farm_id, field_ref, crop_name, lat, lng)
    except AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecommendationOut.from_domain(rec)


@app.get("/api/v1/farms/{farm_id}/market", response_model=RecommendationOut)
def market_check(
    farm_id: int, crop_name: str, market_name: str,
    claims: SessionClaims = Depends(get_current_claims),
) -> RecommendationOut:
    require_farm_access(farm_id, claims, memory)
    try:
        rec = orchestrator.handle_market_check(farm_id, crop_name, market_name)
    except AgentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RecommendationOut.from_domain(rec)


@app.post("/api/v1/farms/{farm_id}/expenses")
def log_expense(
    farm_id: int, field_ref: str = Form(...), crop_name: str = Form(...),
    category: str = Form(...), amount: float = Form(...),
    claims: SessionClaims = Depends(get_current_claims),
) -> dict:
    require_farm_access(farm_id, claims, memory)
    expense_id = orchestrator.handle_log_expense(farm_id, field_ref, crop_name, category, amount)
    return {"id": expense_id, "status": "logged"}


@app.post("/api/v1/farms/{farm_id}/sales")
def log_sale(
    farm_id: int, field_ref: str = Form(...), crop_name: str = Form(...),
    quantity_kg: float = Form(...), price_per_kg: float = Form(...),
    claims: SessionClaims = Depends(get_current_claims),
) -> dict:
    require_farm_access(farm_id, claims, memory)
    sale_id = orchestrator.handle_log_sale(farm_id, field_ref, crop_name, quantity_kg, price_per_kg)
    return {"id": sale_id, "status": "logged"}


@app.post("/api/v1/farms/{farm_id}/crop-cycles")
def start_new_crop_cycle(
    farm_id: int, field_ref: str = Form(...), new_crop_name: str = Form(...),
    claims: SessionClaims = Depends(get_current_claims),
) -> dict:
    """Ends the field's current crop cycle (if any) and starts a fresh
    one — call this when a farmer replants, so Economics doesn't blend
    last season's costs into this season's profit/loss."""
    require_farm_access(farm_id, claims, memory)
    cycle_id = orchestrator.handle_start_new_crop_cycle(farm_id, field_ref, new_crop_name)
    return {"id": cycle_id, "status": "started"}


@app.get("/api/v1/farms/{farm_id}/economics", response_model=RecommendationOut)
def field_economics(
    farm_id: int, field_ref: str, crop_name: str,
    claims: SessionClaims = Depends(get_current_claims),
) -> RecommendationOut:
    require_farm_access(farm_id, claims, memory)
    try:
        rec = orchestrator.handle_field_economics(farm_id, field_ref, crop_name)
    except AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecommendationOut.from_domain(rec)


@app.get("/api/v1/farms/{farm_id}/schemes", response_model=RecommendationOut)
def scheme_match(
    farm_id: int, land_acres: float | None = None, category: str | None = None,
    crop_name: str | None = None,
    claims: SessionClaims = Depends(get_current_claims),
) -> RecommendationOut:
    require_farm_access(farm_id, claims, memory)
    try:
        rec = orchestrator.handle_scheme_match(farm_id, land_acres, category, crop_name)
    except AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecommendationOut.from_domain(rec)


@app.get("/api/v1/farms/{farm_id}/research", response_model=RecommendationOut)
def research_query(
    farm_id: int, query: str, crop_name: str | None = None,
    claims: SessionClaims = Depends(get_current_claims),
) -> RecommendationOut:
    require_farm_access(farm_id, claims, memory)
    try:
        rec = orchestrator.handle_research_query(farm_id, query, crop_name)
    except AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecommendationOut.from_domain(rec)


@app.post("/api/v1/farms/{farm_id}/outcomes")
def record_outcome(
    farm_id: int, source_agent: str = Form(...), followed_advice: bool = Form(...),
    outcome: str = Form(...), recommendation_id: int | None = Form(None),
    notes: str | None = Form(None),
    claims: SessionClaims = Depends(get_current_claims),
) -> dict:
    require_farm_access(farm_id, claims, memory)
    try:
        outcome_id = orchestrator.handle_record_outcome(
            farm_id, recommendation_id, source_agent, followed_advice, outcome, notes,
        )
    except AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": outcome_id, "status": "recorded"}


@app.get("/api/v1/agents/{source_agent}/track-record")
def agent_track_record(
    source_agent: str, farm_id: int,
    claims: SessionClaims = Depends(get_current_claims),
) -> dict:
    # farm_id is only used to satisfy require_farm_access's signature —
    # track records are cross-farm aggregates, not farm-scoped data, but
    # every endpoint still requires an authenticated session.
    require_farm_access(farm_id, claims, memory)
    return orchestrator.handle_agent_track_record(farm_id, source_agent)


@app.get("/api/v1/farms/{farm_id}/alerts")
def active_alerts(farm_id: int, claims: SessionClaims = Depends(get_current_claims)) -> list[dict]:
    """Farm Guardian's alert feed — most urgent first (spec section 12)."""
    require_farm_access(farm_id, claims, memory)
    return orchestrator.get_active_alerts(farm_id)


@app.post("/api/v1/farms/{farm_id}/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    farm_id: int, alert_id: int, claims: SessionClaims = Depends(get_current_claims),
) -> dict[str, str]:
    require_farm_access(farm_id, claims, memory)
    try:
        orchestrator.acknowledge_alert(farm_id, alert_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "acknowledged"}


@app.get("/api/v1/farms/{farm_id}/consultations")
def pending_consultations(farm_id: int, claims: SessionClaims = Depends(get_current_claims)) -> list[dict]:
    """Expert-facing queue for one farm, most severe first."""
    require_farm_access(farm_id, claims, memory)
    return orchestrator.get_pending_consultations(farm_id)


@app.post("/api/v1/farms/{farm_id}/consultations/{consultation_id}/resolve")
def resolve_consultation(
    farm_id: int, consultation_id: int,
    expert_name: str = Form(...), notes: str = Form(...),
    claims: SessionClaims = Depends(get_current_claims),
) -> dict:
    """Only experts/admins may resolve a consultation — a farmer resolving
    their own escalation would defeat the point of asking an expert."""
    from backend.security.tokens import require_role as _require_role
    try:
        _require_role(claims, Role.EXPERT, Role.ADMIN)
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    require_farm_access(farm_id, claims, memory)
    try:
        return orchestrator.resolve_consultation(farm_id, consultation_id, expert_name, notes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/farms/{farm_id}/chat")
def chat(
    farm_id: int, message: str = Form(...),
    lat: float | None = Form(None), lng: float | None = Form(None),
    claims: SessionClaims = Depends(get_current_claims),
) -> dict:
    """Spec section 7's free-text entry point ("Aranya, meri fasal
    dekho"). Requires GEMINI_API_KEY to be set — without it, returns an
    honest {"type": "error", ...} payload rather than 500ing or guessing."""
    require_farm_access(farm_id, claims, memory)
    return orchestrator.handle_farmer_message(farm_id, message, lat, lng)


@app.post("/api/v1/farms/{farm_id}/voice")
async def voice_message(
    farm_id: int, audio: UploadFile = File(...),
    lat: float | None = Form(None), lng: float | None = Form(None),
    language_hint: str | None = Form(None),
    claims: SessionClaims = Depends(get_current_claims),
) -> dict:
    """Spec section 16's voice entry point. Requires GOOGLE_SPEECH_API_KEY
    for transcription — without it, returns an honest 503 rather than
    fabricating a transcript. The result's audio reply (if any) is
    returned as base64 under "audio_reply_base64" rather than raw bytes,
    since this is a JSON endpoint; a real client would decode and play it."""
    require_farm_access(farm_id, claims, memory)
    audio_bytes = await audio.read()
    try:
        result = orchestrator.handle_voice_message(farm_id, audio_bytes, lat, lng, language_hint)
    except AgentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raw_audio = result.pop("_audio_reply_bytes", None)
    if raw_audio is not None:
        import base64
        result["audio_reply_base64"] = base64.b64encode(raw_audio).decode("ascii")
    return result
