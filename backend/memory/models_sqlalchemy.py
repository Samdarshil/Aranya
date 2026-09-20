"""
Production Farm Memory schema (Postgres via SQLAlchemy) — spec section 9.

STATUS: written, NOT executed or tested in the authoring sandbox — that
environment had no network access to `pip install sqlalchemy`, so this
could not be run against a real Postgres instance there. The currently
*working* Farm Memory implementation is backend/memory/store.py (sqlite,
stdlib-only, fully unit-tested — see tests/). This file is the target
schema to migrate to once the project runs somewhere with normal
dependency installation and a Postgres instance.

Covers the entities from spec section 9 that store.py does not yet model
(SoilProfile, SoilTest, IrrigationEvent, WeatherObservation, DiseaseEvent,
PestEvent, Treatment, TreatmentOutcome, MarketPrice, Expense, Revenue,
Harvest, Sale, GuardianAlert, ExpertConsultation, Conversation, Message,
Notification, AuditLog) in addition to the ones store.py already
implements (Farmer, Farm, Field, VisionScan-equivalent, Recommendation,
FarmEvent). Vector/semantic memory (for free-text farm-memory retrieval)
is noted but not modelled here — see docs/STATUS.md; the recommended
approach is a `pgvector` column on Conversation/Message once that
dependency is available.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # soft delete


class Farmer(Base, TimestampMixin):
    __tablename__ = "farmers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    preferred_language: Mapped[str] = mapped_column(String(10), default="hi")
    farms: Mapped[list["Farm"]] = relationship(back_populates="farmer")


class Farm(Base, TimestampMixin):
    __tablename__ = "farms"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmers.id"))
    name: Mapped[str] = mapped_column(String(200))
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    farmer: Mapped[Farmer] = relationship(back_populates="farms")
    fields: Mapped[list["Field"]] = relationship(back_populates="farm")
    animals: Mapped[list["Animal"]] = relationship(back_populates="farm")


class Field(Base, TimestampMixin):
    __tablename__ = "fields"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"))
    field_ref: Mapped[str] = mapped_column(String(50))
    area_hectares: Mapped[float | None] = mapped_column(Float, nullable=True)
    farm: Mapped[Farm] = relationship(back_populates="fields")
    crop_cycles: Mapped[list["CropCycle"]] = relationship(back_populates="field")
    soil_profile: Mapped["SoilProfile | None"] = relationship(back_populates="field", uselist=False)


class Crop(Base, TimestampMixin):
    __tablename__ = "crops"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class CropVariety(Base, TimestampMixin):
    __tablename__ = "crop_varieties"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    crop_id: Mapped[str] = mapped_column(ForeignKey("crops.id"))
    name: Mapped[str] = mapped_column(String(100))


class CropCycleStatus(str, enum.Enum):
    PLANNED = "planned"
    SOWN = "sown"
    GROWING = "growing"
    HARVESTED = "harvested"
    FAILED = "failed"


class CropCycle(Base, TimestampMixin):
    __tablename__ = "crop_cycles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id"))
    crop_id: Mapped[str] = mapped_column(ForeignKey("crops.id"))
    variety_id: Mapped[str | None] = mapped_column(ForeignKey("crop_varieties.id"), nullable=True)
    sown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_harvest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[CropCycleStatus] = mapped_column(Enum(CropCycleStatus), default=CropCycleStatus.PLANNED)
    field: Mapped[Field] = relationship(back_populates="crop_cycles")


class Animal(Base, TimestampMixin):
    __tablename__ = "animals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"))
    animal_ref: Mapped[str] = mapped_column(String(50))
    species: Mapped[str] = mapped_column(String(50))
    farm: Mapped[Farm] = relationship(back_populates="animals")


class SoilProfile(Base, TimestampMixin):
    __tablename__ = "soil_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id"), unique=True)
    soil_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    field: Mapped[Field] = relationship(back_populates="soil_profile")
    tests: Mapped[list["SoilTest"]] = relationship(back_populates="profile")


class SoilTest(Base, TimestampMixin):
    __tablename__ = "soil_tests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(ForeignKey("soil_profiles.id"))
    tested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ph: Mapped[float | None] = mapped_column(Float, nullable=True)
    nitrogen_ppm: Mapped[float | None] = mapped_column(Float, nullable=True)
    phosphorus_ppm: Mapped[float | None] = mapped_column(Float, nullable=True)
    potassium_ppm: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(50))  # 'lab_report' | 'farmer_reported' | 'provider_api'
    profile: Mapped[SoilProfile] = relationship(back_populates="tests")


class IrrigationEvent(Base, TimestampMixin):
    __tablename__ = "irrigation_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    volume_liters: Mapped[float | None] = mapped_column(Float, nullable=True)


class WeatherObservation(Base, TimestampMixin):
    __tablename__ = "weather_observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    rainfall_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(String(50))  # provider abstraction key, e.g. "openweathermap"


class VisionScan(Base, TimestampMixin):
    """Production equivalent of store.py's vision_scans table."""
    __tablename__ = "vision_scans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_type: Mapped[str] = mapped_column(String(10))  # 'field' | 'animal'
    subject_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(50))
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_metrics: Mapped[dict] = mapped_column(JSON)
    image_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)


class DiseaseEvent(Base, TimestampMixin):
    __tablename__ = "disease_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    crop_cycle_id: Mapped[str] = mapped_column(ForeignKey("crop_cycles.id"))
    vision_scan_id: Mapped[str | None] = mapped_column(ForeignKey("vision_scans.id"), nullable=True)
    pattern_category: Mapped[str] = mapped_column(String(200))  # NOT a confirmed pathogen name
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PestEvent(Base, TimestampMixin):
    __tablename__ = "pest_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    crop_cycle_id: Mapped[str] = mapped_column(ForeignKey("crop_cycles.id"))
    vision_scan_id: Mapped[str | None] = mapped_column(ForeignKey("vision_scans.id"), nullable=True)
    pest_category: Mapped[str] = mapped_column(String(200))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Treatment(Base, TimestampMixin):
    __tablename__ = "treatments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    disease_event_id: Mapped[str | None] = mapped_column(ForeignKey("disease_events.id"), nullable=True)
    pest_event_id: Mapped[str | None] = mapped_column(ForeignKey("pest_events.id"), nullable=True)
    action_taken: Mapped[str] = mapped_column(Text)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped["TreatmentOutcome | None"] = relationship(back_populates="treatment", uselist=False)


class TreatmentOutcome(Base, TimestampMixin):
    __tablename__ = "treatment_outcomes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    treatment_id: Mapped[str] = mapped_column(ForeignKey("treatments.id"), unique=True)
    followed_up_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    improved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    treatment: Mapped[Treatment] = relationship(back_populates="outcome")


class Recommendation(Base, TimestampMixin):
    """Production equivalent of store.py's recommendations table — mirrors
    backend.core.schemas.Recommendation field-for-field."""
    __tablename__ = "recommendations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"))
    scan_id: Mapped[str | None] = mapped_column(ForeignKey("vision_scans.id"), nullable=True)
    problem: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(20))
    urgency: Mapped[str] = mapped_column(String(20))
    recommended_action: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str] = mapped_column(Text)
    monitoring_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalate_to_expert: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_agent: Mapped[str] = mapped_column(String(50))
    farmer_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FarmEvent(Base, TimestampMixin):
    __tablename__ = "farm_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"))
    event_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)


class MarketPrice(Base, TimestampMixin):
    __tablename__ = "market_prices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    crop_id: Mapped[str] = mapped_column(ForeignKey("crops.id"))
    market_name: Mapped[str] = mapped_column(String(200))
    price_per_quintal: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(50))  # e.g. "agmarknet"


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"))
    category: Mapped[str] = mapped_column(String(100))
    amount: Mapped[float] = mapped_column(Float)
    incurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Revenue(Base, TimestampMixin):
    __tablename__ = "revenues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"))
    source: Mapped[str] = mapped_column(String(100))
    amount: Mapped[float] = mapped_column(Float)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Harvest(Base, TimestampMixin):
    __tablename__ = "harvests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    crop_cycle_id: Mapped[str] = mapped_column(ForeignKey("crop_cycles.id"))
    harvested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quantity_kg: Mapped[float] = mapped_column(Float)


class Sale(Base, TimestampMixin):
    __tablename__ = "sales"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    harvest_id: Mapped[str] = mapped_column(ForeignKey("harvests.id"))
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quantity_kg: Mapped[float] = mapped_column(Float)
    price_per_kg: Mapped[float] = mapped_column(Float)
    buyer: Mapped[str | None] = mapped_column(String(200), nullable=True)


class GuardianAlert(Base, TimestampMixin):
    """Farm Guardian output — spec section 12."""
    __tablename__ = "guardian_alerts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"))
    alert_type: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    recommended_action: Mapped[str] = mapped_column(Text)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExpertConsultation(Base, TimestampMixin):
    __tablename__ = "expert_consultations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"))
    recommendation_id: Mapped[str | None] = mapped_column(ForeignKey("recommendations.id"), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expert_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"))
    channel: Mapped[str] = mapped_column(String(20))  # 'app' | 'voice' | 'sms' | 'whatsapp'
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(20))  # 'farmer' | 'aranya'
    content: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"))
    channel: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(20), default="pending")


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(200))  # farmer id, agent name, or "system"
    action: Mapped[str] = mapped_column(String(200))
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
