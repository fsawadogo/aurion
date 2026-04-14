"""Eval agent configuration."""

API_BASE_URL = "http://localhost:8080"
API_VERSION = "v1"
API_URL = f"{API_BASE_URL}/api/{API_VERSION}"
AUTH_TOKEN = "CLINICIAN"

# Eval scenarios — golden test visits per CLAUDE.md
ORTHOPEDIC_SCENARIO = {
    "specialty": "orthopedic_surgery",
    "transcript_segments": [
        "The patient presents today with right knee pain that has been worsening over the past three weeks.",
        "He reports the pain started after a twisting injury during a recreational soccer game.",
        "The pain is worse with stairs and prolonged sitting, rated six out of ten.",
        "There is tenderness on palpation at the medial joint line.",
        "Range of motion is restricted, flexion limited to approximately 110 degrees.",
        "McMurray test is positive with a palpable click on the medial side.",
        "Looking at the MRI, there is a horizontal tear of the medial meniscus posterior horn.",
        "No visible fracture or loose bodies identified.",
        "Assessment is medial meniscus tear, right knee.",
        "Plan is to refer for arthroscopic partial meniscectomy and start physiotherapy.",
    ],
}

PLASTIC_SURGERY_SCENARIO = {
    "specialty": "plastic_surgery",
    "transcript_segments": [
        "The patient presents for follow-up of the left forearm flap reconstruction, now post-operative day fourteen.",
        "She reports mild discomfort at the donor site but no drainage or fever.",
        "The wound edges appear well approximated with no signs of infection.",
        "There is healthy granulation tissue visible at the wound base.",
        "Dimensions of the flap are approximately eight by four centimeters.",
        "Capillary refill is brisk, less than two seconds.",
        "No erythema or induration at the flap margins.",
        "The donor site is healing well with epithelialization from the edges.",
        "Assessment is healing flap reconstruction, left forearm, progressing as expected.",
        "Plan is to continue wound care, follow up in two weeks, and remove sutures at that visit.",
    ],
}

# Scoring rubric
SCORING_RUBRIC = {
    "completeness": "Percentage of required template sections that have at least one populated claim (target >= 90%)",
    "citation_traceability": "Percentage of claims that have a valid source_id linking to a transcript segment (target >= 95%)",
    "descriptive_mode": "Pass/fail — any interpretive, diagnostic, or suggestive statements constitute a failure",
    "hallucination": "Count of claims not traceable to any source segment — target 0",
    "section_accuracy": "Per-section score: are claims placed in the correct template section (0-100%)",
}
