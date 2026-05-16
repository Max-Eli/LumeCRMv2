"""Pre-built treatment record templates — the "starter library."

The aim is what every other medspa EMR ships: a curated catalog of
common treatments tenants can clone into their own editable
templates instead of authoring a Botox record from scratch on day
one. The field selections here are deliberate — informed by what
Aesthetic Record / Symplast / Boulevard / PatientNow expose and by
what clinical documentation actually needs to capture (dose, lot,
expiration, site, technique, reaction, post-care).

How starters interact with the live `TreatmentRecordTemplate` model:
  - Starters live in code (this module). They are NOT seeded into
    the DB on tenant creation.
  - When a tenant clicks "Use this template," the frontend POSTs to
    `/api/treatment-record-templates/` with the starter's name +
    schema + (optional) description. The result is a regular
    tenant-owned template the operator can edit freely — the
    starter library doesn't lock anything down.
  - Editing a tenant's copy never affects the starter. Updating
    starters in this module is a deploy-time concern; existing
    tenant copies stay frozen.

Adding a new starter:
  1. Append a new dict to `STARTER_TEMPLATES`.
  2. `slug` is the URL-safe identifier the frontend uses to request
     a starter ("import this one"). Keep it stable — changing it
     would break any tenant who saved a reference.
  3. `category` groups starters in the picker UI. Keep to the small
     vocabulary in `STARTER_CATEGORIES`.
  4. `schema.fields` follows the same shape as
     `TreatmentRecordTemplate.schema.fields` — type, label, id,
     required, options (for choice fields).

Why hardcoded vs. DB-seeded: a code-resident library is versionable
(grep, code review), testable, and doesn't pollute every tenant's
schema. The trade-off is editing-via-deploy, but starters change
rarely and the tenant copies are where the daily edits happen.
"""

from __future__ import annotations

from typing import TypedDict, Literal


class StarterField(TypedDict, total=False):
    id: str
    type: Literal[
        'short_text', 'long_text', 'choice_single',
        'choice_multiple', 'number', 'date', 'signature',
    ]
    label: str
    required: bool
    options: list[dict]
    hint: str


class StarterTemplate(TypedDict):
    slug: str
    name: str
    description: str
    category: str
    fields: list[StarterField]


# Categories shown in the picker. Keep the set small + medspa-
# canonical so the grouping reads cleanly. Adding a new category
# means adding a label here AND in the frontend display map.
STARTER_CATEGORIES = (
    'Injectables',
    'Facials & Skin',
    'Laser & Energy',
    'Body & Contouring',
    'Other',
)


# ── Helpers ──────────────────────────────────────────────────────


def _options(*pairs: str) -> list[dict]:
    """Convenience: build {value, label} options from a flat list of
    labels. The value is a slugified copy of the label."""
    return [
        {
            'value': p.lower().replace(' ', '_').replace('/', '_'),
            'label': p,
        }
        for p in pairs
    ]


# ── The library ───────────────────────────────────────────────────


STARTER_TEMPLATES: list[StarterTemplate] = [
    # ── Injectables ────────────────────────────────────────────────
    {
        'slug': 'botox-neurotoxin',
        'name': 'Botox / Neurotoxin treatment record',
        'description': (
            'Pre-treatment safety check, per-site dosing, product + '
            'lot capture, and post-care notes for botulinum-toxin '
            'injections (Botox, Dysport, Xeomin, Jeuveau).'
        ),
        'category': 'Injectables',
        'fields': [
            {'id': 'product', 'type': 'choice_single', 'label': 'Product',
             'required': True,
             'options': _options('Botox', 'Dysport', 'Xeomin', 'Jeuveau', 'Daxxify')},
            {'id': 'lot_number', 'type': 'short_text', 'label': 'Lot number',
             'required': True},
            {'id': 'expiration', 'type': 'date', 'label': 'Lot expiration date'},
            {'id': 'dilution', 'type': 'short_text', 'label': 'Dilution (e.g. 2 mL)'},
            {'id': 'recent_meds', 'type': 'long_text',
             'label': 'Recent medications / supplements (blood thinners, NSAIDs, fish oil)'},
            {'id': 'last_treatment_date', 'type': 'date',
             'label': 'Date of last neurotoxin treatment (if any)'},
            {'id': 'pre_photos', 'type': 'choice_single',
             'label': 'Pre-treatment photos taken',
             'options': _options('Yes', 'No', 'Customer declined')},
            {'id': 'glabella_units', 'type': 'number', 'label': 'Glabella — units'},
            {'id': 'forehead_units', 'type': 'number', 'label': 'Forehead — units'},
            {'id': 'crows_feet_left_units', 'type': 'number',
             'label': "Crow's feet (L) — units"},
            {'id': 'crows_feet_right_units', 'type': 'number',
             'label': "Crow's feet (R) — units"},
            {'id': 'brow_lift_left_units', 'type': 'number', 'label': 'Brow lift (L) — units'},
            {'id': 'brow_lift_right_units', 'type': 'number', 'label': 'Brow lift (R) — units'},
            {'id': 'bunny_lines_units', 'type': 'number', 'label': 'Bunny lines — units'},
            {'id': 'masseter_left_units', 'type': 'number', 'label': 'Masseter (L) — units'},
            {'id': 'masseter_right_units', 'type': 'number', 'label': 'Masseter (R) — units'},
            {'id': 'lip_flip_units', 'type': 'number', 'label': 'Lip flip — units'},
            {'id': 'dao_left_units', 'type': 'number', 'label': 'DAO (L) — units'},
            {'id': 'dao_right_units', 'type': 'number', 'label': 'DAO (R) — units'},
            {'id': 'chin_units', 'type': 'number',
             'label': 'Mentalis / chin — units'},
            {'id': 'platysma_units', 'type': 'number',
             'label': 'Platysmal bands — units'},
            {'id': 'other_sites', 'type': 'long_text',
             'label': 'Other sites / off-label (location + units)'},
            {'id': 'total_units', 'type': 'number',
             'label': 'TOTAL units administered', 'required': True},
            {'id': 'technique', 'type': 'long_text',
             'label': 'Injection technique notes'},
            {'id': 'side_effects', 'type': 'choice_multiple',
             'label': 'Immediate side effects observed',
             'options': _options(
                 'None', 'Pinpoint bleeding', 'Bruising', 'Erythema',
                 'Headache', 'Lightheaded', 'Other',
             )},
            {'id': 'side_effects_notes', 'type': 'long_text',
             'label': 'Side effects detail'},
            {'id': 'post_care_reviewed', 'type': 'choice_single',
             'label': 'Post-care instructions reviewed with client',
             'required': True,
             'options': _options('Yes', 'No')},
            {'id': 'follow_up_weeks', 'type': 'number',
             'label': 'Follow-up scheduled in (weeks)'},
            {'id': 'provider_notes', 'type': 'long_text',
             'label': 'Provider notes'},
        ],
    },
    {
        'slug': 'dermal-filler',
        'name': 'Dermal filler treatment record',
        'description': (
            'HA filler documentation — product per syringe, lot + '
            'expiration tracking, per-area volume, anesthesia, '
            'cannula vs. needle, post-care. Covers Juvederm, '
            'Restylane, RHA, Versa, Belotero families.'
        ),
        'category': 'Injectables',
        'fields': [
            {'id': 'product_line', 'type': 'choice_single',
             'label': 'Product line',
             'required': True,
             'options': _options(
                 'Juvederm Ultra', 'Juvederm Ultra Plus', 'Juvederm Voluma',
                 'Juvederm Volbella', 'Juvederm Vollure', 'Juvederm Volux',
                 'Restylane', 'Restylane Lyft', 'Restylane Silk',
                 'Restylane Refyne', 'Restylane Defyne', 'Restylane Kysse',
                 'Restylane Contour', 'Restylane Eyelight',
                 'RHA 2', 'RHA 3', 'RHA 4',
                 'Versa', 'Belotero',
                 'Sculptra (PLLA)', 'Radiesse (CaHA)', 'Other',
             )},
            {'id': 'lot_numbers', 'type': 'long_text',
             'label': 'Lot numbers (one per syringe used)',
             'required': True,
             'hint': 'List each syringe lot separated by commas.'},
            {'id': 'expiration', 'type': 'date',
             'label': 'Earliest lot expiration'},
            {'id': 'cannula_or_needle', 'type': 'choice_single',
             'label': 'Cannula or needle',
             'options': _options('Cannula', 'Needle', 'Both')},
            {'id': 'anesthesia', 'type': 'choice_multiple',
             'label': 'Anesthesia',
             'options': _options(
                 'None', 'Topical (BLT)', 'Lidocaine in product',
                 'Dental block', 'Ice',
             )},
            {'id': 'lips_ml', 'type': 'number', 'label': 'Lips — mL'},
            {'id': 'nasolabial_folds_ml', 'type': 'number',
             'label': 'Nasolabial folds — mL'},
            {'id': 'marionette_lines_ml', 'type': 'number',
             'label': 'Marionette lines — mL'},
            {'id': 'cheeks_left_ml', 'type': 'number', 'label': 'Cheeks (L) — mL'},
            {'id': 'cheeks_right_ml', 'type': 'number', 'label': 'Cheeks (R) — mL'},
            {'id': 'tear_troughs_left_ml', 'type': 'number',
             'label': 'Tear troughs (L) — mL'},
            {'id': 'tear_troughs_right_ml', 'type': 'number',
             'label': 'Tear troughs (R) — mL'},
            {'id': 'chin_ml', 'type': 'number', 'label': 'Chin — mL'},
            {'id': 'jawline_left_ml', 'type': 'number', 'label': 'Jawline (L) — mL'},
            {'id': 'jawline_right_ml', 'type': 'number', 'label': 'Jawline (R) — mL'},
            {'id': 'temples_left_ml', 'type': 'number', 'label': 'Temples (L) — mL'},
            {'id': 'temples_right_ml', 'type': 'number', 'label': 'Temples (R) — mL'},
            {'id': 'other_areas', 'type': 'long_text',
             'label': 'Other areas (location + mL)'},
            {'id': 'total_ml', 'type': 'number',
             'label': 'TOTAL mL injected', 'required': True},
            {'id': 'hyaluronidase_on_hand', 'type': 'choice_single',
             'label': 'Hyaluronidase available on-site',
             'options': _options('Yes', 'No')},
            {'id': 'side_effects', 'type': 'choice_multiple',
             'label': 'Immediate side effects observed',
             'options': _options(
                 'None', 'Bruising', 'Swelling',
                 'Erythema', 'Asymmetry', 'Other',
             )},
            {'id': 'side_effects_notes', 'type': 'long_text',
             'label': 'Side effects detail'},
            {'id': 'pre_photos', 'type': 'choice_single',
             'label': 'Pre-treatment photos taken',
             'options': _options('Yes', 'No', 'Customer declined')},
            {'id': 'post_care_reviewed', 'type': 'choice_single',
             'label': 'Post-care instructions reviewed',
             'required': True,
             'options': _options('Yes', 'No')},
            {'id': 'follow_up_weeks', 'type': 'number',
             'label': 'Follow-up scheduled in (weeks)'},
            {'id': 'provider_notes', 'type': 'long_text',
             'label': 'Provider notes'},
        ],
    },

    # ── Facials & Skin ──────────────────────────────────────────────
    {
        'slug': 'hydrafacial',
        'name': 'HydraFacial treatment record',
        'description': (
            'Skin assessment, booster + add-on tracking, tips used, '
            'and home-care recommendations. Suitable for HydraFacial '
            'MD / Allegro and similar device-driven treatments.'
        ),
        'category': 'Facials & Skin',
        'fields': [
            {'id': 'skin_concerns', 'type': 'choice_multiple',
             'label': 'Primary skin concerns',
             'options': _options(
                 'Dryness', 'Oiliness', 'Acne', 'Hyperpigmentation',
                 'Redness / rosacea', 'Texture', 'Fine lines',
                 'Dullness', 'Sun damage', 'Sensitivity',
             )},
            {'id': 'fitzpatrick', 'type': 'choice_single',
             'label': 'Fitzpatrick skin type',
             'options': _options('I', 'II', 'III', 'IV', 'V', 'VI')},
            {'id': 'tip_used', 'type': 'choice_single',
             'label': 'Treatment tip',
             'options': _options(
                 'Standard', 'Aqua peel', 'Glysal',
                 'BetaHD', 'Sensitive', 'Other',
             )},
            {'id': 'boosters', 'type': 'choice_multiple',
             'label': 'Boosters used',
             'options': _options(
                 'Britenol (brightening)', 'Dermabuilder (anti-aging)',
                 'CTGF (growth factors)', 'Hydraglucan (hydration)',
                 'Restorative complex', 'ProBiome', 'Other',
             )},
            {'id': 'add_ons', 'type': 'choice_multiple',
             'label': 'Add-ons',
             'options': _options(
                 'LED red light', 'LED blue light',
                 'Lymphatic drainage', 'Perk eye',
                 'Perk lip', 'Other',
             )},
            {'id': 'extractions_performed', 'type': 'choice_single',
             'label': 'Manual extractions performed',
             'options': _options('Yes', 'No')},
            {'id': 'extractions_notes', 'type': 'long_text',
             'label': 'Extractions detail (location, count)'},
            {'id': 'skin_response', 'type': 'choice_single',
             'label': 'Skin response to treatment',
             'options': _options('Mild erythema', 'Moderate erythema',
                                 'Significant flushing', 'No notable response')},
            {'id': 'side_effects', 'type': 'long_text',
             'label': 'Side effects observed'},
            {'id': 'pre_post_photos', 'type': 'choice_single',
             'label': 'Pre/post photos captured',
             'options': _options('Yes — both', 'Pre only', 'No')},
            {'id': 'products_recommended', 'type': 'long_text',
             'label': 'Home-care products recommended'},
            {'id': 'follow_up_weeks', 'type': 'number',
             'label': 'Suggested follow-up in (weeks)'},
            {'id': 'provider_notes', 'type': 'long_text',
             'label': 'Provider notes'},
        ],
    },
    {
        'slug': 'chemical-peel',
        'name': 'Chemical peel treatment record',
        'description': (
            'Peel type + strength, layer count, neutralization, '
            'patient reaction, and downtime expectations. Covers '
            'superficial through medium-depth peels.'
        ),
        'category': 'Facials & Skin',
        'fields': [
            {'id': 'peel_type', 'type': 'choice_single',
             'label': 'Peel type',
             'required': True,
             'options': _options(
                 'Glycolic acid', 'Salicylic acid', 'Lactic acid',
                 'Mandelic acid', 'Jessner', 'TCA',
                 'VI Peel', 'Perfect Derma', 'Cosmelan',
                 'Enzyme', 'Other',
             )},
            {'id': 'strength_pct', 'type': 'short_text',
             'label': 'Concentration / strength (e.g. 30%)',
             'required': True},
            {'id': 'fitzpatrick', 'type': 'choice_single',
             'label': 'Fitzpatrick skin type',
             'options': _options('I', 'II', 'III', 'IV', 'V', 'VI')},
            {'id': 'pretreatment_compliance', 'type': 'choice_single',
             'label': 'Client followed pre-treatment regimen',
             'options': _options('Yes — full', 'Partial', 'No', 'N/A')},
            {'id': 'layers', 'type': 'number', 'label': 'Layers applied'},
            {'id': 'minutes_left_on', 'type': 'number',
             'label': 'Minutes left on (if timed)'},
            {'id': 'neutralizer', 'type': 'short_text',
             'label': 'Neutralizer used'},
            {'id': 'frost_observed', 'type': 'choice_single',
             'label': 'Frosting observed',
             'options': _options(
                 'None', 'Level 1 (mild)',
                 'Level 2 (speckled)', 'Level 3 (solid white)',
             )},
            {'id': 'erythema_response', 'type': 'choice_single',
             'label': 'Erythema response',
             'options': _options('Mild', 'Moderate', 'Significant')},
            {'id': 'patient_discomfort', 'type': 'choice_single',
             'label': 'Patient discomfort (1–10)',
             'options': _options('1', '2', '3', '4', '5', '6', '7', '8', '9', '10')},
            {'id': 'post_care_kit', 'type': 'choice_single',
             'label': 'Post-care kit dispensed',
             'options': _options('Yes', 'No')},
            {'id': 'expected_downtime_days', 'type': 'number',
             'label': 'Expected peeling / downtime (days)'},
            {'id': 'follow_up_weeks', 'type': 'number',
             'label': 'Follow-up in (weeks)'},
            {'id': 'provider_notes', 'type': 'long_text',
             'label': 'Provider notes'},
        ],
    },
    {
        'slug': 'microneedling',
        'name': 'Microneedling treatment record',
        'description': (
            'Device + depth per area, topical numbing time, serum '
            'used (including PRP for vampire facial), reaction, '
            'and post-care.'
        ),
        'category': 'Facials & Skin',
        'fields': [
            {'id': 'device', 'type': 'choice_single',
             'label': 'Device',
             'options': _options(
                 'SkinPen', 'Dermapen', 'Morpheus8',
                 'Rejuvapen', 'Dr. Pen', 'Other',
             )},
            {'id': 'numbing_time_min', 'type': 'number',
             'label': 'Topical numbing time (minutes)'},
            {'id': 'depth_forehead_mm', 'type': 'number',
             'label': 'Forehead depth (mm)'},
            {'id': 'depth_cheeks_mm', 'type': 'number',
             'label': 'Cheeks depth (mm)'},
            {'id': 'depth_chin_mm', 'type': 'number',
             'label': 'Chin / jawline depth (mm)'},
            {'id': 'depth_neck_mm', 'type': 'number',
             'label': 'Neck depth (mm)'},
            {'id': 'depth_other', 'type': 'long_text',
             'label': 'Other areas + depth'},
            {'id': 'passes', 'type': 'number', 'label': 'Passes per area'},
            {'id': 'serum_used', 'type': 'choice_multiple',
             'label': 'Serum / topical applied',
             'options': _options(
                 'Hyaluronic acid', 'Growth factors',
                 'PRP', 'Vitamin C', 'Peptide', 'Other',
             )},
            {'id': 'prp_volume_ml', 'type': 'number',
             'label': 'PRP volume (mL) — if applicable'},
            {'id': 'patient_discomfort', 'type': 'choice_single',
             'label': 'Patient discomfort (1–10)',
             'options': _options('1', '2', '3', '4', '5', '6', '7', '8', '9', '10')},
            {'id': 'erythema_response', 'type': 'choice_single',
             'label': 'Erythema response',
             'options': _options(
                 'Mild', 'Moderate', 'Significant', 'Pinpoint bleeding',
             )},
            {'id': 'side_effects', 'type': 'long_text',
             'label': 'Other side effects observed'},
            {'id': 'post_care_reviewed', 'type': 'choice_single',
             'label': 'Post-care instructions reviewed',
             'required': True,
             'options': _options('Yes', 'No')},
            {'id': 'follow_up_weeks', 'type': 'number',
             'label': 'Follow-up in (weeks)'},
            {'id': 'provider_notes', 'type': 'long_text',
             'label': 'Provider notes'},
        ],
    },

    # ── Laser & Energy ──────────────────────────────────────────────
    {
        'slug': 'laser-hair-removal',
        'name': 'Laser hair removal treatment record',
        'description': (
            'Per-area device + settings, test patch reaction, pulse '
            'count, and series tracking. Capture per session so the '
            'next provider can pick up the protocol.'
        ),
        'category': 'Laser & Energy',
        'fields': [
            {'id': 'session_number', 'type': 'number',
             'label': 'Session number in series', 'required': True},
            {'id': 'treatment_area', 'type': 'choice_multiple',
             'label': 'Treatment area',
             'required': True,
             'options': _options(
                 'Upper lip', 'Chin', 'Sideburns', 'Full face',
                 'Underarms', 'Bikini', 'Brazilian',
                 'Lower legs', 'Full legs', 'Lower back',
                 'Chest', 'Back', 'Arms', 'Other',
             )},
            {'id': 'fitzpatrick', 'type': 'choice_single',
             'label': 'Fitzpatrick skin type',
             'required': True,
             'options': _options('I', 'II', 'III', 'IV', 'V', 'VI')},
            {'id': 'hair_color', 'type': 'choice_single',
             'label': 'Hair color',
             'options': _options(
                 'Black', 'Brown', 'Red', 'Blonde', 'Gray/white', 'Mixed',
             )},
            {'id': 'device', 'type': 'choice_single',
             'label': 'Device / wavelength',
             'options': _options(
                 'Alexandrite (755nm)', 'Diode (810nm)',
                 'Nd:YAG (1064nm)', 'IPL', 'Combo (multi-wavelength)',
             )},
            {'id': 'fluence_joules', 'type': 'short_text',
             'label': 'Fluence (J/cm²)'},
            {'id': 'pulse_width_ms', 'type': 'short_text',
             'label': 'Pulse width (ms)'},
            {'id': 'spot_size_mm', 'type': 'short_text',
             'label': 'Spot size (mm)'},
            {'id': 'cooling_used', 'type': 'choice_single',
             'label': 'Cooling',
             'options': _options(
                 'Contact', 'Cryogen spray', 'Forced air', 'None',
             )},
            {'id': 'test_patch_reaction', 'type': 'choice_single',
             'label': 'Test patch reaction',
             'options': _options(
                 'No reaction', 'Erythema only',
                 'Perifollicular edema', 'Adverse — discontinued',
             )},
            {'id': 'pulses_count', 'type': 'number',
             'label': 'Total pulses delivered'},
            {'id': 'patient_discomfort', 'type': 'choice_single',
             'label': 'Patient discomfort (1–10)',
             'options': _options('1', '2', '3', '4', '5', '6', '7', '8', '9', '10')},
            {'id': 'side_effects', 'type': 'choice_multiple',
             'label': 'Side effects observed',
             'options': _options(
                 'None', 'Erythema', 'Perifollicular edema',
                 'Blistering', 'Hyperpigmentation',
                 'Hypopigmentation', 'Other',
             )},
            {'id': 'sessions_remaining_in_package', 'type': 'number',
             'label': 'Sessions remaining (if package)'},
            {'id': 'follow_up_weeks', 'type': 'number',
             'label': 'Next session in (weeks)'},
            {'id': 'provider_notes', 'type': 'long_text',
             'label': 'Provider notes'},
        ],
    },
    {
        'slug': 'ipl-photofacial',
        'name': 'IPL / Photofacial treatment record',
        'description': (
            'Per-pass settings + skin response for IPL on vascular '
            '+ pigmentary concerns. Tracks energy / pulse / delay '
            'and series progression.'
        ),
        'category': 'Laser & Energy',
        'fields': [
            {'id': 'primary_concern', 'type': 'choice_single',
             'label': 'Primary concern',
             'options': _options(
                 'Redness / vascular', 'Pigmentation',
                 'Both', 'Photo damage', 'Rosacea',
             )},
            {'id': 'fitzpatrick', 'type': 'choice_single',
             'label': 'Fitzpatrick skin type',
             'required': True,
             'options': _options('I', 'II', 'III', 'IV', 'V', 'VI')},
            {'id': 'session_number', 'type': 'number',
             'label': 'Session number in series'},
            {'id': 'energy_joules', 'type': 'short_text',
             'label': 'Energy (J/cm²)'},
            {'id': 'pulse_count', 'type': 'short_text',
             'label': 'Pulse count / pattern'},
            {'id': 'delay_ms', 'type': 'short_text',
             'label': 'Pulse delay (ms)'},
            {'id': 'filter_used', 'type': 'short_text',
             'label': 'Filter / wavelength cutoff'},
            {'id': 'passes', 'type': 'number', 'label': 'Number of passes'},
            {'id': 'test_spot', 'type': 'choice_single',
             'label': 'Test spot performed',
             'options': _options('Yes', 'No (prior session was test)')},
            {'id': 'immediate_response', 'type': 'choice_multiple',
             'label': 'Immediate skin response',
             'options': _options(
                 'Erythema', 'Edema',
                 'Darkening of pigment (expected)',
                 'Vascular reaction', 'None visible',
             )},
            {'id': 'side_effects', 'type': 'long_text',
             'label': 'Side effects observed'},
            {'id': 'post_care_reviewed', 'type': 'choice_single',
             'label': 'Post-care instructions reviewed',
             'required': True,
             'options': _options('Yes', 'No')},
            {'id': 'follow_up_weeks', 'type': 'number',
             'label': 'Next session in (weeks)'},
            {'id': 'provider_notes', 'type': 'long_text',
             'label': 'Provider notes'},
        ],
    },

    # ── Body & Contouring ───────────────────────────────────────────
    {
        'slug': 'body-contouring',
        'name': 'Body contouring treatment record',
        'description': (
            'Per-cycle documentation for CoolSculpting, EmSculpt, '
            'TruSculpt and similar device-driven body treatments. '
            'Captures applicator, cycles, and tolerance.'
        ),
        'category': 'Body & Contouring',
        'fields': [
            {'id': 'device', 'type': 'choice_single',
             'label': 'Device',
             'options': _options(
                 'CoolSculpting Elite', 'CoolSculpting (legacy)',
                 'EmSculpt Neo', 'EmSculpt', 'TruSculpt iD',
                 'truSculpt flex', 'Vanquish', 'SculpSure',
                 'Other',
             )},
            {'id': 'treatment_area', 'type': 'choice_multiple',
             'label': 'Treatment area',
             'required': True,
             'options': _options(
                 'Abdomen — upper', 'Abdomen — lower',
                 'Flanks (L)', 'Flanks (R)',
                 'Inner thighs', 'Outer thighs',
                 'Bra rolls', 'Back rolls',
                 'Submental (double chin)', 'Arms', 'Banana roll',
                 'Other',
             )},
            {'id': 'applicator', 'type': 'short_text',
             'label': 'Applicator / handpiece used'},
            {'id': 'cycles', 'type': 'number',
             'label': 'Number of cycles', 'required': True},
            {'id': 'cycle_duration_min', 'type': 'number',
             'label': 'Cycle duration (minutes)'},
            {'id': 'pre_measurements', 'type': 'long_text',
             'label': 'Pre-treatment measurements'},
            {'id': 'patient_discomfort', 'type': 'choice_single',
             'label': 'Patient discomfort (1–10)',
             'options': _options('1', '2', '3', '4', '5', '6', '7', '8', '9', '10')},
            {'id': 'side_effects', 'type': 'choice_multiple',
             'label': 'Side effects observed',
             'options': _options(
                 'Erythema', 'Edema', 'Bruising',
                 'Numbness', 'Tenderness', 'None',
             )},
            {'id': 'post_care_reviewed', 'type': 'choice_single',
             'label': 'Post-care + massage protocol reviewed',
             'required': True,
             'options': _options('Yes', 'No')},
            {'id': 'follow_up_weeks', 'type': 'number',
             'label': 'Follow-up consult in (weeks)'},
            {'id': 'provider_notes', 'type': 'long_text',
             'label': 'Provider notes'},
        ],
    },

    # ── Other ───────────────────────────────────────────────────────
    {
        'slug': 'general-treatment',
        'name': 'General treatment record',
        'description': (
            'Lightweight all-purpose template for treatments without '
            'a dedicated starter. SOAP-style: subjective, objective, '
            'assessment, plan.'
        ),
        'category': 'Other',
        'fields': [
            {'id': 'subjective', 'type': 'long_text',
             'label': 'Subjective — what the client reported',
             'required': True},
            {'id': 'objective', 'type': 'long_text',
             'label': 'Objective — observations + assessment',
             'required': True},
            {'id': 'treatment_performed', 'type': 'long_text',
             'label': 'Treatment performed',
             'required': True},
            {'id': 'products_used', 'type': 'long_text',
             'label': 'Products / equipment used (incl. lots)'},
            {'id': 'tolerance', 'type': 'choice_single',
             'label': 'Patient tolerance',
             'options': _options('Excellent', 'Good', 'Fair', 'Poor')},
            {'id': 'side_effects', 'type': 'long_text',
             'label': 'Side effects observed'},
            {'id': 'plan', 'type': 'long_text',
             'label': 'Plan — next steps, recommendations, follow-up'},
            {'id': 'provider_notes', 'type': 'long_text',
             'label': 'Additional notes'},
        ],
    },
]


def starter_template_by_slug(slug: str) -> StarterTemplate | None:
    """Lookup a starter by slug. Returns None when not found so the
    view can map cleanly to a 404."""
    for t in STARTER_TEMPLATES:
        if t['slug'] == slug:
            return t
    return None


def starter_template_to_schema(starter: StarterTemplate) -> dict:
    """Convert a starter to the same `schema` shape
    `TreatmentRecordTemplate.schema` accepts."""
    return {'fields': starter['fields']}
