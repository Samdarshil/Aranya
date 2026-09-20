"""
Thresholds and constants for the CV pipelines. Kept as plain module-level
constants (not env-driven) because these are calibrated heuristic
thresholds, not secrets or deployment config.
"""

CROP_RISK_THRESHOLDS = {
    "healthy_max": 3.0,
    "at_risk_max": 15.0,
}

SUPPORTED_CROPS = [
    "Tomato", "Potato", "Wheat", "Rice", "Maize/Corn",
    "Cotton", "Sugarcane", "Chili", "Grape", "Other / Not sure",
]

LIVESTOCK_RISK_THRESHOLDS = {
    "low_max": 25.0,
    "moderate_max": 50.0,
    "elevated_max": 75.0,
}

SPECIES_OPTIONS = ["Cow", "Buffalo", "Goat", "Sheep", "Poultry", "Other"]

MIN_SEQUENCE_LENGTH_FOR_TEMPORAL_MODEL = 20

CROP_DISCLAIMER = (
    "This is AI-assisted screening using classical computer-vision indicators "
    "(colour, texture, lesion patterns), NOT a guaranteed agricultural diagnosis. "
    "Please confirm with an agricultural expert before taking action."
)

LIVESTOCK_DISCLAIMER = (
    "This is an early-warning visual/behavioural screening tool, NOT a veterinary "
    "diagnostic replacement. A standard RGB camera does NOT measure body "
    "temperature — this system never performs thermal imaging unless a real "
    "thermal camera module is explicitly connected. Please consult a veterinarian "
    "for confirmation."
)
