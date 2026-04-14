---
name: specialty-templates
description: >
  Load when implementing specialty templates, the trigger classifier, or note
  generation for any specialty. Contains full section definitions for all 5 templates,
  visual trigger keyword lists per specialty (to be refined post-pilot), section
  metadata structure, and completeness score calculation rules. Auto-invoked when
  editing template JSON files, the trigger classifier, or note_gen module template loading.
user-invocable: true
---

# Aurion Specialty Templates

## Template Structure

Each template is a JSON file loaded at startup, stored in DB, and passed to the note generation provider as part of the prompt context.

```json
{
  "key": "orthopedic_surgery",
  "display_name": "Orthopedic Surgery",
  "version": "1.0",
  "sections": [
    {
      "id": "chief_complaint",
      "title": "Chief Complaint",
      "required": true,
      "visual_trigger_keywords": [],
      "description": "Primary reason for the visit in the patient's own words"
    }
  ]
}
```

Section fields:
- `id` — snake_case identifier used in note JSON
- `title` — display name shown in iOS review UI and web portal
- `required` — if true, section counts toward completeness score
- `visual_trigger_keywords` — phrases that suggest a visual moment for this section (start empty, populate post-pilot from Dr. Perry and Dr. Marie's input)
- `description` — guidance for the note generation provider

---

## Completeness Score

`completeness_score = populated_required_sections / total_required_sections`

A section is "populated" when `status == "populated"` and `claims` array is non-empty.
Sections with `status == "pending_video"` or `status == "not_captured"` count as not populated.
Target: ≥ 90% completeness per session.

---

## Template: `orthopedic_surgery`

```json
{
  "key": "orthopedic_surgery",
  "display_name": "Orthopedic Surgery",
  "sections": [
    {
      "id": "chief_complaint",
      "title": "Chief Complaint",
      "required": true,
      "visual_trigger_keywords": [],
      "description": "Primary presenting complaint in the patient's own words"
    },
    {
      "id": "hpi",
      "title": "History of Present Illness",
      "required": true,
      "visual_trigger_keywords": [],
      "description": "Onset, duration, character, radiation, associated symptoms, timing, exacerbating/relieving factors, severity"
    },
    {
      "id": "physical_exam",
      "title": "Physical Examination",
      "required": true,
      "visual_trigger_keywords": [
        "range of motion", "ROM", "flexion", "extension", "rotation",
        "palpation", "tenderness", "guarding", "swelling", "effusion",
        "strength", "sensation", "reflexes", "special test",
        "Lachman", "McMurray", "Hawkins", "Neer", "empty can",
        "looking here", "you can see"
      ],
      "description": "Inspection, palpation, range of motion measurements, strength testing, special orthopedic tests, neurovascular status"
    },
    {
      "id": "imaging_review",
      "title": "Imaging Review",
      "required": true,
      "visual_trigger_keywords": [
        "X-ray", "x-ray", "radiograph", "MRI", "CT", "ultrasound",
        "looking at", "pulling up", "on the screen", "you can see here",
        "this view", "AP view", "lateral view", "comparing"
      ],
      "description": "Description of imaging findings as literally observed on screen — modality, laterality, findings described only"
    },
    {
      "id": "assessment",
      "title": "Assessment",
      "required": true,
      "visual_trigger_keywords": [],
      "description": "Clinical assessment as stated by the physician — diagnosis or working diagnosis explicitly stated"
    },
    {
      "id": "plan",
      "title": "Plan",
      "required": true,
      "visual_trigger_keywords": [],
      "description": "Treatment plan, investigations ordered, referrals, follow-up timeline as stated by the physician"
    }
  ]
}
```

---

## Template: `plastic_surgery`

```json
{
  "key": "plastic_surgery",
  "display_name": "Plastic Surgery",
  "sections": [
    {
      "id": "chief_complaint",
      "title": "Chief Complaint",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "hpi",
      "title": "History of Present Illness",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "wound_assessment",
      "title": "Wound Assessment",
      "required": true,
      "visual_trigger_keywords": [
        "wound", "incision", "flap", "graft", "donor site",
        "wound edges", "approximation", "granulation", "epithelialization",
        "dimensions", "measuring", "depth", "drainage", "exudate",
        "erythema", "induration", "perfusion", "capillary refill",
        "looking at", "right here", "this area"
      ],
      "description": "Wound dimensions, wound bed quality, wound edges, surrounding tissue, drainage, signs of infection, healing progress"
    },
    {
      "id": "imaging_review",
      "title": "Imaging Review",
      "required": true,
      "visual_trigger_keywords": [
        "X-ray", "MRI", "CT", "imaging", "looking at", "pulling up"
      ]
    },
    {
      "id": "assessment",
      "title": "Assessment",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "plan",
      "title": "Plan",
      "required": true,
      "visual_trigger_keywords": []
    }
  ]
}
```

---

## Template: `musculoskeletal`

```json
{
  "key": "musculoskeletal",
  "display_name": "Musculoskeletal / Sports Medicine",
  "sections": [
    {
      "id": "chief_complaint",
      "title": "Chief Complaint",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "hpi",
      "title": "History of Present Illness",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "functional_assessment",
      "title": "Functional Assessment",
      "required": true,
      "visual_trigger_keywords": [
        "gait", "walking", "running", "limping", "antalgic",
        "weight bearing", "loading", "squat", "lunge", "step",
        "balance", "proprioception", "functional test",
        "watching you walk", "watching here"
      ],
      "description": "Functional movement assessment — gait analysis, sport-specific movements, activities of daily living"
    },
    {
      "id": "physical_exam",
      "title": "Physical Examination",
      "required": true,
      "visual_trigger_keywords": [
        "range of motion", "palpation", "tenderness", "strength",
        "special test", "looking here", "you can see"
      ]
    },
    {
      "id": "imaging_review",
      "title": "Imaging Review",
      "required": true,
      "visual_trigger_keywords": [
        "X-ray", "MRI", "ultrasound", "looking at", "pulling up"
      ]
    },
    {
      "id": "assessment",
      "title": "Assessment",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "plan",
      "title": "Plan",
      "required": true,
      "visual_trigger_keywords": []
    }
  ]
}
```

---

## Template: `emergency_medicine`

```json
{
  "key": "emergency_medicine",
  "display_name": "Emergency Medicine",
  "sections": [
    {
      "id": "chief_complaint",
      "title": "Chief Complaint",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "hpi",
      "title": "History of Present Illness",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "vital_signs",
      "title": "Vital Signs",
      "required": true,
      "visual_trigger_keywords": [
        "vitals", "blood pressure", "heart rate", "temperature",
        "oxygen saturation", "sat", "respiratory rate",
        "looking at the monitor", "on the screen"
      ],
      "description": "Vital signs as observed on monitor or stated by physician"
    },
    {
      "id": "physical_exam",
      "title": "Physical Examination",
      "required": true,
      "visual_trigger_keywords": [
        "looking at", "you can see", "examination", "palpation",
        "auscultation", "percussion", "inspection"
      ]
    },
    {
      "id": "investigations",
      "title": "Investigations",
      "required": true,
      "visual_trigger_keywords": [
        "lab", "labs", "blood work", "results", "ECG", "EKG",
        "chest X-ray", "CT", "ultrasound", "looking at"
      ],
      "description": "Lab results, ECG findings, imaging — as stated or shown on screen"
    },
    {
      "id": "assessment",
      "title": "Assessment",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "disposition",
      "title": "Disposition",
      "required": true,
      "visual_trigger_keywords": [],
      "description": "Discharge plan, admission decision, referrals, follow-up instructions as stated by physician"
    }
  ]
}
```

---

## Template: `general`

```json
{
  "key": "general",
  "display_name": "General",
  "sections": [
    {
      "id": "chief_complaint",
      "title": "Chief Complaint",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "hpi",
      "title": "History of Present Illness",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "physical_exam",
      "title": "Physical Examination",
      "required": true,
      "visual_trigger_keywords": [
        "looking at", "you can see", "examination",
        "palpation", "inspection", "right here"
      ]
    },
    {
      "id": "assessment",
      "title": "Assessment",
      "required": true,
      "visual_trigger_keywords": []
    },
    {
      "id": "plan",
      "title": "Plan",
      "required": true,
      "visual_trigger_keywords": []
    }
  ]
}
```

---

## Global Suppression List

These phrases must never trigger frame extraction regardless of template. They describe retrospective narration, not live observation.

```json
[
  "last visit", "previously", "the patient reported", "history of",
  "they mentioned", "recalled", "prior to", "at baseline", "in the past",
  "reported that", "mentioned that", "told me", "said that",
  "has been", "had been", "was experiencing"
]
```

---

## Template Loading at Runtime

Templates loaded at startup from JSON files and stored in PostgreSQL. The note generation provider receives the template as part of the prompt — sections, required status, and descriptions.

```python
# Template loading — Phase 0 / Phase 3
async def get_template(specialty_key: str) -> Template:
    template = await db.get(Template, specialty_key)
    if not template:
        raise ValueError(f"Unknown specialty: {specialty_key}")
    return template

# Completeness calculation
def calculate_completeness(note: Note, template: Template) -> float:
    required = [s for s in template.sections if s.required]
    populated = [s for s in required
                 if note.get_section(s.id) and
                 note.get_section(s.id).status == "populated" and
                 len(note.get_section(s.id).claims) > 0]
    return len(populated) / len(required) if required else 0.0
```

---

## Post-Pilot Refinement

Visual trigger keyword lists start empty for all templates. After the pilot:
1. Dr. Perry Gdalevitch reviews and adds plastic surgery trigger phrases
2. Dr. Marie Gdalevitch reviews and adds orthopedic surgery trigger phrases
3. ML engineer analyzes which triggers produced useful frames vs. noise
4. Keyword lists updated via AppConfig — no code change or redeploy required

The trigger classifier architecture must work with whatever keywords exist. An empty list is valid — the system produces Stage 1 draft notes without visual enrichment until keywords are populated.
