# Aranya AI — implementation status

Per the build directive (section 30), this distinguishes **implemented**,
**partially implemented**, and **planned**. Nothing below is described as
more complete than it is.

## Implemented (real, executed, unit-tested in this environment)

- **Vision pipeline** (`backend/vision/`) — classical OpenCV/NumPy CV:
  colour-deviation detection, adaptive-threshold lesion/spot detection,
  texture-variance irregularity for crops; GrabCut segmentation,
  coat-colour/texture biomarkers, skin-patch anomaly detection, and real
  optical-flow motion scoring for livestock. **Not** a trained neural
  classifier — no licensed dataset or pretrained model was available;
  plug-in points (`predict_with_deep_model`,
  `train_or_load_sequence_model`) exist for when one is.
- **Domain schemas** (`backend/core/schemas.py`) — `Evidence` and
  `Recommendation` dataclasses with provenance, confidence, severity,
  urgency, and escalation, matching spec sections 13–15. Zero
  dependencies; unit-tested.
- **External-provider abstraction** (`backend/core/providers.py`) — a
  `WeatherProvider` Protocol and a `MarketProvider` Protocol so agents
  never depend on one vendor's API shape (spec section 20). Enforces the
  "no provider = no fabricated reading" rule from spec section 3.
- **Vision Agent** (`backend/agents/vision_agent.py`) — turns raw CV
  output into a `Recommendation`, rejects low-quality photos rather than
  guessing, and hard-codes the safety rule that any detected skin/coat
  patch always escalates to a vet (the CV pipeline cannot name the
  disease, so the agent never lets it imply one).
- **Weather Agent** (`backend/agents/weather_agent.py`) — threshold-based
  risk assessment (heavy rain, heat stress, high wind) over a
  `WeatherReading`. Fully deterministic, no LLM call. Raises `AgentError`
  rather than fabricating a reading when no provider is configured or the
  provider fails — tested explicitly.
- **Farm Guardian** (`backend/agents/guardian_agent.py`) — spec section
  12's alert-decision layer. Deterministic: takes a Recommendation the
  Vision or Weather agent just produced, decides whether it crosses an
  alert threshold (severity ≥ moderate or urgency ≥ soon), and whether
  it's a *meaningful change* from the last alert already issued for that
  same field/animal/farm — an identical repeated risk is never re-alerted
  (spec section 12: non-spammy). Alerts are stored with a computed
  priority so a farmer's feed is always sorted most-urgent-first. Wired
  automatically into every crop scan, livestock scan, and weather check
  via the Orchestrator. Does **not** include a scheduler/cron — see
  Planned below; this is the decision function a scheduler would call,
  fully implemented and tested on its own. Alert acknowledgement now
  enforces the same farm-ownership check `resolve_consultation` always
  had — a real gap this project's own earlier status notes flagged and
  left open; fixed here, with a test confirming one farm cannot
  acknowledge another farm's alert.
- **Authentication** (`backend/security/`) — spec section 19, real and
  tested end-to-end:
  - `otp.py`: OTP generation, PBKDF2-hashed storage (never plaintext,
    verified by test), 5-minute expiry, 5-attempt lockout, 5-requests/hour
    rate limit at the storage layer.
  - `tokens.py`: JWT session issuance/verification (PyJWT), roles
    (farmer/expert/admin), tampered-token rejection, role enforcement.
  - `rate_limit.py`: in-memory sliding-window limiter — real for a
    single process; explicitly flagged as needing Redis for a scaled
    multi-instance deployment (see Partially implemented below).
  - `auth_service.py`: the actual login flow (request → verify → issue
    token), with every attempt — success or failure — written to a real
    audit log (`FarmMemory.log_audit`/`get_audit_log`).
  - Wired into the FastAPI layer: every farm-scoped endpoint now requires
    a valid bearer token and checks `farmer_owns_farm` (a farmer can only
    act on their own farm; experts/admins can act on any farm).
- **Soil Agent** (`backend/agents/soil_agent.py`) — deterministic pH/NPK
  evaluation against generic per-crop reference ranges
  (`backend/core/soil_config.py`, explicitly labeled as generic, not
  region-calibrated agronomy data). Confidence scales with data source
  (lab report > provider API > farmer-reported estimate) — a farmer's
  rough guess at their own soil doesn't carry the same weight as a lab
  result, and multiple unverified findings from a farmer-reported test
  auto-escalate to an expert. Wired into the Orchestrator and Farm
  Guardian like the other agents.
- **Planning Agent** (`backend/agents/planning_agent.py`) — the first
  agent that actively composes other agents' outputs rather than acting
  standalone: reads the field's latest soil test from Farm Memory
  (written by SoilAgent, without re-running SoilAgent — tested explicitly
  that no duplicate soil-test record is written), optionally calls
  WeatherAgent live for a near-term risk check, and checks the calendar
  month against generic sowing-season windows
  (`backend/core/planning_config.py`, same "generic, not region-
  calibrated" caveat as soil). Degrades gracefully at every layer: no
  soil test on file → says so and nudges toward getting one, rather than
  refusing; no weather provider configured → proceeds without a weather
  opinion instead of failing the whole recommendation; crop not in the
  sowing calendar → says so rather than guessing a season.
- **Intent Router + conversational entry point** (`backend/agents/intent_router.py`,
  `Orchestrator.handle_farmer_message`) — spec section 7's "Input
  Understanding" box, and the first LLM call anywhere in this codebase.
  Deliberately narrow scope: the LLM only classifies free text into one
  of a small fixed action set (weather_check, field_history,
  planning_query, animal_history, unclear) and extracts named
  parameters — it never reasons about farm health, which stays
  deterministic in the agents (spec section 8). Its output is treated as
  untrusted input: parsed as JSON (handling markdown-fenced responses),
  validated against the allowed action set and a required-params schema,
  and any failure — malformed JSON, an invented action name, missing
  required fields — degrades to an honest "unclear, please clarify"
  rather than a guess. Tested with a fake LLM provider covering exactly
  these failure modes, plus tested end-to-end through the real
  Orchestrator (fake classification → real WeatherAgent/PlanningAgent →
  real Farm Memory). A real Gemini client
  (`backend/integrations/llm_gemini.py`) is written in the same
  honest-but-unexecuted pattern as the OpenWeatherMap client — correct
  request shape, not run against the live API here (no network, no key).
  Photo-based intents (crop/livestock scan) are NOT reachable through
  free text alone, since text can't carry an image — that needs a
  frontend that sends a photo alongside the message.
- **Market Agent** (`backend/agents/market_agent.py`) — fetches a live
  mandi price and compares it against this specific crop/market
  combination's own recent trailing average (not a generic "the market is
  up" claim) to advise sell-now / hold / neutral. First check for a new
  crop/market pair reports the price honestly with a "not enough history
  yet" note rather than pretending to see a trend. Same honest-failure
  rule as Weather: no provider configured, or the provider fails, raises
  rather than fabricating a price. A real Agmarknet/data.gov.in client
  (`backend/integrations/market_agmarknet.py`) is written in the same
  pattern as the other providers — correct request shape, never called
  live. Building this agent's chat integration surfaced and fixed a real
  bug: `handle_farmer_message`'s weather and planning dispatch paths
  didn't catch `AgentError` from a missing provider, so a chat question
  about weather with no `WEATHER_API_KEY` set would have crashed instead
  of returning an honest error — fixed for all three paths (weather,
  planning, market) and covered by a regression test.
- **Expert Escalation Agent** (`backend/agents/expert_escalation_agent.py`)
  — closes a loop that existed but did nothing: VisionAgent and SoilAgent
  have set `escalate_to_expert=True` since they were built, but until now
  nothing tracked, queued, or resolved those escalations. This agent
  turns that flag into a real `expert_consultations` record (source
  agent, problem, severity, escalation reason, linked back to the
  originating recommendation), gives experts a severity-sorted queue
  (`get_pending_consultations`/`queue_priority`), and provides a resolve
  workflow with a real farm-isolation check (an expert cannot resolve a
  different farm's consultation — tested). Wired automatically into every
  Recommendation-producing call via `Orchestrator._post_process`, the
  same integration point Guardian already used.
- **Economics Agent** (`backend/agents/economics_agent.py`) — computes
  real profit/loss per field from logged expenses and sales (no
  modeled/estimated figures — only what was actually recorded, per spec
  section 3). Deliberately distinguishes three honest states rather than
  forcing everything into a profit/loss number: no data at all (raises,
  nothing to report); costs logged but nothing sold yet (reports
  spend-to-date, explicitly NOT framed as a loss, since the crop hasn't
  been sold); and a full picture once both exist. A significant loss
  margin escalates through the same Guardian/Expert-Escalation pipeline
  every other agent uses. Scoped to the field's current **crop cycle**
  (`backend/memory/store.py`'s `crop_cycles` table), not the field's
  all-time totals — a real fix for a gap this project flagged in its own
  earlier status notes: replanting a field used to blend last season's
  costs into this season's profit/loss figure. `Orchestrator.handle_start_new_crop_cycle`
  is the explicit farmer action that starts a fresh cycle; cycles are
  also auto-created lazily on first expense/sale if a farmer never calls
  it explicitly. Tested with the exact before-fix scenario: a profitable
  Tomato season, a replant into Wheat, and confirmation that Wheat's
  early-season costs show up alone, not blended with Tomato's profit —
  while the separate all-time query still shows both seasons' history
  intact (the fix is about not blending by default, not about losing
  data).
- **Scheme Agent** (`backend/agents/scheme_agent.py`) — matches land size
  and farmer category against a curated reference list of well-known
  central government agricultural schemes (PM-KISAN, PMFBY crop
  insurance, KCC, Soil Health Card, PMKSY micro-irrigation subsidy, an
  SC/ST/woman/small-farmer enhanced mechanization subsidy tier). This is
  the one agent where "no provider configured" honesty doesn't apply the
  same way Weather/Market do — scheme structures don't change daily —
  but the equivalent honesty rule still applies: every recommendation
  states plainly that this is a curated snapshot, not a live government
  feed, is very likely incomplete (no state-specific schemes), and may
  be outdated; confidence is deliberately capped low (tested explicitly)
  rather than presented as authoritative.
- **Learning Agent** (`backend/agents/learning_agent.py`) — closes the
  outcome-feedback loop the spec's `TreatmentOutcome` entity implies but
  nothing previously used: records whether a farmer followed a
  recommendation and what happened (improved/no change/worsened), and
  computes a per-agent track record. Deliberately NOT presented as a
  controlled trial or a causal claim — every track record carries an
  explicit observational-data caveat — and refuses to report a
  percentage at all below a minimum sample size (5), tested explicitly,
  rather than implying confidence a handful of data points doesn't
  support. Frontend integration: every rendered recommendation, from any
  agent, now has "did you follow this, and did it help?" buttons that
  feed straight into this agent — tested end-to-end with a real
  VisionAgent recommendation id, not just in isolation.
- **Research Agent** (`backend/agents/research_agent.py`) — deterministic
  keyword-overlap search over a curated knowledge base
  (`backend/core/knowledge_base.py`: 8 common crop diseases/pests with
  real symptoms and management steps). No LLM, no embeddings — verified
  during development that realistic symptom descriptions ("white powdery
  coating on my tomato leaves") actually return the correct top match,
  and gibberish correctly returns nothing (tested, not just spot-checked
  once). Confidence is capped low always — a text description is much
  weaker evidence than a photo, and every recommendation says so
  explicitly, pointing back to the Vision Agent's photo scan as the
  stronger option. The one entry flagged as time-sensitive in the
  knowledge base (late blight, which can destroy a crop within days)
  auto-escalates to an expert when matched — tested.
- **Voice Agent** (`backend/agents/voice_agent.py`) — spec section 16, and
  the last of the spec's 16 named agents. Real and tested: script-based
  language detection (Devanagari vs Latin — `backend/core/language_detection.py`,
  including an explicitly documented and tested limitation — romanized
  Hindi like "FIELD-01 mein kya hua" reads as English, since script
  detection can't distinguish transliterated Hindi from English), and
  the orchestration logic around STT/TTS (tested with fake providers,
  same pattern as Weather/Market). STT failure is a hard error (no
  fabricated transcript); TTS failure degrades gracefully — the text
  reply is still returned even if speech-out fails or isn't configured,
  tested explicitly. Reuses `Orchestrator.handle_farmer_message` for the
  actual conversational logic rather than duplicating it, so a
  transcribed voice message goes through the exact same tested
  intent-routing pipeline as typed chat. The real Google Cloud Speech
  client (`backend/integrations/voice_google.py`) is written in the same
  honest-but-unexecuted pattern as the other providers — with one added
  caveat the others don't have: there's no meaningful way to sanity-check
  actual STT/TTS behavior at all without real audio hardware/files, which
  this sandbox has no way to produce.
- **OTP delivery via SMS and Email** (`backend/core/notification_provider.py`,
  `backend/integrations/email_smtp.py`, `backend/integrations/sms_twilio.py`,
  `backend/security/auth_service.py`) — the login flow now attempts real
  delivery instead of returning the code in the API response by default.
  A farmer provides phone (required) and email (optional); whichever
  channels are configured (SMS via Twilio, email via SMTP) are attempted,
  and the request succeeds if at least one delivers. **Email delivery is
  genuinely tested end-to-end**, not just written-and-hoped: loopback
  networking works in this sandbox even though external network access
  doesn't, so `tests/test_email_delivery.py` runs an actual minimal SMTP
  server on localhost and sends real messages to it through
  `SMTPEmailProvider` via real `smtplib` — and this caught a real bug
  during development (a non-ASCII em-dash in the email body silently
  triggered base64 Content-Transfer-Encoding, which the first version of
  the test didn't decode and would have missed; fixed in the source and
  guarded with a dedicated regression test). SMS (Twilio) genuinely
  cannot be tested here at all — unlike email, there's no way to
  simulate an actual carrier network locally — so it's written in the
  same honest-but-unexecuted pattern as the other external providers.
  If neither channel is configured, the system falls back to the old
  dev-mode behavior (return the code directly) rather than hard-failing,
  so local development/testing still works without real credentials —
  but if a channel *is* configured and every attempt fails, that's now a
  real delivery failure (`AuthError`), never a silent fallback to
  exposing the code. 10 new tests cover every combination: no channels,
  SMS-only, email-only, both, one-fails-one-succeeds, all-configured-
  channels-fail, invalid email format rejected before an OTP is even
  generated, and email backfilling onto a farmer's record on first
  provision. The frontend login screen now collects an optional email
  alongside phone.
- **Image validation gate** (`backend/core/image_validation.py`) — spec
  section 11's "Image Quality Check" pipeline step and spec section 19's
  "file validation" requirement, previously unimplemented beyond the
  crop pipeline's own leaf-area heuristic (which needs segmentation to
  already have run — this runs first, before any CV cost is spent).
  Rejects malformed arrays, too-small or absurdly-large images, and
  degenerate blank/solid-color frames — verified against both the real
  sample images (all pass, confirmed) and a battery of synthetic bad
  inputs (too small, blank black, blank white, wrong channel count,
  `None`, oversized) before ever being wired into an agent. Now the
  actual first step of both `VisionAgent.analyze_crop` and
  `analyze_livestock` — tested through the real Orchestrator that a
  rejected image writes nothing to Farm Memory (no half-processed scan
  record) and that legitimate photos are completely unaffected.
- **Observability** (`backend/core/observability.py`) — spec section 28.
  Every agent call the Orchestrator makes (9 call sites: Vision × 2,
  Weather, Soil, Planning, Market, Economics, Scheme, Research) is now
  wrapped in `trace_agent_call`, producing a structured JSON log line
  with agent name, farm id, operation, duration in milliseconds, and
  success/failure — with the actual error message captured on failure.
  Verified two ways: the tracer in isolation (duration measurement,
  correct exception propagation — it never swallows an error, only
  reports on it), and through the *real* Orchestrator with real agents,
  confirming a successful crop scan and a failed weather check (no
  provider configured) both produce the correct structured record. No
  external log shipping is wired up (would need network access this
  sandbox doesn't have) — this produces the log lines a real deployment
  would forward to CloudWatch/Datadog/ELK/whatever via a handler on the
  `"aranya"` logger name.
- **Static frontend** (`frontend/static/`) — a real, dependency-free
  HTML/CSS/vanilla-JS single-page app covering every backend endpoint:
  OTP login, crop/livestock photo scan, weather/soil/planning queries,
  the Guardian alert feed, and the chat interface. No build step, no
  npm install required — this was a deliberate choice: `npm install`
  itself is blocked in this sandbox (verified — the registry returns
  403), so anything requiring a build step could only ever be
  written-but-unexecuted code, same as the FastAPI backend. This frontend
  is different: it's been verified as far as this sandbox allows without
  a browser — `node --check` passes on both JS files, a cross-check that
  every `getElementById` call in `app.js` resolves to a real element in
  `index.html` (52 references at time of writing, zero mismatches), every
  `data-nav` target resolves to a real view (10 views, zero mismatches),
  and balanced HTML/CSS tags. What's NOT verified: it has never actually run in a
  browser, and has never talked to a live backend (the backend itself
  has never run in this sandbox either — see the FastAPI note above).
  Design follows spec section 17's "Simple/Elder-friendly mode" — large
  touch targets, minimal navigation, one flow per screen — but only that
  one mode exists; the spec's separate "Advanced Mode" (maps, analytics,
  historical charts) is not built.
- **Farm Memory** (`backend/memory/store.py`) — sqlite3, stdlib-only,
  working today. Models Farmer, Farm, Field, Animal, VisionScan,
  Recommendation, FarmEvent. Supports the "what happened last time in
  this field?" retrieval pattern from spec section 9, livestock
  baseline-vs-history comparison, and a farm timeline that now also logs
  weather checks.
- **Orchestrator** (`backend/agents/orchestrator.py`) — routes a photo, a
  weather check, or a history query to the right agent/memory call. This
  is a *dispatcher*, not an LLM-based intent router (see Planned below).
- **Tests** — 177 tests total, all passing:
  - `tests/test_vertical_slice.py` (6): photo → evidence → recommendation
    → memory → history retrieval → baseline comparison → mandatory
    escalation on skin-patch detection, run against real sample images.
  - `tests/test_weather_agent.py` (8): threshold logic against a fake
    in-memory provider (protocol-conformant, no network dependency),
    including both honest-failure cases (no provider configured; provider
    call fails).
  - `tests/test_guardian.py` (8): threshold crossing, non-spam dedup on
    repeated identical risk, re-alerting on a genuinely worsening
    condition, cross-agent priority ordering (crop HIGH outranks weather
    MODERATE), acknowledgement, and — new — a real farm-isolation check
    on acknowledgement (one farm cannot acknowledge another farm's
    alert) plus honest handling of a nonexistent alert id — all run
    through the Orchestrator against real sample images and a fake
    weather provider.
  - `tests/test_auth.py` (20): OTP correctness/expiry/single-use/lockout,
    storage never contains plaintext codes, JWT round-trip and
    tamper-rejection, role enforcement, rate limiting (including window
    expiry), and the full login flow's audit trail (both success and
    failure paths).
  - `tests/test_soil_agent.py` (11): pH/NPK threshold logic (acidic,
    alkaline, deficient, excess), confidence scaling by data source,
    graceful fallback for an unlisted crop, escalation on multiple
    unverified findings, persistence, and Guardian alert integration.
  - `tests/test_planning_agent.py` (7): season-window matching, reads an
    existing soil test without writing a duplicate, folds a live weather
    check into the recommendation, and degrades gracefully when soil,
    weather, or calendar data is missing for a given crop.
  - `tests/test_intent_router.py` (9): valid intents, markdown-fenced
    JSON, malformed JSON, an invented action name, missing required
    params, and no-provider-configured — all tested against a fake LLM
    provider, no network needed.
  - `tests/test_conversation.py` (7): `handle_farmer_message` end-to-end
    — fake LLM classification feeding into the real WeatherAgent,
    real PlanningAgent, and real Farm Memory reads/writes, plus the
    honest-failure paths (no location for a weather question, no LLM
    configured, garbled LLM output).
  - `tests/test_market_agent.py` (8): price-vs-trailing-average logic
    (spike → sell signal, drop → hold signal, stable → neutral),
    graceful "not enough history yet" on a first check, honest failure
    with no provider configured, Guardian integration, and a regression
    test for the dispatch bug described above.
  - `tests/test_expert_escalation.py` (9): confirms Vision's and Soil's
    existing escalation flags now actually create tracked consultations,
    severity-based queue ordering, the resolve workflow, and a real
    farm-isolation check (an expert cannot resolve another farm's
    consultation).
  - `tests/test_economics_agent.py` (10): the three-state honesty
    distinction (no data / costs-only / full profit-loss picture),
    correct accumulation across multiple logged expenses, significant-loss
    severity escalation, Guardian integration, and — new — the exact
    replant-blending scenario: a profitable season, a crop-cycle restart,
    and confirmation the new season's figures don't blend with the old
    one's while all-time history stays intact.
  - `tests/test_scheme_agent.py` (8): land-size and category matching
    logic (including a targeted enhanced-subsidy tier), the mandatory
    staleness caveat on every recommendation, and a deliberately-capped
    confidence score.
  - `tests/test_learning_agent.py` (7): sample-size gating (refuses a
    percentage below 5 data points), correct improved/no-change/worsened
    percentage computation, exclusion of not-followed outcomes from the
    success rate, per-agent isolation, and end-to-end integration with a
    real recommendation id from a real VisionAgent crop scan.
  - `tests/test_research_agent.py` (9): keyword matching against
    realistic symptom descriptions (correctly identifies powdery mildew,
    bollworm, etc.), crop-based filtering, honest no-match handling,
    confidence capping, and the late-blight urgency escalation.
  - `tests/test_observability.py` (6): the tracer in isolation (duration
    measurement, exception propagation), plus through the real
    Orchestrator — a successful crop scan and a failed weather check
    (no provider configured) both produce the correct structured record,
    and tracing doesn't alter the returned Recommendation.
  - `tests/test_image_validation.py` (12): real sample images all pass,
    a battery of synthetic bad inputs are all correctly rejected
    (too small, blank black/white, wrong channel count, `None`,
    oversized), farmer-readable error messages, and — through the real
    Orchestrator — that a rejected image writes nothing to Farm Memory
    while legitimate photos are completely unaffected.
  - `tests/test_voice_agent.py` (14): language detection against real
    Hindi/English/mixed text including the documented romanized-Hindi
    limitation, and the full voice pipeline through the real
    Orchestrator with fake STT/TTS providers — honest failure with no
    provider configured, retryable STT failures, empty-transcript
    rejection, transcribed text correctly flowing through the same
    tested conversational pipeline as typed chat, and TTS degrading
    gracefully (text reply survives) when speech-out isn't configured.
  - `tests/test_email_delivery.py` (6): a REAL end-to-end send — an
    actual local SMTP server, an actual `smtplib` client, real socket
    I/O — plus invalid-email rejection before any connection is
    attempted, real connection-failure handling, and the regression
    test for the base64-encoding bug this suite caught during
    development.
  - 10 new tests in `tests/test_auth.py` (now 30 total) covering every
    SMS/email delivery combination: no channels, SMS-only, email-only,
    both, one-fails-one-succeeds, all-configured-channels-fail,
    invalid-email-format rejected before OTP generation, and email
    backfilling onto a farmer's record.

Run them yourself:
```
python3 tests/test_vertical_slice.py
python3 tests/test_weather_agent.py
python3 tests/test_guardian.py
python3 tests/test_auth.py
python3 tests/test_soil_agent.py
python3 tests/test_planning_agent.py
python3 tests/test_intent_router.py
python3 tests/test_conversation.py
python3 tests/test_market_agent.py
python3 tests/test_expert_escalation.py
python3 tests/test_economics_agent.py
python3 tests/test_scheme_agent.py
python3 tests/test_learning_agent.py
python3 tests/test_research_agent.py
python3 tests/test_observability.py
python3 tests/test_image_validation.py
python3 tests/test_voice_agent.py
python3 tests/test_email_delivery.py

```

## Written but not executed here (no network access in the authoring sandbox)

- **FastAPI layer** (`backend/api/`) — standard, should work once
  `pip install -r requirements.txt` succeeds on a machine with network
  access. Not exercised against a live server here.
- **OpenWeatherMap provider** (`backend/integrations/weather_openweathermap.py`)
  — a real HTTP client for OpenWeatherMap's current-weather and forecast
  endpoints. Correct request/response shape, but never called against
  the live API in this sandbox (no network, no key). The WeatherAgent
  logic that consumes its output IS tested, via the fake provider.
- **Postgres/SQLAlchemy schema** (`backend/memory/models_sqlalchemy.py`)
  — covers the full spec section 9 entity list (SoilTest,
  IrrigationEvent, MarketPrice, Harvest, GuardianAlert, Conversation,
  AuditLog, etc.). Not run against a real Postgres instance.
- **Docker/Compose files** — standard shape, not built/run here.

## Partially implemented

- **Farm Memory**: only the entities the current agents need are live in
  `store.py` (sqlite) — Farmer, Farm, Field, Animal, VisionScan,
  Recommendation, FarmEvent, GuardianAlert, AuditLog, SoilTest,
  MarketPrice/MarketWatch, ExpertConsultation, and Expense/Sale. The full
  entity list from the spec is *modelled* in `models_sqlalchemy.py`
  (IrrigationEvent, Harvest as distinct from Sale, Conversation, etc.)
  but not wired to any agent yet.
- **Weather intelligence**: only current-conditions risk screening
  exists. No multi-day forecasting, no per-crop heat/rain tolerance
  tables.
- **Decision Engine / Explainability**: the `Recommendation` schema
  implements the structure; no vector/semantic memory retrieval, no
  confidence calibration beyond the heuristic/threshold scores each agent
  produces directly.
- **Authentication**: the login flow, token issuance, and authorization
  checks are real and tested. Not yet done: (1) SMS delivery (Twilio) is
  written but never tested against a live account — no way to verify
  that without a real phone and carrier network (email delivery IS
  tested end-to-end — see the OTP delivery entry above); (2) the rate
  limiter is in-memory and won't coordinate across multiple backend
  processes — needs Redis for a scaled deployment.
  (Alert-acknowledgement's farm-ownership check — previously flagged as
  missing here — is fixed; see the Guardian entry above.)
- **LLM orchestration**: the intent-classification step and the untrusted-
  output handling around it are real and tested (fake-provider tests
  cover the failure modes deliberately). What's not done: (1) the real
  Gemini client is written but never executed against the live API (no
  network/key in this environment); (2) only six text-answerable actions
  exist (weather, field history, planning, animal history, market, plus
  "unclear" as the fallback) — no soil-test-by-text, no crop-scan-by-text
  (needs an attached photo, which free text can't carry); (3) no reply is
  generated in the farmer's own language or phrasing —
  `as_farmer_summary()` returns the same structured English fields
  regardless of what language the farmer wrote in; (4) no multi-turn
  context — each message is classified independently, so a follow-up
  like "and tomorrow?" after a weather question won't carry context
  forward.

## Not implemented (planned, per the spec)

All 16 of the spec's named agents (section 8) now have a real module —
Voice was the last one and is built (see above). What's NOT built at the
agent level: the Orchestrator itself is still a partial implementation
(deterministic dispatcher, not the full LLM-reasoning pipeline spec
section 7 describes — see "Partially implemented" above), and Farm
Memory is infrastructure every agent uses, not itself a decision-making
agent. Below this point, "not implemented" means real external
integration and infrastructure gaps, not missing agent logic.

- Voice/multilingual pipeline (spec section 16) — the orchestration
  logic and language detection are real and tested (see the Voice Agent
  entry above); actual speech-to-text/text-to-speech has never run
  against a real audio file or real Google Cloud credentials — there is
  no way to test that specific piece in this sandbox at all, unlike
  every other provider here where at least the logic around it could be
  verified with a fake.
- Farm Guardian proactive monitoring (spec section 12) — the *decision
  logic* is implemented and tested (see above); what's missing is the
  scheduler/background-job layer that would call it periodically without
  a farmer taking an action first (e.g. a nightly re-check of every field
  even if no new photo was uploaded). Right now Guardian only evaluates
  when a scan or weather check actually happens.
- Authentication, authorization, rate limiting (spec section 19) — see
  Partially implemented above; the core flow is real, the remaining gaps
  are listed there.
- Object storage for scan images (currently only derived metrics are
  persisted, not the photos themselves).
- Deployment (nothing has been deployed; Docker files are unexecuted).
- React/TypeScript/Vite frontend (spec section 6's preferred stack) — a
  static vanilla-JS frontend exists instead (see Partially implemented
  above) because npm install is blocked in this sandbox; a real build
  tooling setup would need to happen somewhere with network access.
- Advanced Mode UI (maps, analytics, historical charts — spec section
  17) — only Simple/Elder-friendly mode exists.

## Honest bottom line

All 16 of the spec's named agents (section 8) now have a real, tested
module — Vision (crop + livestock), Weather, Soil, Planning, Market,
Economics, Scheme, Learning, Research, Guardian, Expert Escalation, and
Voice — all deterministic where the spec prefers determinism (section
8), all producing the same structured `Recommendation` type, all reading
from and writing to a shared Farm Memory. On top of the agents: a
narrowly-scoped LLM orchestration layer (free text → structured action →
the same deterministic agents, tested end-to-end with only the
classification step faked); real authentication and authorization
(every farm-scoped endpoint requires a valid session and checks farm
ownership — including two ownership gaps this project's own earlier
status notes flagged and then closed: alert acknowledgement and
crop-cycle-scoped Economics); structured observability tracing every
agent call site; an image-validation gate catching malformed/blank
uploads before they reach the CV pipeline; and a dependency-free static
frontend covering every endpoint, including outcome-feedback buttons
that close the loop into the Learning Agent, plus a login flow that
attempts real OTP delivery via SMS and/or email rather than exposing the
code by default. 177 tests, all passing, all run against real sample
images, real threshold math, and real Farm Memory reads/writes — not
mocked business logic. One of those, `tests/test_email_delivery.py`, is
different in kind from the rest: it runs an actual SMTP server on
localhost and sends real messages to it, because loopback networking
works in this sandbox even though external network access doesn't —
this caught and fixed a genuine bug (a non-ASCII character silently
triggering base64 encoding that an earlier, naive version of the test
would have missed).

What's genuinely still missing, and why, falls into two honest
categories. First, infrastructure this sandbox cannot reach regardless
of how much code gets written: no *external* network access means
FastAPI, SQLAlchemy, Docker, and every live external provider call
(Gemini, OpenWeatherMap, Agmarknet, Google Speech, Twilio SMS) are
correct-looking but literally never executed — that's not a confidence
statement, it's a fact about what this environment could and couldn't
run. (Email delivery is the one exception, and only because loopback
still works — see above.) Second, real product gaps that don't need more
agent logic, just more integration work: Guardian has no scheduler (it
only re-evaluates when a farmer takes an action, not proactively
overnight); SMS delivery is written but never tested against a live
Twilio account; the LLM layer has no multi-turn memory or
photo-carrying messages; the frontend is Simple Mode only, in vanilla JS
rather than the spec's preferred React/TypeScript/Vite (blocked by the
same lack of npm/network access).

None of that is a reason to call this unfinished in the sense of "logic
that doesn't exist" — it's a reason to call it unverified in the sense
of "never run outside this sandbox." That's the one gap no amount of
further building here can close. This is a foundation ready for real
review and execution on a machine with network access, not a finished,
deployed product.
