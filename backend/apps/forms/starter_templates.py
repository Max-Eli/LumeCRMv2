"""Pre-built form templates — the operator-facing starter library
for consent + intake forms.

How starters work (mirrors `apps.charts.starter_templates`):

  - Starters live in code (this module). They are NOT seeded into
    the DB on tenant creation.
  - When an operator clicks "Use this template" on /forms/new,
    the frontend POSTs to `/api/form-templates/` with the
    starter's payload (name, description, form_type, recurrence,
    schema). The created row is a regular tenant-owned template
    the operator can edit freely — the starter library never
    locks anything down.
  - Editing a tenant's copy never affects the starter. Updating
    starters in this module is a deploy-time concern.

Content discipline:

  - Every consent form opens with a `paragraph` block explaining
    the procedure, plus a separate `paragraph` listing material
    risks. This mirrors what a state medical board's informed-
    consent statute typically requires (statement, risks,
    alternatives, opportunity to ask questions).
  - Patient confirmations are `choice_single` (Yes/No) so the
    audit trail captures EACH acknowledgment as a discrete answer
    — not buried inside a free-text field.
  - Signature + date are always the last two fields.
  - Intake forms (medical history) skip the formal consent
    boilerplate and lead with allergies (the field that most
    often saves a life).

Adding a new starter: append to STARTER_FORMS, keep the slug
stable (changing it would break any tenant copy that references
it for re-import).

HIPAA note: these templates do NOT carry PHI — they're empty form
shells. Once a tenant clones one and a patient signs it, the
resulting FormSubmission carries PHI (answers + signature) and
is encrypted-at-rest in RDS + audit-logged on every read. The
starter content here is generic medspa-industry-standard language
that should still be reviewed by the tenant's own legal counsel
before going into live use — it's a starting point, not legal
advice.
"""

from __future__ import annotations

from typing import TypedDict, Literal


class StarterFormField(TypedDict, total=False):
    id: str
    type: Literal[
        'short_text', 'long_text', 'choice_single',
        'choice_multiple', 'date', 'signature', 'paragraph',
    ]
    label: str
    required: bool
    options: list[dict]
    hint: str
    body: str  # only for type='paragraph' — the prose block


class StarterForm(TypedDict):
    slug: str
    name: str
    description: str
    category: str
    form_type: Literal['intake', 'consent']
    recurrence: Literal['once', 'per_visit']
    fields: list[StarterFormField]


# Categories in the picker UI. Mirrors EMR pattern — kept small +
# medspa-canonical.
STARTER_CATEGORIES = (
    'Consent forms',
    'Intake & history',
    'Insurance & administrative',
    'Post-treatment',
)


# ── Helpers ──────────────────────────────────────────────────────


def _options(*pairs: str) -> list[dict]:
    """Convenience: {value, label} options from a flat list of labels.
    Value is a slugified copy of the label."""
    return [
        {
            'value': p.lower().replace(' ', '_').replace('/', '_').replace("'", ''),
            'label': p,
        }
        for p in pairs
    ]


# Reused acknowledgment block — operator can delete or edit per
# form, but every consent ends with the same shape so the audit
# trail is consistent.
def _consent_acknowledgments() -> list[StarterFormField]:
    return [
        {
            'id': 'ack_informed',
            'type': 'choice_single',
            'label': (
                'I confirm that the provider has explained the procedure, '
                'its risks, and alternatives to my satisfaction.'
            ),
            'required': True,
            'options': _options('Yes', 'No'),
        },
        {
            'id': 'ack_questions',
            'type': 'choice_single',
            'label': (
                'I have had the opportunity to ask questions, and my '
                'questions have been answered to my satisfaction.'
            ),
            'required': True,
            'options': _options('Yes', 'No'),
        },
        {
            'id': 'ack_voluntary',
            'type': 'choice_single',
            'label': (
                'I understand that I may refuse this treatment or withdraw '
                'my consent at any time without prejudice to my future care.'
            ),
            'required': True,
            'options': _options('Yes', 'No'),
        },
        {
            'id': 'questions_or_concerns',
            'type': 'long_text',
            'label': (
                'Any remaining questions or concerns to discuss before signing? '
                '(Optional)'
            ),
        },
        {
            'id': 'signature',
            'type': 'signature',
            'label': 'Patient signature',
            'required': True,
        },
        {
            'id': 'signed_date',
            'type': 'date',
            'label': 'Date',
            'required': True,
        },
    ]


# ── The library ───────────────────────────────────────────────────


STARTER_FORMS: list[StarterForm] = [
    # ── IV Therapy Consent ─────────────────────────────────────────
    {
        'slug': 'iv-therapy-consent',
        'name': 'IV therapy informed consent',
        'description': (
            'Patient consent for intravenous vitamin / hydration therapy. '
            'Covers procedure description, material risks, alternatives, '
            'and patient acknowledgments.'
        ),
        'category': 'Consent forms',
        'form_type': 'consent',
        'recurrence': 'per_visit',
        'fields': [
            {
                'id': 'intro',
                'type': 'paragraph',
                'label': 'About this procedure',
                'body': (
                    'Intravenous (IV) therapy delivers fluids, vitamins, '
                    'minerals, and/or other nutrients directly into your '
                    'bloodstream through a small catheter placed in a '
                    'vein in your arm or hand. Treatments typically take '
                    '30 to 60 minutes. The specific formulation has been '
                    'discussed with you by a licensed clinician.'
                ),
            },
            {
                'id': 'risks',
                'type': 'paragraph',
                'label': 'Material risks',
                'body': (
                    'Although IV therapy is generally well tolerated, '
                    'risks include but are not limited to:\n\n'
                    '• Pain, bruising, or swelling at the injection site\n'
                    '• Vein irritation, inflammation (phlebitis), or rare scarring\n'
                    '• Infection at the injection site\n'
                    '• Allergic reaction to one or more ingredients\n'
                    '• Dizziness, lightheadedness, or fainting (vasovagal response)\n'
                    '• Headache, nausea, or chills during or after infusion\n'
                    '• Electrolyte imbalance, particularly with magnesium-rich infusions\n'
                    '• In rare cases, fat-soluble vitamin overdose with repeated treatments\n'
                    '• Extravasation — fluid leaking into surrounding tissue if the '
                    'catheter is dislodged\n\n'
                    'You should inform your provider immediately of any '
                    'discomfort, shortness of breath, chest tightness, '
                    'or unusual sensation during the infusion.'
                ),
            },
            {
                'id': 'contraindications',
                'type': 'paragraph',
                'label': 'When IV therapy may not be appropriate',
                'body': (
                    'IV therapy is not recommended without further medical '
                    'evaluation if you have congestive heart failure, kidney '
                    'disease, severe liver disease, G6PD deficiency, or are '
                    'pregnant or breastfeeding. Please disclose all current '
                    'medical conditions and medications to your provider.'
                ),
            },
            {
                'id': 'alternatives',
                'type': 'paragraph',
                'label': 'Alternatives',
                'body': (
                    'Alternatives to IV therapy include oral supplementation, '
                    'dietary modification, and (where clinically indicated) '
                    'no treatment. These have been discussed with you.'
                ),
            },
            {
                'id': 'allergies_disclosure',
                'type': 'long_text',
                'label': (
                    'Please list any known allergies (medications, foods, latex, etc.)'
                ),
                'required': True,
            },
            {
                'id': 'current_medications',
                'type': 'long_text',
                'label': (
                    'Please list all current medications, supplements, and herbal '
                    'products you are taking'
                ),
                'required': True,
            },
            {
                'id': 'pregnancy_status',
                'type': 'choice_single',
                'label': 'Are you currently pregnant or trying to conceive?',
                'required': True,
                'options': _options(
                    'No', 'Yes', 'Not applicable', 'Prefer not to answer',
                ),
            },
            *_consent_acknowledgments(),
        ],
    },

    # ── Blood Draw Consent ─────────────────────────────────────────
    {
        'slug': 'blood-draw-consent',
        'name': 'Blood draw (venipuncture) consent',
        'description': (
            'Patient consent for routine venipuncture / phlebotomy. Used '
            'for lab panels, IV access prep, or diagnostic testing.'
        ),
        'category': 'Consent forms',
        'form_type': 'consent',
        'recurrence': 'per_visit',
        'fields': [
            {
                'id': 'intro',
                'type': 'paragraph',
                'label': 'About this procedure',
                'body': (
                    'Venipuncture (blood draw) involves the insertion of a '
                    'sterile needle into a vein, typically in the arm, to '
                    'collect a small sample of blood for laboratory testing '
                    'or to establish IV access. The procedure usually takes '
                    'less than five minutes.'
                ),
            },
            {
                'id': 'risks',
                'type': 'paragraph',
                'label': 'Material risks',
                'body': (
                    'Risks include but are not limited to:\n\n'
                    '• Pain or discomfort at the puncture site\n'
                    '• Bruising or hematoma (small pool of blood under the skin)\n'
                    '• Lightheadedness or fainting (vasovagal response)\n'
                    '• Infection at the puncture site\n'
                    '• Multiple needle sticks may be required if a vein is '
                    'difficult to access\n'
                    '• Nerve irritation, which is rare and usually temporary\n'
                    '• In very rare cases, arterial puncture or thrombosis'
                ),
            },
            {
                'id': 'purpose',
                'type': 'long_text',
                'label': 'Purpose of this blood draw (as explained to me)',
                'hint': (
                    'e.g. wellness panel, vitamin levels, hormone testing, '
                    'pre-treatment screening'
                ),
                'required': True,
            },
            {
                'id': 'prior_complications',
                'type': 'choice_single',
                'label': (
                    'Have you had complications with blood draws in the past '
                    '(fainting, excessive bruising, difficult vein access)?'
                ),
                'required': True,
                'options': _options('No', 'Yes'),
            },
            {
                'id': 'prior_complications_detail',
                'type': 'long_text',
                'label': 'If yes, please describe',
            },
            {
                'id': 'blood_thinners',
                'type': 'choice_single',
                'label': (
                    'Are you currently taking blood thinners (e.g. warfarin, '
                    'aspirin, clopidogrel, eliquis, xarelto)?'
                ),
                'required': True,
                'options': _options('No', 'Yes', 'Not sure'),
            },
            *_consent_acknowledgments(),
        ],
    },

    # ── Patient Insurance Form ─────────────────────────────────────
    {
        'slug': 'patient-insurance',
        'name': 'Patient insurance & financial authorization',
        'description': (
            "Captures the patient's insurance details and authorizes "
            'claims filing + financial responsibility for non-covered '
            'services. Most cosmetic services are NOT covered by '
            'insurance; this form is for the rare clinical / wellness '
            'services that may be billable, OR for spas that want this '
            'on file as a matter of course.'
        ),
        'category': 'Insurance & administrative',
        'form_type': 'intake',
        'recurrence': 'once',
        'fields': [
            {
                'id': 'notice',
                'type': 'paragraph',
                'label': 'Please read before completing',
                'body': (
                    'Most aesthetic / cosmetic services are not covered by '
                    'health insurance. This form is collected for our '
                    'records and to support claims for services that may '
                    'be billable (e.g. medically indicated IV therapy, '
                    'certain dermatologic conditions, or out-of-network '
                    'reimbursement at your discretion). You remain '
                    'responsible for the full cost of services not paid by '
                    'your insurance carrier.'
                ),
            },
            {
                'id': 'has_insurance',
                'type': 'choice_single',
                'label': 'Do you currently have health insurance?',
                'required': True,
                'options': _options('Yes', 'No', 'Prefer not to disclose'),
            },
            {
                'id': 'insurance_company',
                'type': 'short_text',
                'label': 'Insurance company name',
            },
            {
                'id': 'policy_number',
                'type': 'short_text',
                'label': 'Member / policy ID number',
            },
            {
                'id': 'group_number',
                'type': 'short_text',
                'label': 'Group number (if applicable)',
            },
            {
                'id': 'policyholder_name',
                'type': 'short_text',
                'label': 'Policyholder full name (if different from patient)',
            },
            {
                'id': 'policyholder_dob',
                'type': 'date',
                'label': 'Policyholder date of birth',
            },
            {
                'id': 'relationship',
                'type': 'choice_single',
                'label': "Patient's relationship to the policyholder",
                'options': _options('Self', 'Spouse', 'Parent', 'Child', 'Other'),
            },
            {
                'id': 'secondary_insurance',
                'type': 'choice_single',
                'label': 'Do you have secondary insurance?',
                'options': _options('No', 'Yes'),
            },
            {
                'id': 'secondary_details',
                'type': 'long_text',
                'label': 'Secondary insurance details (company, policy #, group #)',
            },
            {
                'id': 'authorization',
                'type': 'paragraph',
                'label': 'Authorization to release information & file claims',
                'body': (
                    'I authorize this practice to release any information '
                    'required to process insurance claims for services '
                    'rendered to me, including release of relevant medical '
                    'information to my insurance carrier. I authorize the '
                    'practice to file insurance claims on my behalf and '
                    'request that payment of authorized benefits be made '
                    'directly to the practice. I understand that this is '
                    'a HIPAA-authorized disclosure of my protected health '
                    'information limited to the minimum necessary to '
                    'support the claim.'
                ),
            },
            {
                'id': 'financial_responsibility',
                'type': 'paragraph',
                'label': 'Financial responsibility',
                'body': (
                    'I understand that I am financially responsible for '
                    'all charges not covered by my insurance, including '
                    'co-payments, deductibles, and non-covered services. '
                    'Cosmetic / aesthetic services are typically NOT '
                    'covered by insurance and full payment is expected '
                    'at the time of service.'
                ),
            },
            {
                'id': 'authorize_claims',
                'type': 'choice_single',
                'label': (
                    'I authorize this practice to file insurance claims '
                    'on my behalf for eligible services.'
                ),
                'required': True,
                'options': _options('Yes', 'No'),
            },
            {
                'id': 'accept_responsibility',
                'type': 'choice_single',
                'label': (
                    'I accept financial responsibility for any charges '
                    'not paid by my insurance.'
                ),
                'required': True,
                'options': _options('Yes', 'No'),
            },
            {
                'id': 'signature',
                'type': 'signature',
                'label': 'Patient (or guardian) signature',
                'required': True,
            },
            {
                'id': 'signed_date',
                'type': 'date',
                'label': 'Date',
                'required': True,
            },
        ],
    },

    # ── Medical History Intake ─────────────────────────────────────
    {
        'slug': 'medical-history-intake',
        'name': 'Medical history & health intake',
        'description': (
            'Comprehensive new-patient intake. Captures allergies, '
            'current medications, past medical history, surgical history, '
            'family history, lifestyle factors, and reason for visit. '
            'Recommended as the default intake for every new client.'
        ),
        'category': 'Intake & history',
        'form_type': 'intake',
        'recurrence': 'once',
        'fields': [
            {
                'id': 'intro',
                'type': 'paragraph',
                'label': 'Why we ask',
                'body': (
                    "Your responses help us provide treatments that are "
                    "safe and appropriate for you. Information you share "
                    "is treated as Protected Health Information (PHI) "
                    "under HIPAA and is used only by your clinical care "
                    "team. If you're unsure of an answer, please ask your "
                    "provider before completing this section."
                ),
            },
            # Allergies first — most critical for patient safety.
            {
                'id': 'allergies_drug',
                'type': 'long_text',
                'label': 'Drug allergies (medications, IV products, anesthetics)',
                'hint': 'List each drug and the reaction (e.g. "penicillin — hives")',
                'required': True,
            },
            {
                'id': 'allergies_other',
                'type': 'long_text',
                'label': 'Other allergies (food, latex, adhesives, environmental)',
            },
            {
                'id': 'current_medications',
                'type': 'long_text',
                'label': (
                    'Current medications, supplements, herbal products '
                    '(name + dose + how often)'
                ),
                'required': True,
            },
            {
                'id': 'blood_thinners',
                'type': 'choice_single',
                'label': (
                    'Are you currently taking blood thinners or aspirin '
                    'within the last 7 days?'
                ),
                'required': True,
                'options': _options('No', 'Yes'),
            },
            {
                'id': 'past_conditions',
                'type': 'choice_multiple',
                'label': (
                    'Please check any conditions you have or have had '
                    '(check all that apply)'
                ),
                'options': _options(
                    'Diabetes', 'High blood pressure', 'Heart disease',
                    'Stroke or TIA', 'Bleeding disorder', 'Blood clots / DVT',
                    'Cancer (any type)', 'Liver disease', 'Kidney disease',
                    'Thyroid disease', 'Autoimmune disease', 'Lupus',
                    'Rheumatoid arthritis', 'Asthma', 'Seizures or epilepsy',
                    'Anxiety or depression', 'HIV / AIDS', 'Hepatitis B or C',
                    'Herpes (cold sores or genital)', 'Keloid scarring',
                    'Skin cancer or melanoma', 'Eczema or psoriasis',
                ),
            },
            {
                'id': 'past_conditions_other',
                'type': 'long_text',
                'label': 'Other conditions not listed above',
            },
            {
                'id': 'surgical_history',
                'type': 'long_text',
                'label': 'Past surgeries (with approximate dates)',
            },
            {
                'id': 'cosmetic_history',
                'type': 'long_text',
                'label': (
                    'Past cosmetic / dermatologic treatments '
                    '(neurotoxins, fillers, laser, peels, etc.) — '
                    'include approximate dates'
                ),
            },
            {
                'id': 'pregnancy_status',
                'type': 'choice_single',
                'label': (
                    'Pregnancy status (some treatments are not safe '
                    'during pregnancy or breastfeeding)'
                ),
                'required': True,
                'options': _options(
                    'Not applicable',
                    'Not pregnant',
                    'Currently pregnant',
                    'Currently breastfeeding',
                    'Trying to conceive',
                    'Prefer not to answer',
                ),
            },
            {
                'id': 'smoking',
                'type': 'choice_single',
                'label': 'Tobacco / nicotine use',
                'options': _options(
                    'Never', 'Former, quit > 1 year ago',
                    'Former, quit < 1 year ago', 'Current — occasional',
                    'Current — daily',
                ),
            },
            {
                'id': 'alcohol',
                'type': 'choice_single',
                'label': 'Alcohol use',
                'options': _options(
                    'None', 'Occasional', '1–2 drinks per week',
                    '3–7 drinks per week', '8+ drinks per week',
                ),
            },
            {
                'id': 'family_history',
                'type': 'choice_multiple',
                'label': (
                    'Family medical history — please check any conditions '
                    'in first-degree relatives (parents, siblings, children)'
                ),
                'options': _options(
                    'Diabetes', 'Heart disease', 'Stroke',
                    'High blood pressure', 'Cancer', 'Melanoma / skin cancer',
                    'Bleeding disorder', 'Blood clots',
                    'Autoimmune disease', 'None / not known',
                ),
            },
            {
                'id': 'reason_for_visit',
                'type': 'long_text',
                'label': "What brought you in today? Concerns or goals for this visit",
                'required': True,
            },
            {
                'id': 'signature',
                'type': 'signature',
                'label': (
                    'I attest that the information above is true and '
                    'complete to the best of my knowledge'
                ),
                'required': True,
            },
            {
                'id': 'signed_date',
                'type': 'date',
                'label': 'Date',
                'required': True,
            },
        ],
    },

    # ── Post-Treatment Instructions & Acknowledgment ───────────────
    {
        'slug': 'post-treatment-acknowledgment',
        'name': 'Post-treatment instructions & acknowledgment',
        'description': (
            'Generic post-care acknowledgment the operator can use at '
            'check-out. Provider can add visit-specific notes; patient '
            'signs to confirm they received the instructions and '
            'understand activity restrictions.'
        ),
        'category': 'Post-treatment',
        'form_type': 'consent',
        'recurrence': 'per_visit',
        'fields': [
            {
                'id': 'intro',
                'type': 'paragraph',
                'label': 'Post-treatment care',
                'body': (
                    'Following the recommendations below helps ensure the '
                    'best result from your treatment and reduces the risk '
                    'of complications. If you experience any of the warning '
                    'signs listed at the end of this form, please contact '
                    'the practice immediately.'
                ),
            },
            {
                'id': 'treatment_performed',
                'type': 'long_text',
                'label': (
                    'Treatment(s) performed today '
                    '(completed by your provider)'
                ),
            },
            {
                'id': 'areas_treated',
                'type': 'long_text',
                'label': 'Area(s) treated',
            },
            {
                'id': 'products_used',
                'type': 'long_text',
                'label': (
                    'Products / lots / dosages used '
                    '(completed by your provider — kept in your chart)'
                ),
            },
            {
                'id': 'general_care',
                'type': 'paragraph',
                'label': 'General post-care recommendations',
                'body': (
                    '• Avoid touching, rubbing, or massaging the treated area for '
                    'at least 24 hours unless specifically instructed otherwise.\n'
                    '• Avoid strenuous exercise, sauna, hot tub, or hot showers '
                    'for 24–48 hours.\n'
                    '• Avoid alcohol for 24 hours.\n'
                    '• Stay hydrated — drink water throughout the day.\n'
                    '• Avoid direct sun exposure to the treated area; use SPF 30 '
                    'or higher when outside.\n'
                    '• Some redness, swelling, or tenderness is normal and '
                    'typically resolves within 24–72 hours.\n'
                    '• Apply cool compresses (not ice directly) if needed for '
                    'comfort.\n'
                    '• Take acetaminophen (Tylenol) if needed for discomfort — '
                    'AVOID aspirin, ibuprofen, naproxen, and other NSAIDs for '
                    '48 hours unless your provider specifically approves them.'
                ),
            },
            {
                'id': 'visit_specific_instructions',
                'type': 'long_text',
                'label': (
                    'Visit-specific instructions from your provider '
                    '(any deviations from the general care above)'
                ),
            },
            {
                'id': 'warning_signs',
                'type': 'paragraph',
                'label': 'When to call us',
                'body': (
                    'Contact the practice if you experience any of the following:\n\n'
                    '• Severe or worsening pain not relieved by acetaminophen\n'
                    '• Rapidly spreading redness, swelling, or warmth\n'
                    '• Pus, drainage, or signs of infection\n'
                    '• Fever above 101°F (38.3°C)\n'
                    '• Severe headache, vision changes, or weakness\n'
                    '• Shortness of breath, chest tightness, or facial '
                    'swelling (call 911 if severe)\n'
                    '• Any reaction that feels significantly different from '
                    'what was discussed during your treatment'
                ),
            },
            {
                'id': 'follow_up',
                'type': 'short_text',
                'label': (
                    'Recommended follow-up timing '
                    '(completed by your provider)'
                ),
                'hint': 'e.g. "2 weeks for touch-up", "6 weeks for assessment"',
            },
            {
                'id': 'questions_at_checkout',
                'type': 'long_text',
                'label': (
                    'Any questions or symptoms experienced during the visit?'
                ),
            },
            {
                'id': 'ack_received',
                'type': 'choice_single',
                'label': (
                    'I received and understand the post-treatment '
                    'instructions above.'
                ),
                'required': True,
                'options': _options('Yes', 'No'),
            },
            {
                'id': 'ack_warning_signs',
                'type': 'choice_single',
                'label': (
                    'I understand the warning signs and how to contact the '
                    'practice if I experience any of them.'
                ),
                'required': True,
                'options': _options('Yes', 'No'),
            },
            {
                'id': 'signature',
                'type': 'signature',
                'label': 'Patient signature',
                'required': True,
            },
            {
                'id': 'signed_date',
                'type': 'date',
                'label': 'Date',
                'required': True,
            },
        ],
    },
]


# ── Lookup helpers ───────────────────────────────────────────────


def starter_form_by_slug(slug: str) -> StarterForm | None:
    for f in STARTER_FORMS:
        if f['slug'] == slug:
            return f
    return None


def list_starter_forms() -> list[dict]:
    """Catalog shape for the picker UI: just the metadata, no fields."""
    return [
        {
            'slug': f['slug'],
            'name': f['name'],
            'description': f['description'],
            'category': f['category'],
            'form_type': f['form_type'],
            'recurrence': f['recurrence'],
            'field_count': len(f['fields']),
        }
        for f in STARTER_FORMS
    ]
