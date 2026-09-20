"""
Agricultural knowledge base for the Research Agent — spec section 8.

IMPORTANT CAVEAT, same spirit as scheme_config.py: this is a small,
curated set of well-documented crop diseases/pests, NOT a live
agricultural knowledge API or a complete pest/disease reference. It
exists to demonstrate real matching logic against real (if general and
non-exhaustive) reference content — not to replace an agronomist or the
Vision Agent's actual photo-based screening. Every ResearchAgent
recommendation says this explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeEntry:
    entry_id: str
    title: str
    category: str              # 'disease' | 'pest' | 'general'
    applicable_crops: tuple[str, ...]  # empty tuple = general/all crops
    summary: str
    symptoms: tuple[str, ...]
    management: tuple[str, ...]

    def keywords(self) -> set[str]:
        """Everything searchable about this entry, lowercased and
        tokenized — used for simple keyword-overlap matching."""
        text = " ".join([
            self.title, self.category, " ".join(self.applicable_crops),
            self.summary, " ".join(self.symptoms),
        ])
        return {w.strip(".,()-").lower() for w in text.split() if len(w.strip(".,()-")) > 2}


KNOWLEDGE_BASE: list[KnowledgeEntry] = [
    KnowledgeEntry(
        entry_id="early_blight",
        title="Early blight",
        category="disease",
        applicable_crops=("Tomato", "Potato"),
        summary="A common fungal disease causing dark concentric-ring spots, usually starting on "
                "older/lower leaves and spreading upward.",
        symptoms=("dark brown spots with concentric rings", "yellowing around spots",
                   "lower leaves affected first", "leaf drop in severe cases"),
        management=("Remove and destroy affected leaves", "avoid overhead watering to reduce leaf wetness",
                     "rotate crops — don't replant tomato/potato in the same spot each season",
                     "a copper-based or recommended fungicide can help if caught early"),
    ),
    KnowledgeEntry(
        entry_id="late_blight",
        title="Late blight",
        category="disease",
        applicable_crops=("Tomato", "Potato"),
        summary="A fast-spreading, serious fungal-like disease (Phytophthora infestans) that can "
                "destroy a crop within days in cool, wet weather.",
        symptoms=("water-soaked dark green/brown patches", "white fuzzy growth on leaf undersides in humid conditions",
                   "rapid spread across the whole plant", "blackened stems"),
        management=("Act quickly — this spreads fast", "remove and destroy infected plants",
                     "improve air circulation and avoid overhead watering",
                     "a targeted fungicide is often needed — this one usually warrants an expert opinion"),
    ),
    KnowledgeEntry(
        entry_id="powdery_mildew",
        title="Powdery mildew",
        category="disease",
        applicable_crops=("Tomato", "Chili", "Grape", "Cotton"),
        summary="A fungal disease producing a white/grey powdery coating on leaves, common in warm, "
                "humid conditions with poor air circulation.",
        symptoms=("white or grey powdery coating on leaves", "leaf curling or yellowing",
                   "stunted growth in severe cases"),
        management=("Improve spacing/air circulation between plants", "avoid excess nitrogen fertilizer",
                     "a sulfur-based or recommended fungicide can help"),
    ),
    KnowledgeEntry(
        entry_id="wheat_rust",
        title="Wheat rust (yellow/brown/black rust)",
        category="disease",
        applicable_crops=("Wheat",),
        summary="A fungal disease producing rust-colored pustules on leaves and stems; can spread "
                "rapidly across a field.",
        symptoms=("orange/yellow/brown powdery pustules on leaves", "pustules rub off as colored dust",
                   "stunted, weakened plants"),
        management=("Use rust-resistant wheat varieties where possible", "timely fungicide application if detected early",
                     "monitor neighboring fields — rust spreads via wind-borne spores"),
    ),
    KnowledgeEntry(
        entry_id="rice_blast",
        title="Rice blast",
        category="disease",
        applicable_crops=("Rice",),
        summary="A serious fungal disease affecting leaves, stems, and grain heads, especially "
                "under high humidity and dense planting.",
        symptoms=("diamond-shaped grey-centered lesions on leaves", "infected nodes turn black and can break",
                   "empty or partially filled grain heads"),
        management=("Avoid excess nitrogen fertilizer", "ensure good field drainage",
                     "a recommended fungicide may be needed for severe outbreaks — consult an expert"),
    ),
    KnowledgeEntry(
        entry_id="aphids",
        title="Aphids",
        category="pest",
        applicable_crops=(),  # affects many crops
        summary="Small sap-sucking insects that cluster on new growth and leaf undersides, weakening "
                "plants and spreading viral diseases.",
        symptoms=("clusters of small green/black/white insects on new growth", "curled or yellowing leaves",
                   "sticky honeydew residue, sometimes with sooty mold"),
        management=("Encourage natural predators (ladybugs, lacewings)", "a strong water spray can dislodge light infestations",
                     "neem oil or an approved insecticidal soap for larger infestations"),
    ),
    KnowledgeEntry(
        entry_id="whitefly",
        title="Whitefly",
        category="pest",
        applicable_crops=("Tomato", "Chili", "Cotton"),
        summary="Small white flying insects that cluster on leaf undersides, weaken plants by feeding "
                "on sap, and spread viral diseases.",
        symptoms=("tiny white insects that fly up when the plant is disturbed", "yellowing leaves",
                   "sticky honeydew and sooty mold"),
        management=("Yellow sticky traps help monitor and reduce populations", "neem oil applications",
                     "remove heavily infested leaves"),
    ),
    KnowledgeEntry(
        entry_id="bollworm",
        title="Bollworm",
        category="pest",
        applicable_crops=("Cotton", "Tomato", "Maize/Corn"),
        summary="Caterpillar pest that bores into fruit/bolls/cobs, causing direct yield damage.",
        symptoms=("small holes in fruit/bolls/cobs", "caterpillar droppings near entry holes",
                   "premature fruit drop"),
        management=("Regular field scouting for early detection", "pheromone traps for monitoring",
                     "targeted insecticide application timed to egg-hatch, per local agricultural advisory"),
    ),
]


def search(query: str, crop_name: str | None = None, top_n: int = 3) -> list[tuple[KnowledgeEntry, float]]:
    """Simple deterministic keyword-overlap search — no embeddings, no
    external API. Returns (entry, score) pairs sorted by score descending,
    score in [0, 1]. Entries scoring 0 are excluded entirely."""
    query_words = {w.strip(".,?!()-").lower() for w in query.split() if len(w.strip(".,?!()-")) > 2}
    if not query_words:
        return []

    scored = []
    for entry in KNOWLEDGE_BASE:
        if crop_name and entry.applicable_crops and crop_name not in entry.applicable_crops:
            continue
        overlap = query_words & entry.keywords()
        if not overlap:
            continue
        score = len(overlap) / len(query_words)
        scored.append((entry, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_n]
