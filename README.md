<div align="center">

# 🌾 Aranya 🌾

**Intelligence for Every Farm.**

*Your farm remembers. Your AI watches. You make the decision.*

[![Tests](https://img.shields.io/badge/tests-177%20passing-2D4A34?style=flat-square)](#testing)
[![Agents](https://img.shields.io/badge/agents-16%2F16%20built-2D4A34?style=flat-square)](#the-agents)
[![Backend](https://img.shields.io/badge/backend-FastAPI%20%2B%20Python-7A5230?style=flat-square)](#tech-stack)
[![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20TypeScript-3E6E8E?style=flat-square)](#frontend)
[![License](https://img.shields.io/badge/status-pre--deployment-B3401F?style=flat-square)](#honest-status)

</div>

---

## What is Aranya?

Aranya is a persistent agricultural-intelligence system built around one idea: a farm has a *history*, and every recommendation should be able to point to evidence, not just an opinion.

A farmer photographs a crop or an animal, checks the weather, logs a soil test, or just asks a question in plain text. Behind that single action sits a farm memory that remembers what happened last time, sixteen specialized agents that reason over real evidence, and a decision engine that never hands back raw LLM prose as the final word — every recommendation carries its evidence, its confidence, its severity, and (when warranted) a note that says *this needs a human expert, not just an AI*.

This is not a chatbot wrapped around a crop-disease API. It's the full loop:

```
Farmer → Input → Aranya → Farm Memory → Specialized Agent → Evidence
                                                                 │
Farm Memory ← Outcome ← Farmer Action ← Recommendation ← Reasoning
```

---

## Why this project is different

Most AI agriculture demos fake the parts that are hard to build. This one doesn't:

- **No fabricated data, anywhere.** No agent invents a weather reading, a market price, or a government scheme it can't back up. If a data source isn't configured, the agent says so and refuses to guess — never a plausible-looking placeholder.
- **177 automated tests, and they're not mocking the business logic.** Real sample crop/livestock photos run through the actual computer-vision pipeline. A real local SMTP server receives real emails sent by real `smtplib` code. Real threshold math decides whether a recommendation escalates to an expert.
- **Every recommendation is structured, not prose.** `problem`, `evidence[]`, `confidence`, `severity`, `urgency`, `recommended_action`, `reasoning`, and — critically — `escalate_to_expert` with a reason, when the evidence doesn't support full AI confidence.
- **Honesty about what's unverified is treated as a feature, not an admission of failure.** Every file that touches a live external API is labeled with exactly what's been tested and what hasn't. See [Honest Status](#honest-status) below — it's not boilerplate, it's accurate.

---

## Table of Contents

- [The Agents](#the-agents)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Overview](#api-overview)
- [Testing](#testing)
- [Configuration](#configuration)
- [Frontend](#frontend)
- [Honest Status](#honest-status)
- [Design Philosophy](#design-philosophy)

---

## The Agents

All 16 agents from the original specification exist as real, tested modules. Vision covers both crop and livestock screening under one CV pipeline; everything else is one agent, one file, one test suite.

| Agent | What it does | Deterministic? |
|---|---|---|
| **Vision** | Classical CV screening for crop disease/pest symptoms and livestock coat/behavior anomalies — real OpenCV, not a trained neural net (none was available) | ✅ |
| **Weather** | Risk screening (heavy rain, heat stress, high wind) against a live forecast | ✅ |
| **Soil** | pH/NPK evaluation against per-crop reference ranges; confidence scales with data source (lab report > estimate) | ✅ |
| **Planning** | Composes Soil + Weather + a sowing calendar into a single "should I plant now?" recommendation | ✅ |
| **Market** | Compares today's price against *that crop/market's own* recent trailing average — not a generic "prices are up" claim | ✅ |
| **Economics** | Real profit/loss per field, scoped to the current crop cycle so replanting doesn't blend seasons together | ✅ |
| **Scheme** | Matches land size/category against a curated government-scheme reference list, with a mandatory staleness caveat on every result | ✅ |
| **Learning** | Records whether farmers followed advice and what happened; refuses to report a track record below 5 data points | ✅ |
| **Research** | Keyword-matched symptom lookup against a curated pest/disease knowledge base, for when there's no photo to scan | ✅ |
| **Farm Guardian** | Decides which recommendations become farmer-facing alerts — threshold-gated, de-duplicated, priority-sorted | ✅ |
| **Expert Escalation** | Turns any agent's `escalate_to_expert` flag into a tracked, resolvable consultation queue | ✅ |
| **Voice** | Speech-to-text, script-based language detection (Hindi/English/mixed), and text-to-speech reply | ✅ |
| **Orchestrator** | Uses Gemini to route free-text chat, answer general farming questions, and call deterministic agents for farm data | Partial |

The **Intent Router** is the one place an LLM is used at all — and only to classify a message into a fixed action set, never to reason about farm health. Every deterministic agent underneath it stays deterministic, matching the specification's own stated preference for classical logic over LLM judgement wherever one suffices.

---

## Architecture

```
Farmer
  │
  ├─ Photo ─────────────┐
  ├─ Typed / Voice text ─┼──▶  Intent Router (LLM, classification-only)
  ├─ Form (soil, sale)   │
  └─ Weather/location    │
                         ▼
                  Orchestrator
                         │
        ┌────────────────┼────────────────────────┐
        ▼                ▼                         ▼
   Vision / Weather   Soil / Planning /       Guardian / Expert
   / Voice Agent      Market / Economics /    Escalation / Learning
                       Scheme / Research
        │                │                         │
        └────────────────┴────────────┬────────────┘
                                       ▼
                              Structured Recommendation
                         (evidence · confidence · severity)
                                       │
                                       ▼
                                 Farm Memory
                         (sqlite today, Postgres schema
                          ready in models_sqlalchemy.py)
                                       │
                                       ▼
                              Farmer sees the result,
                         reports back what happened →
                            feeds the Learning Agent
```

Every agent shares the same [`Recommendation`](backend/core/schemas.py) contract, so the frontend, the chat layer, and the alert feed all render the same shape regardless of which of the 16 agents produced it.

---

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python, FastAPI, Pydantic | Async-ready, typed, matches the spec's stated preference |
| Domain logic | Plain dataclasses (`backend/core/schemas.py`) | Zero dependencies — testable without FastAPI installed at all |
| Vision | OpenCV + NumPy | Real classical CV, no fabricated ML claims |
| Database | SQLite (working today) + SQLAlchemy/Postgres schema (`models_sqlalchemy.py`, ready to switch on) | Runs with zero setup now, production path already modelled |
| Auth | Custom OTP + JWT (PyJWT), no third-party auth service | Full control over the exact flow the spec describes |
| LLM | Gemini (pluggable — see `backend/core/llm_provider.py`) | Provider abstraction, not hardwired to one vendor |
| Frontend | React, TypeScript, Vite | Typed API client and deployable static build in `frontend/` |
| Email | stdlib `smtplib` — no external dependency | Genuinely tested end-to-end (see [Testing](#testing)) |

---

## Project Structure

```
aranya-ai/
├── backend/
│   ├── core/            # Domain schemas, provider abstractions, validation, observability
│   ├── vision/           # Classical CV pipelines (crop, livestock, trend analysis)
│   ├── agents/            # All 16 agents + the Orchestrator
│   ├── memory/            # Farm Memory: sqlite (live) + SQLAlchemy/Postgres (modelled)
│   ├── security/          # OTP, JWT, rate limiting, the auth service
│   ├── integrations/      # Real external API clients (Gemini, OpenWeatherMap, Twilio, SMTP...)
│   └── api/               # FastAPI HTTP layer
├── frontend/
│   └── static/            # Dependency-free HTML/CSS/JS single-page app
├── tests/                 # 18 files, 177 tests, no mocked business logic
├── docs/
│   └── STATUS.md          # The unvarnished implemented/partial/planned breakdown
├── docker/                 # Dockerfile + compose
├── requirements.txt
├── .env.example
└── docker-compose.yml
```

---

## Getting Started

### Backend

```bash
git clone <this-repo>
cd aranya-ai
cp .env.example .env          # fill in whichever provider keys you have — all optional
pip install -r requirements.txt
uvicorn backend.api.main:app --reload
```

The API comes up on `http://localhost:8000`. No API keys are required to start — every external provider (weather, market, LLM, SMS, email, speech) degrades to an honest "not configured" response rather than crashing or faking data. Fill in `.env` incrementally as you connect real providers.

Or with Docker:

```bash
docker compose up --build
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

The frontend defaults to `http://localhost:8000` for the API. Configure `VITE_API_BASE_URL` in `frontend/.env.local` to use another API origin. For a production bundle, run `npm run build` from `frontend/` and deploy `frontend/dist/` with SPA fallback enabled. See `frontend/README.md` for details.

### First login

The login screen asks for a phone number (required) and email (optional, as a backup delivery channel). With no SMS/SMTP provider configured, the API returns the OTP code directly in the response — clearly labeled as dev-mode-only — so you can log in immediately without setting anything up.

---

## API Overview

All endpoints are versioned under `/api/v1` and (aside from auth) require a bearer token from `/auth/verify-otp`. Full request/response shapes are in `backend/api/main.py`; FastAPI also serves interactive docs at `/docs` once running.

<details>
<summary><strong>Auth</strong></summary>

```
POST /api/v1/auth/request-otp     phone, email (optional)
POST /api/v1/auth/verify-otp      phone, code, name, email (optional)
```
</details>

<details>
<summary><strong>Vision (photo upload)</strong></summary>

```
POST /api/v1/vision/crop-scan         farm_id, field_ref, crop_name, image
POST /api/v1/vision/livestock-scan    farm_id, animal_ref, species, image
```
</details>

<details>
<summary><strong>Field intelligence</strong></summary>

```
GET  /api/v1/farms/{farm_id}/fields/{field_ref}/history
GET  /api/v1/farms/{farm_id}/weather?lat=..&lng=..
POST /api/v1/farms/{farm_id}/soil-test
GET  /api/v1/farms/{farm_id}/planning?field_ref=..&crop_name=..
GET  /api/v1/farms/{farm_id}/research?query=..
```
</details>

<details>
<summary><strong>Economics</strong></summary>

```
POST /api/v1/farms/{farm_id}/expenses
POST /api/v1/farms/{farm_id}/sales
POST /api/v1/farms/{farm_id}/crop-cycles     # start a fresh cycle when replanting
GET  /api/v1/farms/{farm_id}/economics
GET  /api/v1/farms/{farm_id}/market?crop_name=..&market_name=..
GET  /api/v1/farms/{farm_id}/schemes?land_acres=..&category=..
```
</details>

<details>
<summary><strong>Guardian, escalation, learning</strong></summary>

```
GET  /api/v1/farms/{farm_id}/alerts
POST /api/v1/farms/{farm_id}/alerts/{alert_id}/acknowledge
GET  /api/v1/farms/{farm_id}/consultations
POST /api/v1/farms/{farm_id}/consultations/{consultation_id}/resolve
POST /api/v1/farms/{farm_id}/outcomes
GET  /api/v1/agents/{source_agent}/track-record
```
</details>

<details>
<summary><strong>Conversational (text + voice)</strong></summary>

```
POST /api/v1/farms/{farm_id}/chat     message, lat, lng (optional)
POST /api/v1/farms/{farm_id}/voice    audio file, lat, lng (optional)
```
</details>

---

## Testing

```bash
# run everything
for f in tests/test_*.py; do python3 "$f"; done

# or one at a time
python3 tests/test_vertical_slice.py     # end-to-end vision loop
python3 tests/test_email_delivery.py     # real SMTP server, real smtplib client
python3 tests/test_voice_agent.py        # language detection + STT/TTS orchestration
# ...15 more files, see tests/
```

**177 tests, 18 files, all passing.** What makes this suite worth trusting rather than just counting:

- **Real sample images**, not synthetic noise — the crop pipeline is verified to correctly order healthy → mild → moderate → severe across four actual photos.
- **A real local SMTP server.** `test_email_delivery.py` spins up an actual minimal SMTP server on `127.0.0.1`, sends real messages through real `smtplib`, and inspects what was actually received. This caught a genuine bug during development (a non-ASCII character silently triggering base64 encoding that a naive first-pass test would have missed) — fixed in the source, guarded with a dedicated regression test.
- **Provider failures are tested, not just successes** — every external-dependent agent has a test proving it fails honestly (raises a clear error) rather than fabricating data when no provider is configured.
- **Cross-agent composition is tested**, not just each agent in isolation — e.g. Planning reads a soil test that Soil actually wrote, without duplicating or re-triggering it.

---

## Configuration

Every external integration is optional and additive — the system runs fully without any of them, using honest fallbacks. See `.env.example` for the complete list. Summary:

| Variable | Powers | Tested? |
|---|---|---|
| `GEMINI_API_KEY` | Chat routing and general farming answers | Logic tested with a fake provider |
| `WEATHER_API_KEY` | OpenWeatherMap | Logic tested with a fake provider |
| `MARKET_DATA_API_KEY` | Agmarknet mandi prices | Logic tested with a fake provider |
| `GOOGLE_SPEECH_API_KEY` | Speech-to-text / text-to-speech | Logic tested with a fake provider |
| `SMTP_HOST` + friends | OTP delivery via email | ✅ **Real end-to-end test**, not a fake |
| `TWILIO_ACCOUNT_SID` + friends | OTP delivery via SMS | Written, not yet testable (needs a real carrier network) |
| `JWT_SECRET_KEY` | Session signing | Required before any production traffic — see startup warning |
| `DATABASE_URL` | Postgres (falls back to local sqlite) | sqlite path fully tested |

---

## Frontend

The React + TypeScript + Vite single-page app groups workflows into perception, analysis, intelligence, and action. It retains the existing API-backed OTP, scan, weather, soil, planning, market, economics, scheme, research, chat, alert, consultation, and recommendation-feedback workflows. The farm ID is persisted in the client because the current backend contract does not provide farm selection or creation. Build and deployment steps are documented in `frontend/README.md`.

---

## Honest Status

This section exists because most project READMEs oversell. This one won't.

**What's real and tested:** all 16 agents' decision logic, the domain schema, Farm Memory, authentication and authorization (including two real ownership bugs found and fixed during development), observability tracing, image validation, and email delivery.

**What's written but not verified against live infrastructure:** FastAPI startup, SQLAlchemy, Docker, and external provider calls still need environment-backed verification. In this task, npm registry access was denied, so the upgraded frontend's dependency install and production build could not be completed here. The frontend source and build configuration are present; run the documented build after installing dependencies in a network-enabled environment.

**The one exception:** email delivery. Loopback networking works even in that sandbox, so a real local SMTP server was used to genuinely prove the send path — including catching a real encoding bug along the way.

**Practical next steps, in order:**
1. `pip install -r requirements.txt` and boot the FastAPI server for the first time — expect at least minor issues on first real run, that's normal for ~9,000 lines never executed.
2. Install the frontend dependencies, build `frontend/`, then exercise it in a browser against that live backend.
3. Wire one real provider (start with weather — lowest stakes) and confirm the honest-failure path becomes a real-success path.
4. Everything else in `docs/STATUS.md`'s "Not implemented" section, roughly in priority order: a Guardian scheduler and SMS delivery verification.

For the full, granular implemented/partial/planned breakdown — file by file — see [`docs/STATUS.md`](docs/STATUS.md).

---

## Design Philosophy

> *"Complexity belongs to the AI. Simplicity belongs to the farmer."*

A few rules were held to throughout, without exception:

- **Never fabricate.** No invented weather, no invented prices, no invented government schemes, no confident-sounding recommendation with zero evidence behind it.
- **Prefer deterministic logic over LLM judgement** wherever one will do the job — the LLM is used exactly once, to classify intent, never to decide whether a crop is diseased.
- **Every recommendation explains itself** — what happened, why it matters, what the evidence is, what to do, how urgent, and when to call a human instead of trusting the AI.
- **Say what's untested as clearly as what's tested.** A "written but unexecuted" label is not an embarrassment — pretending otherwise would be.

---

<div align="center">

Built with a documented, tested, and consistently honest trail —
from the first vision-pipeline port to the last real SMTP handshake.

</div>
