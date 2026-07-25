"use client"

import { type FormEvent, memo, useMemo, useRef, useState } from "react"
import {
  Bell,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Clock3,
  Copy,
  Download,
  Eye,
  FolderOpen,
  Languages,
  Library,
  LogOut,
  MessageSquareText,
  Mic,
  Pause,
  Play,
  Plus,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Square,
  Stethoscope,
  Upload,
  UserRound,
} from "lucide-react"

import { Link } from "@/i18n/navigation"
import type { AppLocale } from "@/i18n/routing"
import { cn } from "@/lib/utils"

type View =
  | "schedule"
  | "patients"
  | "newVisit"
  | "capture"
  | "validation"
  | "templates"
  | "profile"

type VisitStatus = "ready" | "preparing" | "pendingConsent" | "recorded" | "completed"

type Visit = {
  id: string
  time: string
  patient: string
  visitType: string
  context: string
  status: VisitStatus
  seenBy?: string
  tags?: string[]
}

const visits: Visit[] = [
  {
    id: "visit-03",
    time: "9:00 AM",
    patient: "Patient A",
    visitType: "Knee follow-up",
    context: "Doctor recording completed from smart glasses. Draft note is ready for edits.",
    status: "recorded",
    seenBy: "Dr. Marie Gdalevitch",
    tags: ["Smart glasses", "Ready for review"],
  },
  {
    id: "visit-04",
    time: "9:30 AM",
    patient: "Patient B",
    visitType: "Initial consultation",
    context: "Nurse triage completed. Doctor still needs to see the patient and complete their note.",
    status: "ready",
    seenBy: "Inf: Sarah Jenkins",
    tags: ["Triage complete"],
  },
  {
    id: "visit-05",
    time: "10:15 AM",
    patient: "Patient C",
    visitType: "Shoulder consult",
    context: "Follow-up after physiotherapy. Screen review expected.",
    status: "preparing",
  },
  {
    id: "visit-06",
    time: "11:00 AM",
    patient: "Patient D",
    visitType: "Post-op review",
    context: "One-week post-operative check. Wound appearance and ROM are key observations.",
    status: "pendingConsent",
  },
]

const patientFiles = [
  {
    id: "k",
    title: "Patient Identifier K",
    subtitle: "Visit ID 09 · Chest pain",
    status: "Active",
    encounters: "3 encounters",
  },
  {
    id: "l",
    title: "Patient Identifier L",
    subtitle: "Visit ID 10 · Routine follow-up",
    status: "Ready",
    encounters: "1 encounter",
  },
  {
    id: "m",
    title: "Patient Identifier M",
    subtitle: "Visit ID 11 · Post-op check",
    status: "Ready",
    encounters: "5 encounters",
  },
  {
    id: "j",
    title: "Patient Identifier J",
    subtitle: "Visit ID 08 · Consultation",
    status: "Completed",
    encounters: "Summary generated",
  },
]

const templates = [
  {
    name: "Knee Follow-up Protocol",
    specialty: "Orthopedics",
    type: "SOAP note",
    sections: ["HPI", "ROS", "Physical Exam", "Assessment & Plan"],
  },
  {
    name: "Orthopedic SOAP Note",
    specialty: "Orthopedics",
    type: "SOAP note",
    sections: ["Subjective", "Objective", "Imaging", "Plan"],
  },
  {
    name: "Post-op Review",
    specialty: "Orthopedics",
    type: "Progress note",
    sections: ["Procedure", "Wound", "ROM", "Follow-up"],
  },
  {
    name: "Initial Consultation",
    specialty: "Musculoskeletal medicine",
    type: "Encounter summary",
    sections: ["History", "Exam", "Clinical impression", "Plan"],
  },
]

const visitTypeTemplates = [
  { visitType: "Initial consultation", noteTemplate: "Initial Consultation", captureDefault: "Ambient capture" },
  { visitType: "Follow-up visit", noteTemplate: "Orthopedic SOAP Note", captureDefault: "Smart dictation" },
  { visitType: "Post-operative review", noteTemplate: "Post-op Review", captureDefault: "Audio + Video" },
  { visitType: "Fracture consultation", noteTemplate: "Orthopedic SOAP Note", captureDefault: "Ambient capture" },
]

const profileTypeOptions = [
  { id: "doctor", en: "Doctor", fr: "Medecin" },
  { id: "nurse", en: "Nurse", fr: "Infirmiere" },
  { id: "resident", en: "Resident", fr: "Resident" },
  { id: "fellow", en: "Fellow", fr: "Fellow" },
  { id: "medical-student", en: "Medical student", fr: "Etudiant en medecine" },
  { id: "nurse-practitioner", en: "Nurse practitioner", fr: "Infirmiere praticienne" },
  { id: "physician-assistant", en: "Physician assistant", fr: "Adjoint medical" },
]

const copy = {
  en: {
    brand: "Aurion Clinical AI",
    clinician: "Dr. Marie Gdalevitch",
    role: "Orthopedic clinic",
    nav: {
      schedule: "Schedule",
      patients: "Patient Files",
      newVisit: "New Visit",
      validation: "Review & Validate",
      templates: "Templates",
      profile: "Profile",
      support: "Support / Feedback",
      signOut: "Sign Out",
    },
    common: {
      search: "Search visits, patients, or notes...",
      today: "Today",
      upcoming: "Upcoming",
      ready: "Ready",
      preparing: "Preparing",
      pendingConsent: "Pending consent",
      recorded: "Recording complete",
      completed: "Completed",
      startVisit: "Start Visit",
      prepareVisit: "Start Visit",
      reviewNote: "Review Note",
      uploadSchedule: "Upload Schedule",
      startCapture: "Start Capture",
      confirmConsent: "Consent confirmed and timestamped",
      simulated: "Simulated",
      continue: "Continue",
    },
    schedule: {
      title: "Today’s Schedule",
      date: "Monday, May 4, 2026",
      selectDate: "Select a date",
      providers: "Providers",
      myCalendar: "My calendar",
      helperTitle: "Clinic readiness",
      nextPatient: "Next patient",
      pendingNotes: "Pending notes",
      captureReady: "Live transcript and audio + video capture ready",
      recordedDevice: "Smart glasses",
      recordedReady: "Ready for review",
      combineNotes: "Combine all notes",
      privacy: "Privacy shield enabled",
      template: "Knee Follow-up Protocol selected",
      consent: "Consent required before capture",
      queue: "1 note ready for validation",
    },
    setup: {
      title: "Prepare Visit",
      subtitle: "Visit type and encounter context are enough to start. Defaults for device, language, and template come from your profile.",
      patientLabel: "Encounter",
      identifier: "Temporary identifier",
      visitType: "Visit type",
      context: "Encounter context",
      inputs: "Capture input",
      inputOptions: ["Smart dictation", "Ambient capture", "Word for Word", "Audio + Video"],
      device: "Capture device",
      deviceOptions: ["Smart glasses", "Body camera", "Phone / tablet"],
      outputLanguage: "Output Language",
      languageOptions: ["Auto detect", "English", "French"],
      template: "Note template",
      templateHint: "Change anytime in Templates or Profile.",
      selectTemplate: "Change template",
    },
    capture: {
      title: "Live Visit Capture",
      subtitle: "The clinician delivers care while Aurion captures the encounter passively.",
      elapsed: "Elapsed",
      audio: "Audio + Video",
      transcript: "Live transcript",
      changes: "Make edits",
      changesPlaceholder: "Type or dictate changes to the transcript. Example: replace right knee with left knee, add that pain is worse on stairs, remove duplicate sentence.",
      pause: "Pause",
      stop: "Stop Recording",
    },
    validation: {
      title: "Review & Validate",
      subtitle: "One review of the complete note before it enters the patient file. Internal validation can use source-linked evidence separately.",
      approve: "Approve Note",
      copy: "Copy Note",
      export: "Export DOCX",
      send: "Send to Patient File",
      evidence: "Evidence traceability",
      audio: "Audio evidence",
      visual: "Visual observation evidence",
      screen: "Screen-derived evidence",
      audit: "Consent and privacy audit",
      chatTitle: "Edit with Aurion",
      chatHint: "Describe changes in plain language. This demo applies simple updates; production would use a secure model.",
      chatPlaceholder: "e.g. Change right shoulder to left shoulder, or add that pain is worse on stairs…",
      chatAssistantIntro:
        "Ask for edits in plain language, or change the note directly above. Try “swap right and left shoulder” or “add stair pain.”",
      chatSend: "Send",
    },
    patients: {
      title: "Patient Files",
      subtitle: "De-identified containers for today’s encounters and prior notes.",
      select: "Select a patient file to review history, encounters, and generated notes.",
      addVisit: "Add Visit",
    },
    templates: {
      title: "Templates",
      subtitle: "Template structures shape the output note without changing capture.",
      my: "My Templates",
      community: "Community Library",
      use: "Use Template",
      upload: "Upload Template",
      preview: "Template Preview",
    },
    profile: {
      title: "Physician Profile & Preferences",
      subtitle: "Configure clinical defaults for personalized documentation.",
      type: "Profile type",
      practice: "Practice & clinical defaults",
      consultation: "Common consultation types",
      language: "Language & transcription",
      privacy: "Data archiving & privacy",
      save: "Save Preferences",
    },
    support: {
      title: "Support / Feedback",
      subtitle: "Demo notes for internal UI review.",
      feedback: "Feedback to capture",
      limitations: "Prototype limitations",
      contact: "Aurion team contact",
    },
  },
  fr: {
    brand: "Aurion IA clinique",
    clinician: "Dre Marie Gdalevitch",
    role: "Clinique orthopédique",
    nav: {
      schedule: "Horaire",
      patients: "Dossiers patients",
      newVisit: "Nouvelle visite",
      validation: "Révision et validation",
      templates: "Modèles",
      profile: "Profil",
      support: "Soutien / Commentaires",
      signOut: "Déconnexion",
    },
    common: {
      search: "Rechercher visites, patients ou notes...",
      today: "Aujourd’hui",
      upcoming: "À venir",
      ready: "Prêt",
      preparing: "En préparation",
      pendingConsent: "Consentement requis",
      recorded: "Enregistrement termine",
      completed: "Terminé",
      startVisit: "Commencer la visite",
      prepareVisit: "Commencer la visite",
      reviewNote: "Réviser la note",
      uploadSchedule: "Importer l’horaire",
      startCapture: "Démarrer la capture",
      confirmConsent: "Consentement confirmé et horodaté",
      simulated: "Simulation",
      continue: "Continuer",
    },
    schedule: {
      title: "Horaire du jour",
      date: "Lundi 4 mai 2026",
      selectDate: "Choisir une date",
      providers: "Fournisseurs",
      myCalendar: "Mon calendrier",
      helperTitle: "Préparation clinique",
      nextPatient: "Prochain patient",
      pendingNotes: "Notes en attente",
      captureReady: "Transcription en direct et capture audio + video pretes",
      recordedDevice: "Lunettes intelligentes",
      recordedReady: "Pret a reviser",
      combineNotes: "Combiner les notes",
      privacy: "Bouclier de confidentialité activé",
      template: "Modèle de suivi du genou sélectionné",
      consent: "Consentement requis avant la capture",
      queue: "1 note prête pour validation",
    },
    setup: {
      title: "Préparer la visite",
      subtitle: "Le type de visite et le contexte suffisent pour démarrer. Dispositif, langue et modèle viennent du profil.",
      patientLabel: "Rencontre",
      identifier: "Identifiant temporaire",
      visitType: "Type de visite",
      context: "Contexte de la rencontre",
      inputs: "Source de capture",
      inputOptions: ["Dictee intelligente", "Capture ambiante", "Mot a mot", "Audio + Video"],
      device: "Dispositif de capture",
      deviceOptions: ["Lunettes intelligentes", "Camera corporelle", "Telephone / tablette"],
      outputLanguage: "Langue de sortie",
      languageOptions: ["Detection automatique", "Anglais", "Francais"],
      template: "Modèle de note",
      templateHint: "Modifiable dans Modèles ou Profil.",
      selectTemplate: "Changer de modèle",
    },
    capture: {
      title: "Capture de la visite",
      subtitle: "Le médecin soigne le patient pendant qu’Aurion capture la rencontre passivement.",
      elapsed: "Temps écoulé",
      audio: "Audio + Video",
      transcript: "Transcription en direct",
      changes: "Modifier",
      changesPlaceholder: "Saisir ou dicter les changements a apporter a la transcription.",
      pause: "Pause",
      stop: "Arreter l'enregistrement",
    },
    validation: {
      title: "Révision et validation",
      subtitle: "Une seule révision de la note complète avant le dossier patient. La traçabilité des sources reste pour la validation interne.",
      approve: "Approuver la note",
      copy: "Copier la note",
      export: "Exporter DOCX",
      send: "Envoyer au dossier patient",
      evidence: "Traçabilité des preuves",
      audio: "Preuve audio",
      visual: "Preuve visuelle",
      screen: "Preuve issue de l’écran",
      audit: "Audit consentement et confidentialité",
      chatTitle: "Modifier avec Aurion",
      chatHint: "Décrivez les changements en langage courant. Cette démo applique des mises à jour simples.",
      chatPlaceholder: "p. ex. remplacer épaule droite par épaule gauche, ou ajouter douleur dans les escaliers…",
      chatAssistantIntro:
        "Demandez des modifications en langage courant, ou éditez la note ci-dessus. Essayez « inverser droite et gauche » ou « ajouter douleur aux escaliers ».",
      chatSend: "Envoyer",
    },
    patients: {
      title: "Dossiers patients",
      subtitle: "Conteneurs dépersonnalisés pour les rencontres du jour et les notes antérieures.",
      select: "Sélectionner un dossier pour consulter l’historique, les rencontres et les notes générées.",
      addVisit: "Ajouter une visite",
    },
    templates: {
      title: "Modèles",
      subtitle: "Les modèles structurent la note sans modifier la capture.",
      my: "Mes modèles",
      community: "Bibliothèque communautaire",
      use: "Utiliser le modèle",
      upload: "Importer un modèle",
      preview: "Aperçu du modèle",
    },
    profile: {
      title: "Profil et préférences du médecin",
      subtitle: "Configurer les valeurs cliniques par défaut pour personnaliser la documentation.",
      type: "Type de profil",
      practice: "Valeurs cliniques par défaut",
      consultation: "Types de consultation courants",
      language: "Langue et transcription",
      privacy: "Archivage et confidentialité",
      save: "Enregistrer les préférences",
    },
    support: {
      title: "Soutien / Commentaires",
      subtitle: "Notes de démonstration pour la révision interne de l’interface.",
      feedback: "Commentaires à recueillir",
      limitations: "Limites du prototype",
      contact: "Contact équipe Aurion",
    },
  },
} as const

const localizedVisitText = {
  en: {
    hpi: "Patient reports persistent right knee pain during flexion after increased activity. Symptoms are worse on stairs and improve with rest.",
    exam: "Observed antalgic gait favoring the right side on room entry. Range of motion demonstrated from 0 to 105 degrees with discomfort at terminal flexion.",
    screen: "Prior MRI summary reviewed on screen. Report notes mild medial compartment degenerative change without acute fracture.",
    plan: "Continue physiotherapy, use activity modification, and follow up in four weeks if symptoms persist.",
    transcript1: "Patient describing sharp pain during flexion.",
    transcript2: "Physician examining joint stability.",
    transcript3: "Clinician reviewed prior MRI summary on screen.",
    visual: "Patient demonstrated guarded knee flexion during range-of-motion assessment.",
  },
  fr: {
    hpi: "Le patient rapporte une douleur persistante au genou droit en flexion après une augmentation de l’activité. Les symptômes sont plus marqués dans les escaliers et s’améliorent au repos.",
    exam: "Démarche antalgique observée en faveur du côté droit à l’entrée dans la salle. Amplitude de mouvement de 0 à 105 degrés avec inconfort en fin de flexion.",
    screen: "Résumé de l’IRM antérieure consulté à l’écran. Le rapport note de légers changements dégénératifs du compartiment médial sans fracture aiguë.",
    plan: "Poursuivre la physiothérapie, adapter les activités et revoir dans quatre semaines si les symptômes persistent.",
    transcript1: "Le patient décrit une douleur vive pendant la flexion.",
    transcript2: "Le médecin examine la stabilité articulaire.",
    transcript3: "Le clinicien consulte le résumé d’IRM antérieur à l’écran.",
    visual: "Le patient démontre une flexion du genou protégée pendant l’évaluation de l’amplitude.",
  },
} as const

const encounterHistory = [
  {
    id: "nurse",
    time: "08:42",
    role: "Inf",
    name: "Sarah Jenkins",
    status: "Signed",
    summary: "Triage note: pain score documented, vitals reviewed, mobility concern flagged.",
    note: "Triage note\nPatient reports right knee pain with stairs and prolonged walking. Pain score 6/10. Vitals stable. No fever or acute systemic symptoms reported. Mobility concern flagged for physician review.",
  },
  {
    id: "resident",
    time: "08:58",
    role: "Resident",
    name: "Alex Chen",
    status: "Signed",
    summary: "Resident note: preliminary exam documented and imaging history summarized.",
    note: "Resident note\nRight knee pain after increased activity. Mild antalgic gait observed. Range of motion limited by pain at terminal flexion. Prior MRI summary reviewed: mild medial compartment degenerative change, no acute fracture.",
  },
  {
    id: "doctor",
    time: "09:18",
    role: "Doctor",
    name: "Dr. Marie Gdalevitch",
    status: "Completed",
    summary: "Completed orthopedic consultation note for shoulder trauma with concern for fracture.",
    note: `Reason for Consultation
Evaluation and management of shoulder injury following trauma, with concern for fracture.

History of Present Illness
[Patient Name] is a [age]-year-old [male/female] who presents following a [mechanism of injury] (e.g., fall onto outstretched arm, direct blow, motor vehicle accident) occurring on [date/time].

The patient reports:
- Immediate pain in the [left/right] shoulder
- Difficulty or inability to move the arm
- Associated swelling and possible deformity
- Pain severity: [X/10]
- Aggravated by movement, relieved partially by immobilization

Denies:
- Loss of consciousness (if applicable)
- Head injury symptoms
- Distal numbness or weakness (unless present)

Initial management:
- Seen in [ER/clinic]
- Arm immobilized in a sling
- Analgesics provided

Past Medical History
[e.g., Hypertension, Diabetes, Osteoporosis]

Past Surgical History
[Relevant orthopedic or other surgeries]

Medications
[List medications]

Allergies
[Drug allergies]

Social History
Occupation: [Important for CNESST/work injury context]
Smoking: [Yes/No]
Alcohol: [Use]
Functional baseline: Independent / limitations

Review of Systems
Constitutional: No fever, chills
Neurological: No focal deficits reported
Musculoskeletal: Pain localized to shoulder
Others: Non-contributory unless specified

Physical Examination
General: Alert, oriented, in moderate distress due to pain

Inspection
Swelling over [proximal humerus/clavicle/scapula]
Possible deformity or asymmetry
No open wounds unless specified

Palpation
Tenderness over [proximal humerus / clavicle / AC joint / scapula]
Crepitus may be present

Range of Motion
Severely limited due to pain
Active ROM: Restricted
Passive ROM: Painful

Neurovascular Examination
Sensation intact over axillary nerve distribution (deltoid area)
Motor: Deltoid function: [Intact/Impaired]
Distal pulses: Radial pulse present
Capillary refill normal

Imaging
X-rays (Date)
Views: AP, lateral, scapular Y
Findings: [Type of fracture] (e.g., proximal humerus fracture, surgical neck fracture)
Displacement: [Non-displaced / minimally displaced / displaced]
Number of fragments: [e.g., 2-part, 3-part, 4-part fracture]

CT Scan (if performed)
Confirms fracture pattern
Better delineation of comminution/articular involvement

Assessment
Diagnosis: [Left/Right] proximal humerus fracture
Type: [e.g., Neer classification - 2-part surgical neck fracture]

Clinical Summary
This is a [stable/unstable] fracture of the shoulder resulting from [mechanism], with [degree of displacement] and [no / possible] neurovascular compromise.

Plan
Non-Operative Management (if applicable)
- Sling immobilization for 2-4 weeks
- Pain control: Acetaminophen +/- NSAIDs
- Consider short course opioids if severe pain
- Early physiotherapy: Pendulum exercises after acute phase
- Follow-up imaging in 1-2 weeks to assess alignment

Operative Management (if indicated)
Indications:
- Significant displacement
- Multi-part fracture
- Articular involvement
- Functional demands of patient

Options:
- ORIF (Open Reduction Internal Fixation)
- Intramedullary nailing
- Shoulder arthroplasty (in severe cases)

Rehabilitation
Gradual ROM progression
Strengthening at 6-8 weeks
Full recovery timeline: 3-6 months depending on severity

Follow-Up
Orthopedic clinic in [X days/weeks]
Monitor for malunion, nonunion, shoulder stiffness, and avascular necrosis (in proximal humerus fractures).

Medico-Legal / Functional Considerations (Important for CNESST)
Mechanism consistent with reported injury.
Functional limitations: restricted lifting and reduced overhead activity.
Temporary work restrictions: no lifting > [X kg], no overhead use of affected arm.
Prognosis: generally favorable with appropriate treatment, dependent on fracture type and compliance with rehab.`,
  },
]

const evidenceLibrary = {
  "audio-chief": {
    title: "Chief complaint transcript",
    kind: "Audio transcript",
    source: "00:18-00:46",
    lines: [
      "Patient reports right shoulder pain following a fall onto the right side.",
      "Patient states pain began immediately after trauma and is worse with movement.",
    ],
  },
  "audio-hpi": {
    title: "History transcript",
    kind: "Audio transcript",
    source: "01:12-02:10",
    lines: [
      "Pain severity reported as 8 out of 10.",
      "Pain is localized over the proximal humerus without radiation.",
      "No numbness or tingling reported.",
    ],
  },
  "video-inspection": {
    title: "Physical exam video frames",
    kind: "Video frame",
    source: "Frame 03:14, 03:28, 03:51",
    media: [
      { src: "/clinic-mode-capture.jpeg", alt: "Shoulder inspection capture frame" },
      { src: "/exam-grid.jpeg", alt: "Orthopedic physical exam capture grid" },
    ],
    lines: [
      "Frame 03:14: swelling visible over the right shoulder.",
      "Frame 03:28: patient guards the right arm in sling position.",
      "Frame 03:51: active shoulder motion severely limited by pain.",
    ],
  },
  "video-neuro": {
    title: "Neurovascular exam video",
    kind: "Video frame",
    source: "Frame 04:22, 04:47",
    media: [
      { src: "/doctor-patient.jpg", alt: "Clinician checking upper extremity exam findings" },
      { src: "/clinical-environment.jpg", alt: "Clinical exam room capture frame" },
    ],
    lines: [
      "Frame 04:22: deltoid contraction checked.",
      "Frame 04:47: radial pulse and capillary refill assessed.",
    ],
  },
  "screen-xray": {
    title: "Right shoulder X-ray report",
    kind: "Screen frame",
    source: "Imaging screen 05:36",
    media: [
      { src: "https://upload.wikimedia.org/wikipedia/commons/4/42/ProxHumeralFracture.png", alt: "Proximal humerus fracture X-ray" },
      { src: "https://upload.wikimedia.org/wikipedia/commons/f/f4/Proxhumerousfrac.png", alt: "Shoulder X-ray with proximal humerus fracture" },
    ],
    lines: [
      "X-ray right shoulder: proximal humerus fracture.",
      "Minimally displaced surgical neck fracture.",
      "No dislocation.",
    ],
  },
  "screen-plan": {
    title: "Plan and restrictions reference",
    kind: "Screen frame",
    source: "Plan screen 07:02",
    media: [
      { src: "/imaging-review-1.jpeg", alt: "Imaging review screen frame" },
      { src: "/imaging-review-2.jpeg", alt: "Follow-up plan screen frame" },
    ],
    lines: [
      "Sling immobilization and pain control reviewed.",
      "Repeat X-ray in 1-2 weeks.",
      "No lifting or overhead movement with affected arm.",
    ],
  },
}

const soapNoteSections = [
  {
    title: "Orthopedic SOAP Note - Shoulder Fracture",
    blocks: [
      {
        heading: "S - Subjective",
        paragraphs: [
          { text: "Right shoulder pain after a fall onto the right side. Pain is 8/10, localized over the proximal humerus, worse with movement, and improved with sling immobilization." },
        ],
      },
      {
        heading: "O - Objective",
        paragraphs: [
          { text: "Swelling and mild deformity over the right shoulder. Active ROM is severely limited. Neurovascular exam is intact. X-ray shows a minimally displaced surgical neck fracture without dislocation." },
        ],
      },
      {
        heading: "A - Assessment",
        paragraphs: [
          { text: "Right proximal humerus fracture, surgical neck, minimally displaced, with no neurovascular compromise." },
        ],
      },
      {
        heading: "P - Plan",
        paragraphs: [
          { text: "Continue sling for 2-3 weeks, use acetaminophen +/- NSAIDs, begin pendulum exercises in 1-2 weeks, repeat X-ray at follow-up, and avoid lifting or overhead activity." },
        ],
      },
    ],
  },
]

function buildInitialSoapNoteText(): string {
  const [{ title, blocks }] = soapNoteSections
  const body = blocks
    .map((b) => `${b.heading}\n${b.paragraphs.map((p) => p.text).join(" ")}`)
    .join("\n\n")
  return `${title}\n\n${body}`
}

function mockApplyNoteEdit(noteText: string, instruction: string): { reply: string; nextNote: string } {
  const ins = instruction.trim()
  const lower = ins.toLowerCase()
  let next = noteText

  if (!ins) {
    return { reply: "Describe how you want the note changed.", nextNote: next }
  }

  if (
    /\bright\b.*\bleft\b|\bleft\b.*\bright\b|swap|change.*right.*to.*left|change.*left.*to.*right|inverser|droite.*gauche|gauche.*droite/i.test(
      instruction,
    )
  ) {
    next = next
      .replace(/\bright shoulder\b/gi, "@@TMP_RIGHT@@")
      .replace(/\bleft shoulder\b/gi, "right shoulder")
      .replace(/@@TMP_RIGHT@@/g, "left shoulder")
    return {
      reply: "Demo: updated shoulder laterality where those phrases appeared. Review the note above.",
      nextNote: next,
    }
  }

  if (/stair|stairs|escalier/i.test(lower)) {
    if (!/stair|escalier/i.test(next)) {
      next = next.replace(/(S - Subjective\n)([^\n]+)/, (_, h: string, line: string) => `${h}${line.trim()} Pain is worse on stairs.`)
    }
    return {
      reply: "Demo: added stair-related wording to the subjective line. Adjust in the note if needed.",
      nextNote: next,
    }
  }

  return {
    reply:
      'Demo: try “change right shoulder to left shoulder” or “add stair pain.” You can also edit the note directly above.',
    nextNote: next,
  }
}

const mergedNotePreview = `Merged Orthopedic SOAP Note - Shoulder Fracture

S - Subjective
Patient presents with right shoulder pain following trauma after a fall onto the right side. Pain began immediately, is rated 8/10, and is localized over the proximal humerus without radiation. Movement and lifting aggravate symptoms; rest and sling immobilization provide partial relief. Nurse triage documented swelling and stable vitals. Resident assessment confirmed no distal numbness or tingling.

O - Objective
Patient is alert and in moderate distress due to pain. Right shoulder inspection shows swelling and mild deformity without open wounds. Palpation demonstrates tenderness over the proximal humerus without clavicle or scapular tenderness. Active ROM is severely limited and passive ROM is painful. Neurovascular exam is intact, including axillary nerve sensation, deltoid contraction, radial pulse, and capillary refill under 2 seconds. X-ray confirms minimally displaced surgical neck fracture of the proximal humerus with no dislocation.

A - Assessment
Right proximal humerus fracture, surgical neck, minimally displaced. No neurovascular compromise. Mechanism is consistent with the injury.

P - Plan
Continue sling immobilization for 2-3 weeks. Use acetaminophen +/- NSAIDs and consider short course opioids if required. Begin pendulum exercises in 1-2 weeks with gradual ROM progression under physiotherapy. Reassess in 1-2 weeks with repeat X-ray. No lifting with affected arm and avoid overhead movement. Expected recovery is 3-4 months with compliance.`

const navItems: Array<{ view: View; icon: typeof CalendarDays; key: keyof typeof copy.en.nav }> = [
  { view: "schedule", icon: CalendarDays, key: "schedule" },
  { view: "patients", icon: FolderOpen, key: "patients" },
  { view: "newVisit", icon: Plus, key: "newVisit" },
  { view: "templates", icon: Library, key: "templates" },
  { view: "profile", icon: UserRound, key: "profile" },
]

export function PrototypeApp({ locale }: { locale: AppLocale }) {
  const t = copy[locale]
  const note = localizedVisitText[locale]
  const [activeView, setActiveView] = useState<View>("schedule")
  const [selectedVisit, setSelectedVisit] = useState<Visit>(visits[0])
  const [selectedTemplate, setSelectedTemplate] = useState(templates[0])
  const [consent, setConsent] = useState(false)
  const [paused, setPaused] = useState(false)
  const [approved, setApproved] = useState(false)
  const [captureStopped, setCaptureStopped] = useState(false)
  const [profileType, setProfileType] = useState(profileTypeOptions[0].id)

  const visitRows = useMemo(
    () =>
      visits.map((visit) =>
        approved && visit.id === selectedVisit.id
          ? { ...visit, status: "completed" as VisitStatus }
          : visit,
      ),
    [approved, selectedVisit.id],
  )

  function openVisit(visit: Visit, mode: "setup" | "validation" = "setup") {
    setSelectedVisit(visit)
    setConsent(false)
    setPaused(false)
    setCaptureStopped(false)
    setActiveView(mode === "validation" ? "validation" : "newVisit")
  }

  return (
    <main className="fixed inset-0 z-[60] flex bg-[#F5F4F0] text-[#101725]">
      <aside className="hidden w-[284px] shrink-0 flex-col bg-[#081D36] text-[#EAF0F8] lg:flex">
        <div className="px-8 py-8">
          <div className="font-serif text-4xl text-[#D1B464]">Aurion</div>
          <div className="mt-1 text-xs uppercase tracking-[0.35em] text-[#A9B8CC]">
            Clinical AI
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-5">
          {navItems.map((item) => {
            const Icon = item.icon
            const active = activeView === item.view
            return (
              <button
                key={item.view}
                type="button"
                onClick={() => setActiveView(item.view)}
                className={cn(
                  "flex h-13 w-full items-center gap-4 rounded-md px-4 text-left text-[15px] transition-colors",
                  active
                    ? "bg-[#203B5D] text-white shadow-[inset_4px_0_0_#D1B464]"
                    : "text-[#B8C6D8] hover:bg-white/8 hover:text-white",
                )}
              >
                <Icon className={cn("size-5", active && "text-[#D1B464]")} />
                <span>{t.nav[item.key]}</span>
              </button>
            )
          })}
        </nav>

        <div className="space-y-4 border-t border-white/10 px-6 py-6">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-full bg-[#DCE6F4] text-sm font-semibold text-[#081D36]">
              MG
            </div>
            <div>
              <div className="text-sm font-medium">{t.clinician}</div>
              <div className="text-xs text-[#9DB0C7]">{t.role}</div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setActiveView("schedule")}
            className="flex items-center gap-3 text-sm text-[#B8C6D8] hover:text-white"
          >
            <LogOut className="size-4" />
            {t.nav.signOut}
          </button>
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-20 shrink-0 items-center justify-between border-b border-[#D9DDE3] bg-[#F8F8F6] px-4 md:px-8">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <div className="lg:hidden">
              <div className="font-serif text-2xl text-[#081D36]">Aurion</div>
            </div>
            <div className="hidden h-11 w-full max-w-xl items-center gap-3 rounded-md bg-[#EEF1F4] px-4 text-sm text-[#6A7280] md:flex">
              <Search className="size-4" />
              {t.common.search}
            </div>
          </div>
          <div className="flex items-center gap-2 md:gap-4">
            <Link
              href="/prototype"
              locale={locale === "en" ? "fr" : "en"}
              className="inline-flex h-10 items-center gap-2 rounded-md border border-[#D3D8E0] bg-white px-3 text-sm font-medium text-[#22344D] hover:bg-[#F0F3F7]"
            >
              <Languages className="size-4" />
              {locale === "en" ? "FR" : "EN"}
            </Link>
            <button className="grid size-10 place-items-center rounded-md text-[#52647C] hover:bg-[#EDEFF2]">
              <Bell className="size-5" />
            </button>
            <button className="grid size-10 place-items-center rounded-md text-[#52647C] hover:bg-[#EDEFF2]">
              <Settings className="size-5" />
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-auto">
          {activeView === "schedule" && (
            <ScheduleView
              t={t}
              visitRows={visitRows}
              selectedVisit={selectedVisit}
              onOpenVisit={openVisit}
            />
          )}
          {activeView === "patients" && (
            <PatientsView t={t} onAddVisit={() => setActiveView("newVisit")} />
          )}
          {activeView === "newVisit" && (
            <NewVisitView
              t={t}
              visit={selectedVisit}
              template={selectedTemplate}
              consent={consent}
              setConsent={setConsent}
              onSelectTemplate={() => setActiveView("templates")}
              onStart={() => {
                setCaptureStopped(false)
                setActiveView("capture")
              }}
            />
          )}
          {activeView === "capture" && (
            <CaptureView
              t={t}
              note={note}
              visit={selectedVisit}
              paused={paused}
              setPaused={setPaused}
              stopped={captureStopped}
              onStopRecording={() => {
                setPaused(true)
                setCaptureStopped(true)
              }}
              onContinue={() => {
                setApproved(false)
                setActiveView("validation")
              }}
            />
          )}
          {activeView === "validation" && (
            <ValidationView
              t={t}
              note={note}
              visit={selectedVisit}
              approved={approved}
              onApprove={() => setApproved(true)}
              onReturn={() => setActiveView("schedule")}
            />
          )}
          {activeView === "templates" && (
            <TemplatesView
              t={t}
              selectedTemplate={selectedTemplate}
              onUse={(template) => {
                setSelectedTemplate(template)
                setActiveView("newVisit")
              }}
            />
          )}
          {activeView === "profile" && (
            <ProfileView
              t={t}
              locale={locale}
              profileType={profileType}
              setProfileType={setProfileType}
            />
          )}
        </div>
      </section>
    </main>
  )
}

function StatusPill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded bg-[#EAE1C8] px-2.5 py-1 text-xs font-medium uppercase tracking-[0.12em] text-[#5F4D1D]">
      {children}
    </span>
  )
}

function ActionButton({
  children,
  onClick,
  disabled,
  variant = "primary",
}: {
  children: React.ReactNode
  onClick?: () => void
  disabled?: boolean
  variant?: "primary" | "secondary"
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex h-11 items-center justify-center gap-2 rounded-md px-5 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-45",
        variant === "primary"
          ? "bg-[#081D36] text-white hover:bg-[#143255]"
          : "border border-[#C8CED6] bg-white text-[#17243A] hover:bg-[#F1F3F5]",
      )}
    >
      {children}
    </button>
  )
}

function ScheduleView({
  t,
  visitRows,
  selectedVisit,
  onOpenVisit,
}: {
  t: typeof copy.en | typeof copy.fr
  visitRows: Visit[]
  selectedVisit: Visit
  onOpenVisit: (visit: Visit, mode?: "setup" | "validation") => void
}) {
  const [selectedProvider, setSelectedProvider] = useState("my")
  const providers = [
    { id: "my", label: t.schedule.myCalendar, role: "Default" },
    { id: "marie", label: "Dr. Marie Gdalevitch", role: "Doctor" },
    { id: "perry", label: "Dr. Perry Gdalevitch", role: "Doctor" },
  ]

  return (
    <div className="grid gap-6 p-5 md:p-8 xl:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="rounded-md border border-[#D4D9E1] bg-white p-4">
        <h2 className="px-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
          {t.schedule.providers}
        </h2>
        <div className="mt-4 space-y-1">
          {providers.map((provider) => {
            const active = provider.id === selectedProvider
            return (
              <button
                key={provider.id}
                type="button"
                onClick={() => setSelectedProvider(provider.id)}
                className={cn(
                  "w-full rounded-md px-3 py-3 text-left transition-colors",
                  active
                    ? "bg-[#081D36] text-white"
                    : "text-[#17243A] hover:bg-[#F1F3F5]",
                )}
              >
                <span className="block text-sm font-semibold">{provider.label}</span>
                <span className={cn("mt-1 block text-xs", active ? "text-[#C7D3E2]" : "text-[#667385]")}>
                  {provider.role}
                </span>
              </button>
            )
          })}
        </div>
      </aside>

      <section>
        <div className="mb-8 flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <h1 className="font-serif text-5xl leading-tight text-[#08111F]">
              {t.schedule.title}
            </h1>
            <p className="mt-2 text-sm text-[#667385]">{t.schedule.date}</p>
          </div>
          <button
            type="button"
            className="inline-flex h-11 items-center gap-3 rounded-md border border-[#C8CED6] bg-white px-4 text-sm font-semibold text-[#17243A] hover:bg-[#F1F3F5]"
          >
            <CalendarDays className="size-4 text-[#244A77]" />
            <span>{t.schedule.selectDate}</span>
          </button>
        </div>

        <div className="mb-5 flex gap-8 border-b border-[#D2D7DF] text-lg">
          <button className="border-b-2 border-[#416A9C] pb-3 font-medium text-[#0A1D35]">
            {t.common.today}
          </button>
          <button className="pb-3 text-[#6A7280]">{t.common.upcoming}</button>
        </div>

        <div className="overflow-hidden rounded-md border border-[#D4D9E1] bg-white">
          {visitRows.map((visit) => {
            const selected = visit.id === selectedVisit.id
            const label =
              visit.status === "completed"
                ? t.common.reviewNote
                : visit.status === "recorded"
                  ? t.common.reviewNote
                : visit.status === "ready"
                  ? t.common.startVisit
                  : t.common.prepareVisit
            const mode =
              visit.status === "completed" || visit.status === "recorded" ? "validation" : "setup"
            return (
              <div
                key={visit.id}
                className={cn(
                  "grid gap-4 border-b border-[#E3E6EA] p-5 last:border-0 md:grid-cols-[110px_1fr_160px]",
                  selected && "bg-[#F7F4EA]",
                )}
              >
                <div className="font-medium text-[#0A1D35]">{visit.time}</div>
                <div>
                  <div className="flex flex-wrap items-center gap-3">
                    <h2 className="text-xl font-semibold text-[#101725]">
                      {visit.visitType}
                    </h2>
                    <StatusPill>{t.common[visit.status]}</StatusPill>
                  </div>
                  <p className="mt-1 text-sm text-[#667385]">
                    {visit.patient} · {visit.context}
                  </p>
                  {(visit.status === "recorded" || visit.tags || visit.seenBy) && (
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      {visit.tags?.map((tag, index) => (
                        <span
                          key={tag}
                          className={cn(
                            "rounded border px-2.5 py-1 text-xs font-semibold",
                            index === 0
                              ? "border-[#BFD4E6] bg-[#EFF6FB] text-[#245B82]"
                              : "border-[#C5D8C8] bg-[#F0F7F1] text-[#2F6C3C]",
                          )}
                        >
                          {tag}
                        </span>
                      ))}
                      {visit.seenBy && (
                        <span className="text-xs font-medium text-[#667385]">
                          {visit.seenBy}
                        </span>
                      )}
                    </div>
                  )}
                </div>
                <ActionButton onClick={() => onOpenVisit(visit, mode)}>
                  {label}
                  <ChevronRight className="size-4" />
                </ActionButton>
              </div>
            )
          })}
        </div>
      </section>

      <aside className="hidden">
        <div className="rounded-md border border-[#D4D9E1] bg-white p-6">
          <h2 className="font-serif text-3xl text-[#08111F]">
            {t.schedule.helperTitle}
          </h2>
          <div className="mt-5 space-y-4">
            {[
              [t.schedule.nextPatient, `${selectedVisit.time} · ${selectedVisit.patient}`],
              [t.schedule.pendingNotes, t.schedule.recordedReady],
              [t.setup.template, t.schedule.template],
              [t.validation.audit, t.schedule.consent],
            ].map(([label, value]) => (
              <div key={label} className="border-b border-[#ECEFF2] pb-4 last:border-0">
                <div className="text-xs uppercase tracking-[0.18em] text-[#7A8494]">
                  {label}
                </div>
                <div className="mt-1 text-sm font-medium text-[#17243A]">{value}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-md border border-[#D4D9E1] bg-[#081D36] p-6 text-white">
          <ShieldCheck className="size-8 text-[#D1B464]" />
          <p className="mt-4 text-sm text-[#C7D3E2]">{t.schedule.captureReady}</p>
          <p className="mt-2 text-sm text-[#C7D3E2]">{t.schedule.privacy}</p>
        </div>
      </aside>
    </div>
  )
}

function NewVisitView({
  t,
  visit,
  template,
  consent,
  setConsent,
  onSelectTemplate,
  onStart,
}: {
  t: typeof copy.en | typeof copy.fr
  visit: Visit
  template: (typeof templates)[number]
  consent: boolean
  setConsent: (value: boolean) => void
  onSelectTemplate: () => void
  onStart: () => void
}) {
  const [visitType, setVisitType] = useState(visit.visitType)
  const [context, setContext] = useState(visit.context)

  return (
    <div className="mx-auto max-w-2xl p-5 md:p-10">
      <div className="mb-8 text-center">
        <h1 className="font-serif text-5xl text-[#08111F]">{t.setup.title}</h1>
        <p className="mt-3 text-base leading-relaxed text-[#667385]">{t.setup.subtitle}</p>
      </div>

      <div className="rounded-md border border-[#D4D9E1] bg-white p-6 shadow-sm">
        <p className="text-sm text-[#667385]">
          <span className="font-semibold text-[#17243A]">{t.setup.patientLabel}:</span>{" "}
          {visit.patient} · {visit.id.toUpperCase()}
        </p>

        <div className="mt-6 space-y-5">
          <label className="block space-y-2">
            <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
              {t.setup.visitType}
            </span>
            <input
              value={visitType}
              onChange={(e) => setVisitType(e.target.value)}
              className="h-12 w-full rounded-md border border-[#C8CED6] bg-[#F8F8F6] px-4 text-sm font-medium text-[#17243A] outline-none transition-colors focus:border-[#081D36] focus:bg-white"
            />
          </label>
          <label className="block space-y-2">
            <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
              {t.setup.context}
            </span>
            <textarea
              value={context}
              onChange={(e) => setContext(e.target.value)}
              rows={4}
              className="w-full resize-y rounded-md border border-[#C8CED6] bg-[#F8F8F6] px-4 py-3 text-sm leading-6 text-[#17243A] outline-none transition-colors focus:border-[#081D36] focus:bg-white"
            />
          </label>
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-[#ECEFF2] pt-5">
          <p className="text-sm text-[#667385]">
            <span className="font-medium text-[#17243A]">{template.name}</span>
            <span className="mx-2 text-[#C8CED6]">·</span>
            <span>{t.setup.templateHint}</span>
          </p>
          <button
            type="button"
            onClick={onSelectTemplate}
            className="text-sm font-semibold text-[#244A77] hover:text-[#081D36]"
          >
            {t.setup.selectTemplate}
          </button>
        </div>

        <label className="mt-6 flex items-center gap-3 rounded-md border border-[#D8C992] bg-[#FBF7EA] p-4 text-sm font-medium text-[#17243A]">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
            className="size-4 accent-[#081D36]"
          />
          {t.common.confirmConsent}
        </label>

        <div className="mt-6 flex justify-end">
          <ActionButton disabled={!consent} onClick={onStart}>
            <Play className="size-4" />
            {t.common.startCapture}
          </ActionButton>
        </div>
      </div>
    </div>
  )
}

function CaptureView({
  t,
  note,
  visit,
  paused,
  setPaused,
  stopped,
  onStopRecording,
  onContinue,
}: {
  t: typeof copy.en | typeof copy.fr
  note: typeof localizedVisitText.en | typeof localizedVisitText.fr
  visit: Visit
  paused: boolean
  setPaused: (value: boolean) => void
  stopped: boolean
  onStopRecording: () => void
  onContinue: () => void
}) {
  return (
    <div className="p-5 md:p-8">
      <section className="min-h-[calc(100vh-128px)] rounded-md border border-[#D4D9E1] bg-white p-6">
        <div className="flex flex-col justify-between gap-4 border-b border-[#E4E7EC] pb-6 md:flex-row md:items-center">
          <div>
            <h1 className="font-serif text-5xl text-[#08111F]">{t.capture.title}</h1>
            <p className="mt-2 text-[#667385]">{t.capture.subtitle}</p>
          </div>
          <div className="rounded-md bg-[#081D36] px-5 py-3 text-white">
            <div className="text-xs uppercase tracking-[0.18em] text-[#A9B8CC]">
              {t.capture.elapsed}
            </div>
            <div className="font-mono text-2xl">00:07:42</div>
          </div>
        </div>

        <div className="mt-6 grid min-h-[520px] gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(260px,1fr)]">
          <div className="flex min-h-0 flex-col rounded-md border border-[#D4D9E1] bg-[#F8F8F6] p-5">
            <div className="flex items-center justify-between gap-4 border-b border-[#E1E5EA] pb-4">
              <div>
                <div className="text-xs uppercase tracking-[0.18em] text-[#6D7787]">
                  {visit.patient} · {visit.visitType}
                </div>
                <h2 className="mt-2 text-2xl font-semibold text-[#08111F]">
                  {t.capture.transcript}
                </h2>
              </div>
              <span className={cn("size-3 rounded-full", paused ? "bg-[#AAB3C0]" : "capture-pulse bg-emerald-500")} />
            </div>
            <div className="min-h-0 flex-1 overflow-auto pt-5">
              <div className="space-y-5 text-base leading-8 text-[#17243A]">
                <TranscriptLine time="00:42" text={note.transcript1} />
                <TranscriptLine time="03:15" text={note.transcript2} />
                <TranscriptLine time="05:50" text={note.transcript3} />
              </div>
            </div>
          </div>

          <div className="flex min-h-0 flex-col gap-5">
            <CaptureSignal icon={Mic} title={t.capture.audio} active={!paused} />

            {stopped && (
              <label className="flex flex-col rounded-md border border-[#D4D9E1] bg-[#F6F7F8] p-4">
                <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
                  {t.capture.changes}
                </span>
                <textarea
                  className="mt-3 min-h-[150px] resize-none rounded-md border border-[#C8CED6] bg-white p-3 text-sm leading-6 text-[#17243A] outline-none transition-colors placeholder:text-[#8994A4] focus:border-[#081D36]"
                  placeholder={t.capture.changesPlaceholder}
                />
              </label>
            )}

            <div className="flex flex-wrap justify-end gap-3">
              {!stopped && (
                <ActionButton variant="secondary" onClick={() => setPaused(!paused)}>
                  <Pause className="size-4" />
                  {t.capture.pause}
                </ActionButton>
              )}
              <ActionButton onClick={stopped ? onContinue : onStopRecording}>
                {stopped ? (
                  <CheckCircle2 className="size-4" />
                ) : (
                  <Square className="size-4" />
                )}
                {stopped ? t.common.continue : t.capture.stop}
              </ActionButton>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

function CaptureSignal({
  icon: Icon,
  title,
  active,
}: {
  icon: typeof Mic
  title: string
  active: boolean
}) {
  return (
    <div className="rounded-md border border-[#D4D9E1] p-5">
      <div className="flex items-center justify-between">
        <Icon className="size-6 text-[#244A77]" />
        <span className={cn("size-3 rounded-full", active ? "capture-pulse bg-emerald-500" : "bg-[#AAB3C0]")} />
      </div>
      <div className="mt-4 font-medium text-[#17243A]">{title}</div>
    </div>
  )
}

function TranscriptLine({ time, text }: { time: string; text: string }) {
  return (
    <div className="grid grid-cols-[58px_1fr] gap-4">
      <span className="font-mono text-xs text-[#6D7787]">{time}</span>
      <span>{text}</span>
    </div>
  )
}

function SeenByTimeline({
  selected,
  onSelect,
  title = "Seen by",
}: {
  selected: string
  onSelect: (value: string) => void
  title?: string
}) {
  return (
    <aside className="rounded-md border border-[#D4D9E1] bg-white p-4">
      <h2 className="px-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
        {title}
      </h2>
      <div className="mt-5">
        {encounterHistory.map((encounter, index) => {
          const active = selected === encounter.id
          return (
            <button
              key={encounter.id}
              type="button"
              onClick={() => onSelect(encounter.id)}
              className="grid w-full grid-cols-[22px_1fr] gap-3 text-left"
            >
              <span className="flex flex-col items-center">
                <span className={cn("mt-1 size-3 rounded-full border-2", active ? "border-[#2A6F9F] bg-[#2A6F9F]" : "border-[#9BA7B6] bg-white")} />
                {index < encounterHistory.length - 1 && <span className="h-16 w-px bg-[#CBD3DD]" />}
              </span>
              <span className={cn("mb-3 rounded-md p-3 transition-colors", active ? "bg-[#081D36] text-white" : "text-[#17243A] hover:bg-[#F1F3F5]")}>
                <span className="block font-mono text-xs">{encounter.time}</span>
                <span className="mt-1 block text-sm font-semibold">{encounter.role}: {encounter.name}</span>
                <span className={cn("mt-1 inline-block rounded px-2 py-0.5 text-[11px] font-semibold", active ? "bg-white/12 text-[#D7E3F2]" : "bg-[#EEF3F8] text-[#516176]")}>
                  {encounter.status}
                </span>
              </span>
            </button>
          )
        })}
      </div>
    </aside>
  )
}

function PatientVisitsMenu({
  selected,
  onSelect,
}: {
  selected: string
  onSelect: (value: string) => void
}) {
  const visitsMenu = [
    {
      id: "nurse",
      date: "Today",
      title: "Triage",
      provider: "Inf: Sarah Jenkins",
      status: "Signed",
    },
    {
      id: "resident",
      date: "Today",
      title: "Resident assessment",
      provider: "Resident: Alex Chen",
      status: "Signed",
    },
    {
      id: "doctor",
      date: "Today",
      title: "Doctor visit",
      provider: "Doctor: Dr. Marie Gdalevitch",
      status: "Draft",
    },
    {
      id: "prior",
      date: "Apr 12",
      title: "Prior follow-up",
      provider: "Doctor: Dr. Perry Gdalevitch",
      status: "Signed",
    },
  ]

  return (
    <aside className="rounded-md border border-[#D4D9E1] bg-white p-4">
      <h2 className="px-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
        Patient visits
      </h2>
      <div className="mt-4 space-y-2">
        {visitsMenu.map((visit) => {
          const active = selected === visit.id
          return (
            <button
              key={visit.id}
              type="button"
              onClick={() => onSelect(visit.id === "prior" ? "doctor" : visit.id)}
              className={cn(
                "w-full rounded-md border p-3 text-left transition-colors",
                active
                  ? "border-[#081D36] bg-[#081D36] text-white"
                  : "border-[#D4D9E1] bg-[#F8F8F6] text-[#17243A] hover:bg-white",
              )}
            >
              <span className={cn("block text-xs font-semibold uppercase tracking-[0.14em]", active ? "text-[#C7D3E2]" : "text-[#667385]")}>
                {visit.date}
              </span>
              <span className="mt-1 block text-sm font-semibold">{visit.title}</span>
              <span className={cn("mt-1 block text-xs", active ? "text-[#D7E3F2]" : "text-[#667385]")}>
                {visit.provider}
              </span>
              <span className={cn("mt-2 inline-block rounded px-2 py-0.5 text-[11px] font-semibold", active ? "bg-white/12 text-[#D7E3F2]" : "bg-[#EEF3F8] text-[#516176]")}>
                {visit.status}
              </span>
            </button>
          )
        })}
      </div>
    </aside>
  )
}

const EditableSoapNote = memo(function EditableSoapNote({
  value,
  onChange,
}: {
  value: string
  onChange: (next: string) => void
}) {
  return (
    <article className="overflow-hidden rounded-md border border-[#D4D9E1] bg-white p-4 shadow-sm md:p-6">
      <label className="sr-only" htmlFor="validation-soap-note">
        Clinical note
      </label>
      <textarea
        id="validation-soap-note"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        spellCheck
        className={cn(
          "min-h-[min(20rem,calc(100vh-28rem))] w-full resize-y rounded-md border border-[#E3E6EA] bg-[#FAFAF8] p-5 font-sans text-sm leading-7 text-[#243248] outline-none transition-colors",
          "focus:border-[#BFD4E6] focus:bg-white focus:ring-1 focus:ring-[#BFD4E6]",
        )}
      />
    </article>
  )
})

type ChatMsg = { id: string; role: "user" | "assistant"; content: string }

function NoteEditChatPanel({
  t,
  messages,
  input,
  onInputChange,
  onSend,
}: {
  t: typeof copy.en | typeof copy.fr
  messages: ChatMsg[]
  input: string
  onInputChange: (value: string) => void
  onSend: () => void
}) {
  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    onSend()
  }

  return (
    <section
      aria-label={t.validation.chatTitle}
      className="flex max-h-[min(22rem,42vh)] min-h-[14rem] flex-col overflow-hidden rounded-md border border-[#D4D9E1] bg-white shadow-sm"
    >
      <header className="border-b border-[#ECEFF2] px-4 py-3">
        <h3 className="text-sm font-semibold text-[#08111F]">{t.validation.chatTitle}</h3>
        <p className="mt-1 text-xs leading-relaxed text-[#667385]">{t.validation.chatHint}</p>
      </header>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {messages.map((m) => (
          <div
            key={m.id}
            className={cn(
              "max-w-[95%] rounded-lg px-3 py-2 text-sm leading-relaxed",
              m.role === "user"
                ? "ml-auto bg-[#EEF3F8] text-[#17243A]"
                : "mr-auto border border-[#E3E6EA] bg-[#FAFAF8] text-[#243248]",
            )}
          >
            {m.content}
          </div>
        ))}
      </div>
      <form onSubmit={handleSubmit} className="flex gap-2 border-t border-[#ECEFF2] p-3">
        <label className="sr-only" htmlFor="note-edit-chat-input">
          {t.validation.chatPlaceholder}
        </label>
        <textarea
          id="note-edit-chat-input"
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              onSend()
            }
          }}
          rows={2}
          placeholder={t.validation.chatPlaceholder}
          className="min-h-[44px] flex-1 resize-none rounded-md border border-[#C8CED6] bg-[#F8F8F6] px-3 py-2 text-sm text-[#17243A] outline-none placeholder:text-[#8994A4] focus:border-[#081D36] focus:bg-white"
        />
        <button
          type="submit"
          className="grid size-11 shrink-0 place-items-center self-end rounded-md bg-[#081D36] text-white hover:bg-[#173B66]"
          aria-label={t.validation.chatSend}
        >
          <Send className="size-4" />
        </button>
      </form>
    </section>
  )
}

function EvidenceDetail({
  evidenceId,
}: {
  evidenceId: keyof typeof evidenceLibrary
}) {
  const evidence = evidenceLibrary[evidenceId]

  return (
    <div className="rounded-md border border-[#D4D9E1] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-[#08111F]">{evidence.title}</h3>
          <p className="mt-1 text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
            {evidence.kind} · {evidence.source}
          </p>
        </div>
      </div>
      <div className="mt-4 space-y-3">
        {evidence.lines.map((line, index) => (
          <div
            key={line}
            className={cn(
              "rounded-md border p-3 text-sm leading-6 text-[#243248]",
              evidence.kind === "Video frame"
                ? "border-[#D6C7A1] bg-[#FBF7EA]"
                : evidence.kind === "Screen frame"
                  ? "border-[#BFD4E6] bg-[#EFF6FB]"
                  : "border-[#D4D9E1] bg-[#F6F7F8]",
            )}
          >
            {evidence.kind !== "Audio transcript" &&
              "media" in evidence &&
              evidence.media[index] && (
              <figure className="mb-3 overflow-hidden rounded-md border border-[#CBD3DD] bg-[#081D36]">
                <img
                  src={evidence.media[index].src}
                  alt={evidence.media[index].alt}
                  className="h-auto max-h-56 w-full object-contain"
                  loading="lazy"
                />
              </figure>
            )}
            {line}
          </div>
        ))}
      </div>
    </div>
  )
}

function ValidationView({
  t,
  note: _note,
  visit: _visit,
  approved,
  onApprove,
  onReturn,
}: {
  t: typeof copy.en | typeof copy.fr
  note: typeof localizedVisitText.en | typeof localizedVisitText.fr
  visit: Visit
  approved: boolean
  onApprove: () => void
  onReturn: () => void
}) {
  const [selectedEncounter, setSelectedEncounter] = useState("doctor")
  const [isCombining, setIsCombining] = useState(false)
  const [mergedReady, setMergedReady] = useState(false)
  const [noteText, setNoteText] = useState(buildInitialSoapNoteText)
  const [chatInput, setChatInput] = useState("")
  const chatId = useRef(0)
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>(() => [
    { id: "intro", role: "assistant", content: t.validation.chatAssistantIntro },
  ])
  const activeEncounter = encounterHistory.find((item) => item.id === selectedEncounter) ?? encounterHistory[0]

  function combineNotes() {
    setMergedReady(false)
    setIsCombining(true)
    window.setTimeout(() => {
      setIsCombining(false)
      setMergedReady(true)
    }, 900)
  }

  function sendChatMessage() {
    const text = chatInput.trim()
    if (!text) return
    setChatInput("")
    const { reply, nextNote } = mockApplyNoteEdit(noteText, text)
    setNoteText(nextNote)
    const u = `u-${++chatId.current}`
    const a = `a-${++chatId.current}`
    setChatMessages((prev) => [
      ...prev,
      { id: u, role: "user", content: text },
      { id: a, role: "assistant", content: reply },
    ])
  }

  const showChat = !isCombining

  return (
    <div className="grid gap-6 p-4 md:p-8 xl:grid-cols-[240px_minmax(0,1fr)]">
      <SeenByTimeline selected={selectedEncounter} onSelect={setSelectedEncounter} />

      <section className="min-w-0">
        <div className="mb-5">
          <h1 className="font-serif text-5xl text-[#08111F]">{t.validation.title}</h1>
          <p className="mt-2 text-[#667385]">{t.validation.subtitle}</p>
        </div>
        <div className="mb-5 rounded-md border border-[#D4D9E1] bg-[#F6F7F8] p-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
            {activeEncounter.role}: {activeEncounter.name}
          </div>
          <p className="mt-2 text-sm leading-6 text-[#17243A]">{activeEncounter.summary}</p>
        </div>
        {isCombining ? (
          <div className="grid min-h-[520px] place-items-center rounded-md border border-[#D4D9E1] bg-white p-8 text-center shadow-sm">
            <div>
              <div className="mx-auto grid size-14 place-items-center rounded-full bg-[#081D36] text-[#D1B464]">
                <Stethoscope className="size-7" />
              </div>
              <h2 className="mt-5 font-serif text-3xl text-[#08111F]">Combining notes</h2>
              <p className="mt-2 text-sm text-[#667385]">Merging nurse, resident, and physician documentation into one note.</p>
            </div>
          </div>
        ) : mergedReady ? (
          <div className="rounded-md border border-[#D4D9E1] bg-white p-8 shadow-sm">
            <div className="flex items-center justify-between gap-4">
              <h2 className="font-serif text-4xl text-[#08111F]">Merged note preview</h2>
              <div className="flex gap-2">
                <button type="button" className="grid size-10 place-items-center rounded-md border border-[#C8CED6] text-[#17243A] hover:bg-[#F1F3F5]" aria-label={t.validation.copy}>
                  <Copy className="size-4" />
                </button>
                <button type="button" className="grid size-10 place-items-center rounded-md border border-[#C8CED6] text-[#17243A] hover:bg-[#F1F3F5]" aria-label={t.validation.export}>
                  <Download className="size-4" />
                </button>
              </div>
            </div>
            <pre className="mt-6 whitespace-pre-wrap rounded-md border border-[#D4D9E1] bg-[#F8F8F6] p-5 text-sm leading-7 text-[#17243A]">
              {mergedNotePreview}
            </pre>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <EditableSoapNote value={noteText} onChange={setNoteText} />
            {showChat && (
              <NoteEditChatPanel
                t={t}
                messages={chatMessages}
                input={chatInput}
                onInputChange={setChatInput}
                onSend={sendChatMessage}
              />
            )}
          </div>
        )}
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <ActionButton variant="secondary">
            <Copy className="size-4" />
            {t.validation.copy}
          </ActionButton>
          <ActionButton variant="secondary">
            <Download className="size-4" />
            {t.validation.export}
          </ActionButton>
          <ActionButton variant="secondary" onClick={combineNotes}>
            <ClipboardCheck className="size-4" />
            {t.schedule.combineNotes}
          </ActionButton>
          <ActionButton onClick={approved ? onReturn : onApprove}>
            <CheckCircle2 className="size-4" />
            {approved ? t.common.completed : t.validation.approve}
          </ActionButton>
        </div>
      </section>
    </div>
  )
}

function EvidenceCard({
  title,
  source,
  lines,
}: {
  title: string
  source: string
  lines: string[]
}) {
  return (
    <div className="rounded-md border border-[#D4D9E1] bg-white p-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-[#08111F]">{title}</h3>
        <span className="text-xs uppercase tracking-[0.18em] text-[#6D7787]">{source}</span>
      </div>
      <div className="mt-4 space-y-3">
        {lines.map((line) => (
          <p key={line} className="rounded bg-[#F6F7F8] p-3 text-sm leading-6 text-[#243248]">
            {line}
          </p>
        ))}
      </div>
    </div>
  )
}

function PatientsView({
  t,
  onAddVisit,
}: {
  t: typeof copy.en | typeof copy.fr
  onAddVisit: () => void
}) {
  const [selectedFile, setSelectedFile] = useState(patientFiles[0])
  const [selectedEncounter, setSelectedEncounter] = useState("nurse")
  const [chartOpen, setChartOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [showSeenBy, setShowSeenBy] = useState(true)
  const [showContext, setShowContext] = useState(true)
  const [chartTab, setChartTab] = useState<"chart" | "review">("chart")
  const activeEncounter = encounterHistory.find((item) => item.id === selectedEncounter) ?? encounterHistory[0]
  const filteredFiles = patientFiles.filter((file) =>
    `${file.title} ${file.subtitle}`.toLowerCase().includes(query.toLowerCase()),
  )

  function openChart(file: (typeof patientFiles)[number]) {
    setSelectedFile(file)
    setChartOpen(true)
  }

  if (!chartOpen) {
    return (
      <div className="p-5 md:p-8">
        <div className="mb-6">
          <h1 className="font-serif text-5xl text-[#08111F]">{t.patients.title}</h1>
          <p className="mt-2 text-sm text-[#667385]">{t.patients.subtitle}</p>
        </div>
        <div className="rounded-md border border-[#D4D9E1] bg-white p-5">
          <label className="flex h-12 items-center gap-3 rounded-md border border-[#C8CED6] bg-[#F8F8F6] px-4 text-sm text-[#667385]">
            <Search className="size-4" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search patient files"
              className="h-full flex-1 bg-transparent text-[#17243A] outline-none placeholder:text-[#667385]"
            />
          </label>
          <div className="mt-8">
            <h2 className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
              Recently viewed
            </h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {(query ? filteredFiles : patientFiles.slice(0, 3)).map((file) => (
                <button
                  key={file.id}
                  type="button"
                  onClick={() => openChart(file)}
                  className="rounded-md border border-[#D4D9E1] bg-[#F8F8F6] p-4 text-left transition-colors hover:border-[#081D36] hover:bg-white"
                >
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="font-semibold text-[#17243A]">{file.title}</h3>
                    <StatusPill>{file.status}</StatusPill>
                  </div>
                  <p className="mt-2 text-sm text-[#667385]">{file.subtitle}</p>
                  <p className="mt-4 text-xs text-[#667385]">{file.encounters}</p>
                  <span className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-[#244A77]">
                    Open chart
                    <ChevronRight className="size-4" />
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-5 md:p-8">
      <div className="mb-5 flex flex-col justify-between gap-4 md:flex-row md:items-center">
        <div>
          <button
            type="button"
            onClick={() => setChartOpen(false)}
            className="text-sm font-semibold text-[#244A77] hover:text-[#081D36]"
          >
            Patient files
          </button>
          <h1 className="mt-2 font-serif text-5xl text-[#08111F]">{selectedFile.title}</h1>
          <p className="mt-1 text-sm text-[#667385]">{selectedFile.subtitle}</p>
          <div className="mt-5 flex gap-2 border-b border-[#D2D7DF]">
            <button
              type="button"
              onClick={() => setChartTab("chart")}
              className={cn("pb-3 text-sm font-semibold", chartTab === "chart" ? "border-b-2 border-[#416A9C] text-[#0A1D35]" : "text-[#6A7280]")}
            >
              Chart
            </button>
            <button
              type="button"
              onClick={() => setChartTab("review")}
              className={cn("pb-3 text-sm font-semibold", chartTab === "review" ? "border-b-2 border-[#416A9C] text-[#0A1D35]" : "text-[#6A7280]")}
            >
              Review & Validate
            </button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ActionButton variant="secondary" onClick={() => {
            setShowSeenBy(false)
            setShowContext(false)
          }}>
            Collapse all
          </ActionButton>
          <ActionButton onClick={onAddVisit}>
            <Play className="size-4" />
            {t.common.startVisit}
          </ActionButton>
        </div>
      </div>

      {chartTab === "review" ? (
        <ValidationView
          t={t}
          note={localizedVisitText.en}
          visit={visits[0]}
          approved={false}
          onApprove={() => undefined}
          onReturn={() => setChartTab("chart")}
        />
      ) : (

      <div className="grid gap-5 xl:grid-cols-[minmax(0,260px)_minmax(0,1fr)_minmax(0,320px)]">
        {showSeenBy ? (
          <div>
            <div className="mb-2 flex justify-end">
              <button type="button" onClick={() => setShowSeenBy(false)} className="text-xs font-semibold text-[#244A77]">
                Collapse
              </button>
            </div>
            <PatientVisitsMenu
              selected={selectedEncounter}
              onSelect={setSelectedEncounter}
            />
          </div>
        ) : (
          <button type="button" onClick={() => setShowSeenBy(true)} className="h-11 rounded-md border border-[#C8CED6] bg-white text-sm font-semibold text-[#244A77]">
            Patient visits
          </button>
        )}

        <main className="rounded-md border border-[#D4D9E1] bg-white p-6">
          <div className="mb-5 flex items-center justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
                {activeEncounter.role}: {activeEncounter.name}
              </div>
              <h2 className="mt-2 font-serif text-3xl text-[#08111F]">Provider note</h2>
            </div>
            <StatusPill>{activeEncounter.status}</StatusPill>
          </div>
          <pre className="whitespace-pre-wrap rounded-md border border-[#D4D9E1] bg-[#F8F8F6] p-5 text-sm leading-7 text-[#17243A]">
            {activeEncounter.note}
          </pre>
        </main>

        {showContext ? (
          <aside className="space-y-4">
            <div className="flex justify-end">
              <button type="button" onClick={() => setShowContext(false)} className="text-xs font-semibold text-[#244A77]">
                Collapse
              </button>
            </div>
            <div className="rounded-md border border-[#D4D9E1] bg-white p-4">
              <h2 className="text-lg font-semibold text-[#08111F]">Appointments</h2>
              <div className="mt-4 space-y-3 text-sm">
                <div className="rounded bg-[#F6F7F8] p-3">
                  <div className="font-semibold text-[#17243A]">Today · 11:40 AM</div>
                  <div className="mt-1 text-[#667385]">Follow-up available</div>
                  <button type="button" onClick={onAddVisit} className="mt-3 rounded bg-[#081D36] px-3 py-1.5 text-xs font-semibold text-white">
                    Record session
                  </button>
                </div>
                <div className="rounded bg-[#F6F7F8] p-3 text-[#667385]">
                  Upcoming · May 12 · Post-op review
                </div>
              </div>
            </div>
            <div className="rounded-md border border-[#D4D9E1] bg-white p-4">
              <h2 className="text-lg font-semibold text-[#08111F]">Uploaded documents</h2>
              <div className="mt-4 space-y-2 text-sm text-[#17243A]">
                <div className="rounded bg-[#F6F7F8] p-3">MRI summary.pdf</div>
                <div className="rounded bg-[#F6F7F8] p-3">Referral note.docx</div>
              </div>
              <h3 className="mt-5 text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
                Typed context
              </h3>
              <textarea
                className="mt-3 min-h-[120px] w-full resize-none rounded-md border border-[#C8CED6] bg-[#F8F8F6] p-3 text-sm leading-6 text-[#17243A] outline-none focus:border-[#081D36] focus:bg-white"
                defaultValue="Patient prefers conservative care. Compare current symptoms against prior MRI and triage note."
              />
            </div>
          </aside>
        ) : (
          <button type="button" onClick={() => setShowContext(true)} className="h-11 rounded-md border border-[#C8CED6] bg-white text-sm font-semibold text-[#244A77]">
            Context
          </button>
        )}
      </div>
      )}
    </div>
  )
}

function TemplatesView({
  t,
  selectedTemplate,
  onUse,
}: {
  t: typeof copy.en | typeof copy.fr
  selectedTemplate: (typeof templates)[number]
  onUse: (template: (typeof templates)[number]) => void
}) {
  const [preview, setPreview] = useState(selectedTemplate)
  const [previewOpen, setPreviewOpen] = useState(false)
  const templateBody = `${preview.name}

Type
${preview.type}

Specialty
${preview.specialty}

Sections
${preview.sections.map((section) => `- ${section}`).join("\n")}

Documentation instructions
Use concise clinical language. Preserve clinician judgment. Include only findings supported by transcript, exam capture, imaging, or screen evidence. Keep assessment and plan editable before approval.`

  return (
    <div className="p-5 md:p-8">
      <section>
        <div className="mb-6">
          <div>
            <h1 className="font-serif text-5xl text-[#08111F]">{t.templates.title}</h1>
            <p className="mt-2 text-[#667385]">{t.templates.subtitle}</p>
          </div>
        </div>

        <div className="rounded-md border border-[#D4D9E1] bg-white p-5">
          <h2 className="text-xl font-semibold text-[#08111F]">Note templates</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {templates.map((template) => (
              <div
                key={template.name}
                className={cn(
                  "rounded-md border bg-white p-3 transition-colors hover:bg-[#F8F8F6]",
                  previewOpen && preview.name === template.name ? "border-[#081D36]" : "border-[#D4D9E1]",
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-semibold text-[#08111F]">{template.name}</h3>
                  <button
                    type="button"
                    onClick={() => {
                      setPreview(template)
                      setPreviewOpen(true)
                    }}
                    className="grid size-8 shrink-0 place-items-center rounded-md border border-[#C8CED6] text-[#17243A] hover:bg-white"
                    aria-label={`Preview ${template.name}`}
                  >
                    <Eye className="size-4" />
                  </button>
                </div>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <p className="text-xs text-[#667385]">{template.specialty}</p>
                  <span className="shrink-0 rounded bg-[#EEF3F8] px-2 py-1 text-[11px] font-semibold text-[#516176]">
                    {template.type}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-8 rounded-md border border-[#D4D9E1] bg-white p-5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-xl font-semibold text-[#08111F]">Visit type templates</h2>
            <button
              type="button"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-[#C8CED6] px-3 text-sm font-semibold text-[#17243A] hover:bg-[#F1F3F5]"
            >
              <Plus className="size-4" />
              Add visit type
            </button>
          </div>
          <div className="mt-4 overflow-hidden rounded-md border border-[#D4D9E1]">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#F6F7F8] text-xs font-semibold uppercase tracking-[0.14em] text-[#6D7787]">
                <tr>
                  <th className="px-3 py-3">Visit type</th>
                  <th className="px-3 py-3">Note template</th>
                  <th className="px-3 py-3">Capture</th>
                  <th className="px-3 py-3 text-right">Preview</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E3E6EA] bg-white">
                {visitTypeTemplates.map((mapping) => {
                  const mappedTemplate = templates.find((template) => template.name === mapping.noteTemplate) ?? templates[0]

                  return (
                    <tr key={mapping.visitType}>
                      <td className="px-3 py-3 font-semibold text-[#17243A]">{mapping.visitType}</td>
                      <td className="px-3 py-3">
                        <select
                          defaultValue={mapping.noteTemplate}
                          className="h-9 w-full rounded-md border border-[#C8CED6] bg-white px-2 text-sm text-[#17243A] outline-none"
                        >
                          {templates.map((template) => (
                            <option key={template.name} value={template.name}>
                              {template.name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-3 text-[#667385]">{mapping.captureDefault}</td>
                      <td className="px-3 py-3">
                        <button
                          type="button"
                          onClick={() => {
                            setPreview(mappedTemplate)
                            setPreviewOpen(true)
                          }}
                          className="ml-auto grid size-8 place-items-center rounded-md border border-[#C8CED6] text-[#17243A] hover:bg-[#F1F3F5]"
                          aria-label={`Preview ${mapping.visitType}`}
                        >
                          <Eye className="size-4" />
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </section>
      {previewOpen && (
      <aside className="mt-6 rounded-md border border-[#D4D9E1] bg-white p-6">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
          <div>
            <h2 className="font-serif text-3xl text-[#08111F]">{t.templates.preview}</h2>
            <p className="mt-1 text-lg font-medium text-[#17243A]">{preview.name}</p>
          </div>
          <div className="flex gap-2">
            <button type="button" onClick={() => setPreviewOpen(false)} className="rounded-md border border-[#C8CED6] px-3 text-sm font-semibold text-[#17243A] hover:bg-[#F1F3F5]">
              Close
            </button>
            <button type="button" className="grid size-10 place-items-center rounded-md border border-[#C8CED6] text-[#17243A] hover:bg-[#F1F3F5]" aria-label="Copy template">
              <Copy className="size-4" />
            </button>
            <button type="button" className="grid size-10 place-items-center rounded-md border border-[#D8B9B9] text-[#8A2D2D] hover:bg-[#FBEEEE]" aria-label="Delete template">
              <Square className="size-4" />
            </button>
          </div>
        </div>
        <textarea
          className="mt-6 min-h-[560px] w-full resize-none rounded-md border border-[#C8CED6] bg-[#F8F8F6] p-5 text-sm leading-7 text-[#17243A] outline-none focus:border-[#081D36] focus:bg-white"
          defaultValue={templateBody}
          key={preview.name}
        />
        <div className="mt-5 flex justify-end">
          <ActionButton onClick={() => onUse(preview)}>
            <CheckCircle2 className="size-4" />
            {t.templates.use}
          </ActionButton>
        </div>
      </aside>
      )}
    </div>
  )
}

function ProfileView({
  t,
  locale,
  profileType,
  setProfileType,
}: {
  t: typeof copy.en | typeof copy.fr
  locale: AppLocale
  profileType: string
  setProfileType: (value: string) => void
}) {
  const [profileTab, setProfileTab] = useState<"profile" | "data" | "defaults">("profile")

  return (
    <div className="p-5 md:p-8">
      <div className="mb-8">
        <h1 className="font-serif text-5xl text-[#08111F]">{t.profile.title}</h1>
        <p className="mt-2 text-[#667385]">{t.profile.subtitle}</p>
      </div>
      <div className="mb-6 flex gap-8 border-b border-[#D2D7DF] text-lg">
        {[
          ["profile", "Profile"],
          ["data", "Data management"],
          ["defaults", "Defaults"],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setProfileTab(id as typeof profileTab)}
            className={cn(
              "pb-3 font-medium",
              profileTab === id ? "border-b-2 border-[#416A9C] text-[#0A1D35]" : "text-[#6A7280]",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className={cn("space-y-8 rounded-md border border-[#D4D9E1] bg-white p-6", profileTab !== "profile" && "hidden")}>
          <section>
            <h2 className="font-serif text-2xl text-[#173B66]">{t.profile.type}</h2>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <SettingsField label="Organization name" value="CREOQ / CLLC" />
              <SettingsField label="Specialty" value="Orthopedics" />
              <SettingsField label="Default language" value="English" />
            </div>
            <label className="mt-4 block max-w-md space-y-2">
              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">
                {t.profile.type}
              </span>
              <select
                value={profileType}
                onChange={(event) => setProfileType(event.target.value)}
                className="h-14 w-full rounded-md border border-[#C8CED6] bg-[#F8F8F6] px-4 text-sm font-medium text-[#17243A] outline-none transition-colors hover:border-[#9FAABD] focus:border-[#081D36] focus:bg-white"
              >
                {profileTypeOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option[locale]}
                  </option>
                ))}
              </select>
            </label>
          </section>
          <ProfileSection title={t.profile.practice} items={["Orthopedics", "CREOQ / CLLC"]} />
          <ProfileSection title={t.profile.consultation} items={["Initial consultation", "Follow-up visit", "Post-operative review"]} />
          <ProfileSection title={t.profile.language} items={["Auto-detect", "English", "Francais", "Medical voice recognition on"]} />
        </section>
        <section className={cn("rounded-md border border-[#D4D9E1] bg-white p-6", profileTab !== "data" && "hidden")}>
          <h2 className="font-serif text-2xl text-[#173B66]">Data management</h2>
          <p className="mt-2 text-sm text-[#667385]">Controls how long captured sessions and generated files are retained.</p>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <SelectSetting label="Session retention" choices={["24 hours", "7 days", "30 days", "Until manually deleted"]} />
            <SelectSetting label="Raw media retention" choices={["Delete after note approval", "24 hours", "7 days"]} />
            <SelectSetting label="Transcript retention" choices={["Keep with chart", "30 days", "Do not retain"]} />
            <SelectSetting label="Storage region" choices={["Canada", "United States", "Organization default"]} />
          </div>
        </section>
        <section className={cn("rounded-md border border-[#D4D9E1] bg-white p-6", profileTab !== "defaults" && "hidden")}>
          <h2 className="font-serif text-2xl text-[#173B66]">Defaults</h2>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <SelectSetting label="Platform language" choices={["English", "Francais"]} />
            <SelectSetting label="Default input language" choices={["Auto detect", "English", "French"]} />
            <SelectSetting label="Default output language" choices={["English", "French"]} />
            <SelectSetting label="Default capture input" choices={["Ambient capture", "Smart dictation", "Word for Word", "Audio + Video"]} />
          </div>
          <div className="mt-6 rounded-md bg-[#F6F7F8] p-4">
            <h3 className="text-lg font-semibold text-[#08111F]">Default note template per visit type</h3>
            <div className="mt-4 space-y-3">
              {visitTypeTemplates.map((mapping) => (
                <div key={mapping.visitType} className="grid gap-3 rounded bg-white p-3 text-sm md:grid-cols-[1fr_1fr]">
                  <span className="font-semibold text-[#17243A]">{mapping.visitType}</span>
                  <select defaultValue={mapping.noteTemplate} className="h-10 rounded-md border border-[#C8CED6] px-3 text-[#17243A]">
                    {templates.map((template) => (
                      <option key={template.name}>{template.name}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          </div>
        </section>
        <aside className="space-y-4">
          <div className="rounded-md border border-[#D4D9E1] bg-white p-6">
            <h2 className="text-lg font-semibold text-[#08111F]">Governance & operations</h2>
            <div className="mt-4 space-y-3 text-sm">
              <div className="flex justify-between rounded bg-[#F6F7F8] p-3"><span>EMR export</span><span>Demo</span></div>
              <div className="flex justify-between rounded bg-[#F6F7F8] p-3"><span>Calendar sync</span><span>Demo</span></div>
            </div>
          </div>
          <div className="rounded-md bg-[#081D36] p-6 text-white">
            <ShieldCheck className="size-7 text-[#D1B464]" />
            <h2 className="mt-4 text-xl font-semibold">{t.profile.privacy}</h2>
            <div className="mt-4 space-y-2 text-sm text-[#C7D3E2]">
              <p>Auto-purge: 24 hours</p>
              <p>Zero-persistence mode</p>
              <p>End-to-end encryption keys</p>
            </div>
          </div>
          <ActionButton>{t.profile.save}</ActionButton>
        </aside>
      </div>
    </div>
  )
}

function ProfileSection({ title, items }: { title: string; items: string[] }) {
  return (
    <section>
      <h2 className="font-serif text-2xl text-[#173B66]">{title}</h2>
      <div className="mt-4 flex flex-wrap gap-3">
        {items.map((item, index) => (
          <span
            key={item}
            className={cn(
              "rounded-md border px-4 py-3 text-sm",
              index === 0 ? "border-[#081D36] bg-[#081D36] text-white" : "border-[#D4D9E1] bg-[#F8F8F6] text-[#17243A]",
            )}
          >
            {item}
          </span>
        ))}
      </div>
    </section>
  )
}

function SettingsField({ label, value }: { label: string; value: string }) {
  return (
    <label className="space-y-2">
      <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">{label}</span>
      <input
        defaultValue={value}
        className="h-12 w-full rounded-md border border-[#C8CED6] bg-[#F8F8F6] px-4 text-sm text-[#17243A] outline-none focus:border-[#081D36] focus:bg-white"
      />
    </label>
  )
}

function SelectSetting({ label, choices }: { label: string; choices: string[] }) {
  return (
    <label className="space-y-2">
      <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6D7787]">{label}</span>
      <select className="h-12 w-full rounded-md border border-[#C8CED6] bg-[#F8F8F6] px-4 text-sm text-[#17243A] outline-none focus:border-[#081D36] focus:bg-white">
        {choices.map((choice) => (
          <option key={choice}>{choice}</option>
        ))}
      </select>
    </label>
  )
}

function SupportView({ t }: { t: typeof copy.en | typeof copy.fr }) {
  return (
    <div className="mx-auto max-w-5xl p-5 md:p-10">
      <h1 className="font-serif text-5xl text-[#08111F]">{t.support.title}</h1>
      <p className="mt-2 text-[#667385]">{t.support.subtitle}</p>
      <div className="mt-8 grid gap-5 md:grid-cols-3">
        <EvidenceCard title={t.support.feedback} source="Internal" lines={["Navigation clarity", "Clinical wording", "Validation evidence layout"]} />
        <EvidenceCard title={t.support.limitations} source="Demo" lines={["No real recording", "No backend storage", "No EMR connection"]} />
        <EvidenceCard title={t.support.contact} source="Aurion" lines={["contact@aurion.health", "Investor demo prototype"]} />
      </div>
    </div>
  )
}
