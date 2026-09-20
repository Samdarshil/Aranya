"""
Orchestrator — spec section 7.

Full target pipeline per the spec:
    User -> Input Understanding -> Orchestrator -> Farm Memory Retrieval
          -> Specialized Agents -> Evidence -> Reasoning -> Decision Engine
          -> Recommendation -> Farmer -> Outcome -> Farm Memory

Two entry points now exist:
  - The structured handle_* methods (handle_crop_scan, handle_weather_check,
    etc.) — used directly by the API for photo uploads and structured
    forms, where there's no ambiguity to resolve.
  - handle_farmer_message() — spec section 7's "Input Understanding" box.
    Takes free text, uses IntentRouter (an LLM call) to classify it into
    one of the structured actions above, then dispatches to the same
    handle_* method. The LLM's job is narrowly scoped to classification —
    it never reasons about farm health itself; that stays deterministic
    in the agents below it (spec section 8). See
    backend/agents/intent_router.py for how untrusted LLM output is
    validated rather than trusted blindly.

Photo-based actions (crop/livestock scan) are NOT reachable through
handle_farmer_message — free text alone can't supply an image. A real
client would let the farmer attach a photo alongside text; wiring that
through is a small addition once a frontend exists to send it (see
docs/STATUS.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.agents.base import AgentContext, AgentError
from backend.agents.economics_agent import EconomicsAgent
from backend.agents.expert_escalation_agent import ExpertEscalationAgent
from backend.agents.guardian_agent import GuardianAgent
from backend.agents.intent_router import IntentRouter
from backend.agents.learning_agent import LearningAgent
from backend.agents.market_agent import MarketAgent
from backend.agents.planning_agent import PlanningAgent
from backend.agents.research_agent import ResearchAgent
from backend.agents.scheme_agent import SchemeAgent
from backend.agents.soil_agent import SoilAgent
from backend.agents.vision_agent import VisionAgent
from backend.agents.voice_agent import VoiceAgent
from backend.agents.weather_agent import WeatherAgent
from backend.core.llm_provider import LLMProvider, LLMUnavailable
from backend.core.observability import trace_agent_call
from backend.core.providers import MarketProvider, WeatherProvider
from backend.core.schemas import GuardianAlert, Recommendation
from backend.core.voice_provider import SpeechToTextProvider, TextToSpeechProvider
from backend.memory.store import FarmMemory


@dataclass
class Orchestrator:
    memory: FarmMemory
    vision_agent: VisionAgent
    weather_agent: WeatherAgent
    soil_agent: SoilAgent = field(default_factory=SoilAgent)
    planning_agent: PlanningAgent = field(default_factory=PlanningAgent)
    market_agent: MarketAgent = field(default_factory=lambda: MarketAgent(provider=None))
    guardian_agent: GuardianAgent = field(default_factory=GuardianAgent)
    expert_escalation_agent: ExpertEscalationAgent = field(default_factory=ExpertEscalationAgent)
    economics_agent: EconomicsAgent = field(default_factory=EconomicsAgent)
    scheme_agent: SchemeAgent = field(default_factory=SchemeAgent)
    learning_agent: LearningAgent = field(default_factory=LearningAgent)
    research_agent: ResearchAgent = field(default_factory=ResearchAgent)
    voice_agent: VoiceAgent = field(default_factory=VoiceAgent)
    intent_router: IntentRouter = field(default_factory=lambda: IntentRouter(llm=None))

    @classmethod
    def default(cls, memory: FarmMemory | None = None,
                weather_provider: WeatherProvider | None = None,
                market_provider: MarketProvider | None = None,
                llm_provider: LLMProvider | None = None,
                stt_provider: SpeechToTextProvider | None = None,
                tts_provider: TextToSpeechProvider | None = None) -> "Orchestrator":
        return cls(
            memory=memory or FarmMemory(),
            vision_agent=VisionAgent(),
            weather_agent=WeatherAgent(provider=weather_provider),
            planning_agent=PlanningAgent(weather_provider=weather_provider),
            market_agent=MarketAgent(provider=market_provider),
            intent_router=IntentRouter(llm=llm_provider),
            voice_agent=VoiceAgent(stt_provider=stt_provider, tts_provider=tts_provider),
        )

    def _latest_recommendation_id(self, farm_id: int) -> int | None:
        recs = self.memory.get_farm_recommendations(farm_id)
        return recs[0]["id"] if recs else None

    def _post_process(self, context: AgentContext, rec: Recommendation,
                       subject_type: str, subject_id: int, subject_ref: str,
                       alert_type: str) -> GuardianAlert | None:
        """Runs every Recommendation-producing call through the same two
        downstream steps: Farm Guardian's alert decision (spec section
        12), and — new — Expert Escalation's consultation-request creation
        if the recommendation was flagged for escalation (spec section 8's
        Expert Escalation Agent). Both read the same just-saved
        recommendation id, so they're combined here rather than requiring
        every handle_* method to remember to call both."""
        rec_id = self._latest_recommendation_id(context.farm_id)
        self.expert_escalation_agent.escalate_if_needed(context, rec, rec_id)
        return self.guardian_agent.consider(
            context, rec, rec_id, subject_type, subject_id, subject_ref, alert_type,
        )

    def handle_crop_scan(self, farm_id: int, bgr: np.ndarray, field_ref: str,
                          crop_name: str, is_demo: bool = False) -> Recommendation:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        with trace_agent_call(farm_id, "vision_agent", "analyze_crop"):
            rec = self.vision_agent.analyze_crop(context, bgr, field_ref, crop_name, is_demo)
        field_id = self.memory.get_or_create_field(farm_id, field_ref, crop_name)
        self._post_process(context, rec, "field", field_id, field_ref, "crop_health")
        return rec

    def handle_livestock_scan(self, farm_id: int, bgr: np.ndarray, animal_ref: str,
                               species: str, frames_for_motion: list[np.ndarray] | None = None,
                               is_demo: bool = False) -> Recommendation:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        with trace_agent_call(farm_id, "vision_agent", "analyze_livestock"):
            rec = self.vision_agent.analyze_livestock(
                context, bgr, animal_ref, species, frames_for_motion, is_demo
            )
        animal_id = self.memory.get_or_create_animal(farm_id, animal_ref, species)
        self._post_process(context, rec, "animal", animal_id, animal_ref, "livestock_health")
        return rec

    def handle_weather_check(self, farm_id: int, lat: float, lng: float) -> Recommendation:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        with trace_agent_call(farm_id, "weather_agent", "assess_conditions"):
            rec = self.weather_agent.assess_conditions(context, lat, lng)
        self._post_process(context, rec, "farm", farm_id, f"farm-{farm_id}", "weather")
        return rec

    def handle_soil_test(self, farm_id: int, field_ref: str, crop_name: str,
                          ph: float | None = None, nitrogen_ppm: float | None = None,
                          phosphorus_ppm: float | None = None, potassium_ppm: float | None = None,
                          source: str = "farmer_reported") -> Recommendation:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        with trace_agent_call(farm_id, "soil_agent", "evaluate_soil_test"):
            rec = self.soil_agent.evaluate_soil_test(
                context, field_ref, crop_name, ph, nitrogen_ppm, phosphorus_ppm, potassium_ppm, source,
            )
        field_id = self.memory.get_or_create_field(farm_id, field_ref, crop_name)
        self._post_process(context, rec, "field", field_id, field_ref, "soil_health")
        return rec

    def handle_planning_query(self, farm_id: int, field_ref: str, crop_name: str,
                               lat: float | None = None, lng: float | None = None,
                               current_month: int | None = None) -> Recommendation:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        with trace_agent_call(farm_id, "planning_agent", "recommend_sowing_window"):
            rec = self.planning_agent.recommend_sowing_window(
                context, field_ref, crop_name, lat, lng, current_month,
            )
        field_id = self.memory.get_or_create_field(farm_id, field_ref, crop_name)
        # Planning doesn't currently set escalate_to_expert and isn't
        # alert-worthy the way a health/price finding is (it's an
        # advisory, not a detected problem), so Guardian is deliberately
        # skipped here — but escalation is still checked for consistency
        # in case that changes.
        rec_id = self._latest_recommendation_id(farm_id)
        self.expert_escalation_agent.escalate_if_needed(context, rec, rec_id)
        return rec

    def handle_market_check(self, farm_id: int, crop_name: str, market_name: str) -> Recommendation:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        with trace_agent_call(farm_id, "market_agent", "check_price"):
            rec = self.market_agent.check_price(context, crop_name, market_name)
        watch_id = self.memory.get_or_create_market_watch(farm_id, crop_name, market_name)
        self._post_process(context, rec, "market", watch_id, f"{crop_name} @ {market_name}", "market_price")
        return rec

    def handle_log_expense(self, farm_id: int, field_ref: str, crop_name: str,
                            category: str, amount: float) -> int:
        field_id = self.memory.get_or_create_field(farm_id, field_ref, crop_name)
        expense_id = self.memory.log_expense(field_id, category, amount)
        self.memory.log_event(farm_id, "expense_logged", f"{field_ref}: {category} \u20b9{amount:.0f}")
        return expense_id

    def handle_log_sale(self, farm_id: int, field_ref: str, crop_name: str,
                         quantity_kg: float, price_per_kg: float) -> int:
        field_id = self.memory.get_or_create_field(farm_id, field_ref, crop_name)
        sale_id = self.memory.log_sale(field_id, quantity_kg, price_per_kg)
        self.memory.log_event(
            farm_id, "sale_logged",
            f"{field_ref}: sold {quantity_kg:.0f}kg @ \u20b9{price_per_kg:.0f}/kg",
        )
        return sale_id

    def handle_start_new_crop_cycle(self, farm_id: int, field_ref: str, new_crop_name: str) -> int:
        """The explicit action a farmer takes when replanting a field —
        ends the current crop cycle (if any) and starts a fresh one, so
        Economics doesn't blend last season's costs into this season's
        profit/loss figure."""
        field_id = self.memory.get_or_create_field(farm_id, field_ref, new_crop_name)
        cycle_id = self.memory.start_new_crop_cycle(field_id, new_crop_name)
        self.memory.log_event(farm_id, "crop_cycle_started", f"{field_ref}: now growing {new_crop_name}")
        return cycle_id

    def handle_field_economics(self, farm_id: int, field_ref: str, crop_name: str) -> Recommendation:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        with trace_agent_call(farm_id, "economics_agent", "compute_profitability"):
            rec = self.economics_agent.compute_profitability(context, field_ref, crop_name)
        field_id = self.memory.get_or_create_field(farm_id, field_ref, crop_name)
        self._post_process(context, rec, "field", field_id, field_ref, "economics")
        return rec

    def handle_scheme_match(self, farm_id: int, land_acres: float | None = None,
                             category: str | None = None, crop_name: str | None = None) -> Recommendation:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        with trace_agent_call(farm_id, "scheme_agent", "match_schemes"):
            return self.scheme_agent.match_schemes(context, land_acres, category, crop_name)

    def handle_record_outcome(self, farm_id: int, recommendation_id: int | None, source_agent: str,
                               followed_advice: bool, outcome: str, notes: str | None = None) -> int:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        return self.learning_agent.record_outcome(
            context, recommendation_id, source_agent, followed_advice, outcome, notes,
        )

    def handle_agent_track_record(self, farm_id: int, source_agent: str) -> dict[str, Any]:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        return self.learning_agent.get_track_record(context, source_agent)

    def handle_research_query(self, farm_id: int, query: str,
                               crop_name: str | None = None) -> Recommendation:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        with trace_agent_call(farm_id, "research_agent", "answer_question"):
            rec = self.research_agent.answer_question(context, query, crop_name)
        self._post_process(context, rec, "farm", farm_id, f"farm-{farm_id}", "research")
        return rec


    def get_active_alerts(self, farm_id: int) -> list[dict[str, Any]]:
        """Farmer-facing alert feed, most urgent first (spec section 12)."""
        return self.memory.get_active_alerts(farm_id)

    def acknowledge_alert(self, farm_id: int, alert_id: int) -> None:
        """Raises ValueError if the alert doesn't exist or belongs to a
        different farm — the same ownership check
        resolve_consultation already enforces, now applied here too."""
        alert = self.memory.get_alert(alert_id)
        if alert is None:
            raise ValueError(f"No alert with id {alert_id}")
        if alert["farm_id"] != farm_id:
            raise ValueError(f"Alert {alert_id} belongs to a different farm.")
        self.memory.acknowledge_alert(alert_id)

    def get_pending_consultations(self, farm_id: int) -> list[dict[str, Any]]:
        """Expert-facing queue, most severe first (mirrors Guardian's own
        prioritization philosophy from spec section 12)."""
        return self.expert_escalation_agent.queue_priority(
            self.memory.get_pending_consultations(farm_id)
        )

    def resolve_consultation(self, farm_id: int, consultation_id: int,
                              expert_name: str, notes: str) -> dict[str, Any]:
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        return self.expert_escalation_agent.resolve(context, consultation_id, expert_name, notes)

    def handle_field_history_query(self, farm_id: int, field_ref: str, crop_name: str) -> dict[str, Any]:
        """Answers "Aranya, pichli baar is field mein kya hua tha?" (spec
        section 9's worked example) via a direct Farm Memory lookup — no
        LLM call needed for a query this structured."""
        field_id = self.memory.get_or_create_field(farm_id, field_ref, crop_name)
        history = self.memory.get_field_history(field_id)
        if not history:
            return {"field_ref": field_ref, "scan_count": 0, "message": "No scans recorded yet for this field."}
        latest = history[-1]
        return {
            "field_ref": field_ref,
            "scan_count": len(history),
            "latest_status": latest["status"],
            "latest_affected_area_pct": latest["score"],
            "latest_timestamp": latest["timestamp"],
            "history": history,
        }

    def handle_animal_history_query(self, farm_id: int, animal_ref: str, species: str) -> dict[str, Any]:
        animal_id = self.memory.get_or_create_animal(farm_id, animal_ref, species)
        history = self.memory.get_animal_history(animal_id)
        if not history:
            return {"animal_ref": animal_ref, "scan_count": 0, "message": "No observations recorded yet for this animal."}
        latest = history[-1]
        return {
            "animal_ref": animal_ref,
            "scan_count": len(history),
            "latest_risk_level": latest["status"],
            "latest_risk_score": latest["score"],
            "latest_timestamp": latest["timestamp"],
            "history": history,
        }

    def handle_farmer_message(self, farm_id: int, message: str,
                               lat: float | None = None, lng: float | None = None) -> dict[str, Any]:
        """Spec section 7's free-text entry point. Classifies `message`
        via IntentRouter, then dispatches to the same structured handlers
        used by the API's photo/form endpoints. Returns a dict rather
        than a bare Recommendation because some intents (history queries,
        clarification requests) aren't Recommendations at all — keeping
        one return shape here would force-fit them.
        """
        try:
            intent = self.intent_router.parse_message(message)
        except LLMUnavailable as exc:
            return {"type": "error", "message": str(exc)}

        if intent.action == "unclear":
            return {"type": "clarification", "message": intent.clarification_needed}

        if intent.action == "weather_check":
            if lat is None or lng is None:
                return {"type": "clarification",
                        "message": "I need your farm's location to check the weather — "
                                   "please enable location or share it."}
            try:
                rec = self.handle_weather_check(farm_id, lat, lng)
            except AgentError as exc:
                return {"type": "error", "message": str(exc)}
            return {"type": "recommendation", "intent": intent.action, **rec.as_farmer_summary()}

        if intent.action == "field_history":
            result = self.handle_field_history_query(
                farm_id, intent.params["field_ref"], intent.params["crop_name"],
            )
            return {"type": "history", "intent": intent.action, **result}

        if intent.action == "animal_history":
            result = self.handle_animal_history_query(
                farm_id, intent.params["animal_ref"], intent.params["species"],
            )
            return {"type": "history", "intent": intent.action, **result}

        if intent.action == "planning_query":
            try:
                rec = self.handle_planning_query(
                    farm_id, intent.params["field_ref"], intent.params["crop_name"], lat, lng,
                )
            except AgentError as exc:
                return {"type": "error", "message": str(exc)}
            return {"type": "recommendation", "intent": intent.action, **rec.as_farmer_summary()}

        if intent.action == "market_check":
            try:
                rec = self.handle_market_check(
                    farm_id, intent.params["crop_name"], intent.params["market_name"],
                )
            except AgentError as exc:
                return {"type": "error", "message": str(exc)}
            return {"type": "recommendation", "intent": intent.action, **rec.as_farmer_summary()}

        if intent.action == "scheme_match":
            try:
                land_acres = float(intent.params["land_acres"])
            except (KeyError, ValueError):
                return {"type": "clarification", "message": "What's your approximate land size in acres?"}
            try:
                rec = self.handle_scheme_match(
                    farm_id, land_acres, intent.params.get("category"), intent.params.get("crop_name"),
                )
            except AgentError as exc:
                return {"type": "error", "message": str(exc)}
            return {"type": "recommendation", "intent": intent.action, **rec.as_farmer_summary()}

        if intent.action == "research_query":
            try:
                rec = self.handle_research_query(
                    farm_id, intent.params["query"], intent.params.get("crop_name"),
                )
            except AgentError as exc:
                return {"type": "error", "message": str(exc)}
            return {"type": "recommendation", "intent": intent.action, **rec.as_farmer_summary()}

        # Unreachable given IntentRouter's own validation, but fail
        # honestly rather than silently if it ever is.
        return {"type": "error", "message": f"Unhandled intent action: {intent.action!r}"}

    def handle_voice_message(self, farm_id: int, audio_bytes: bytes,
                              lat: float | None = None, lng: float | None = None,
                              language_hint: str | None = None) -> dict[str, Any]:
        """Spec section 16's voice entry point. Transcribes audio (real
        STT call, or an honest failure if no provider is configured),
        detects the spoken language, then reuses the exact same
        handle_farmer_message pipeline every other conversational path
        goes through — no separate voice-specific intent logic to keep
        in sync. If a TTS provider is configured, also returns synthesized
        audio for the reply; if not, the text reply is still returned
        (spec section 16: voice degrades to text, not to nothing)."""
        context = AgentContext(farm_id=farm_id, memory=self.memory)
        with trace_agent_call(farm_id, "voice_agent", "transcribe"):
            transcript = self.voice_agent.transcribe(context, audio_bytes, language_hint)

        result = self.handle_farmer_message(farm_id, transcript.text, lat, lng)
        result["transcript"] = transcript.text
        result["detected_language"] = transcript.detected_language.value

        reply_text = result.get("what_happened") or result.get("message")
        if reply_text:
            audio_reply = self.voice_agent.synthesize_reply(
                reply_text, transcript.detected_language.value
                if transcript.detected_language.value != "mixed" else "hi",
            )
            if audio_reply is not None:
                result["audio_reply_available"] = True
                result["_audio_reply_bytes"] = audio_reply
            else:
                result["audio_reply_available"] = False

        return result
