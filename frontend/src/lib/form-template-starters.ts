/**
 * Curated starter templates for the form builder.
 *
 * Surfaced as a picker on `/forms/new` — operators choose a starter
 * (e.g. "Botox consent") to pre-fill the builder rather than starting
 * from blank. After picking, they edit + customize before saving.
 * Nothing is persisted until they hit Save, and each starter is
 * marked as "review with your medical director / legal counsel"
 * before activation.
 *
 * **Important.** These starters include common-knowledge medspa
 * intake / consent structure. They are NOT legal advice and are NOT
 * jurisdiction-aware. Clinics should:
 *
 *   1. Have their medical director review the risks + acknowledgements.
 *   2. Have an attorney review the language for their state(s).
 *   3. Add jurisdiction-specific disclosures (CA, NY, FL all have
 *      additional informed-consent requirements for medical
 *      aesthetics).
 *
 * The builder shows a yellow disclaimer banner whenever a starter is
 * loaded so the operator never forgets this responsibility.
 *
 * Adding a new starter:
 *   - Append to STARTERS below with a stable string `id`.
 *   - Use the same field types the schema validator accepts
 *     (`short_text`, `long_text`, `choice_single`, `choice_multiple`,
 *     `date`, `signature`).
 *   - End with a `signature` field — that's the actual signing block.
 *   - Match the `recurrence` to the form's purpose (intake → 'once';
 *     clinical consent → 'per_visit').
 */

import type {
  FormSchema,
  FormType,
  Recurrence,
} from './form-templates';

export interface FormTemplateStarter {
  /** Stable identifier — used in `/forms/new?starter={id}` to remember
   *  which starter was picked. */
  id: string;
  /** Display name shown on the picker card and pre-filled into the
   *  template's `name` field. Operators usually rename anyway. */
  name: string;
  /** Short description shown on the picker card. */
  description: string;
  /** Default form type — drives the recurrence default and decides
   *  whether the service-mapping section shows. */
  form_type: FormType;
  /** Default recurrence. */
  recurrence: Recurrence;
  /** Pre-built schema. Operator edits in the builder before saving. */
  schema: FormSchema;
}

export const STARTERS: FormTemplateStarter[] = [
  // ── Intake ──────────────────────────────────────────────────────

  {
    id: 'general-intake',
    name: 'New client intake',
    description:
      "Standard first-visit intake — contact details, emergency contact, basic medical history, allergies, and photo / no-show acknowledgements. Asked once on the client's first appointment ever.",
    form_type: 'intake',
    recurrence: 'once',
    schema: {
      fields: [
        {
          id: 'date_of_birth',
          type: 'date',
          label: 'Date of birth',
          required: true,
          help_text: 'Required for age-restricted treatments and identity verification.',
        },
        {
          id: 'emergency_contact_name',
          type: 'short_text',
          label: 'Emergency contact — name',
          required: true,
        },
        {
          id: 'emergency_contact_phone',
          type: 'short_text',
          label: 'Emergency contact — phone',
          required: true,
        },
        {
          id: 'how_did_you_hear',
          type: 'choice_single',
          label: 'How did you hear about us?',
          required: false,
          options: [
            { value: 'instagram', label: 'Instagram' },
            { value: 'tiktok', label: 'TikTok' },
            { value: 'google', label: 'Google search' },
            { value: 'referral', label: 'Friend or family referral' },
            { value: 'walk_in', label: 'Walked by / saw the location' },
            { value: 'other', label: 'Other' },
          ],
        },
        {
          id: 'medical_conditions',
          type: 'choice_multiple',
          label: 'Do you have any of the following? (Select all that apply)',
          required: true,
          help_text: 'Some treatments require additional precautions or are contraindicated with these conditions.',
          options: [
            { value: 'pregnancy', label: 'Currently pregnant or nursing' },
            { value: 'autoimmune', label: 'Autoimmune disorder' },
            { value: 'bleeding_disorder', label: 'Bleeding or clotting disorder' },
            { value: 'keloid', label: 'History of keloid scarring' },
            { value: 'cold_sores', label: 'History of cold sores / herpes' },
            { value: 'cancer_active', label: 'Active cancer or treatment' },
            { value: 'none', label: 'None of the above' },
          ],
        },
        {
          id: 'allergies',
          type: 'long_text',
          label: 'Allergies (medications, latex, anesthetics, etc.)',
          required: true,
          help_text: 'Type "None" if you have no known allergies.',
        },
        {
          id: 'medications',
          type: 'long_text',
          label: 'Current medications and supplements',
          required: true,
          help_text: 'Including blood thinners (aspirin, ibuprofen, fish oil), accutane, antibiotics, and any topical retinoids. Type "None" if applicable.',
        },
        {
          id: 'recent_aesthetic_procedures',
          type: 'long_text',
          label: 'Aesthetic procedures in the last 6 months',
          required: false,
          help_text: 'Botox, fillers, lasers, peels, etc. Includes location and approximate date.',
        },
        {
          id: 'photo_consent',
          type: 'choice_single',
          label: 'Photo consent',
          required: true,
          help_text: 'We may take before / after photos for your chart record. May we also use them anonymously (face cropped or blurred) for training and marketing?',
          options: [
            { value: 'chart_only', label: 'Yes for chart records only' },
            { value: 'chart_and_marketing', label: 'Yes for both chart and anonymous marketing use' },
            { value: 'no_photos', label: 'No photos at all' },
          ],
        },
        {
          id: 'cancellation_policy_ack',
          type: 'choice_single',
          label: 'Cancellation policy',
          required: true,
          help_text: 'I understand that appointments cancelled within 24 hours or no-shows may be charged a fee.',
          options: [
            { value: 'agree', label: 'I agree' },
          ],
        },
        {
          id: 'signature',
          type: 'signature',
          label: 'I confirm the information above is accurate to the best of my knowledge.',
          required: true,
        },
      ],
    },
  },

  // ── Consent ─────────────────────────────────────────────────────

  {
    id: 'botox-consent',
    name: 'Botox / neurotoxin consent',
    description:
      'Informed consent for botulinum toxin treatments (Botox, Dysport, Xeomin, Jeuveau). Pre-treatment screening + risk acknowledgements + signature.',
    form_type: 'consent',
    recurrence: 'per_visit',
    schema: {
      fields: [
        {
          id: 'pregnant_or_nursing',
          type: 'choice_single',
          label: 'Are you currently pregnant or nursing?',
          required: true,
          help_text: 'Neurotoxin treatments are contraindicated during pregnancy and breastfeeding.',
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes', label: 'Yes' },
            { value: 'unsure', label: 'Unsure' },
          ],
        },
        {
          id: 'recent_neurotoxin',
          type: 'choice_single',
          label: 'Have you received any neurotoxin treatment in the last 3 months?',
          required: true,
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes', label: 'Yes — please tell your provider what / when' },
          ],
        },
        {
          id: 'blood_thinners_recent',
          type: 'choice_single',
          label: 'Have you taken blood thinners or anti-inflammatories in the last 7 days?',
          required: true,
          help_text: 'Aspirin, ibuprofen, fish oil, vitamin E, etc. These increase bruising risk.',
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes', label: 'Yes' },
          ],
        },
        {
          id: 'risks_understood',
          type: 'choice_multiple',
          label: 'I understand the following risks and have had the opportunity to ask questions',
          required: true,
          options: [
            { value: 'bruising_swelling', label: 'Bruising, swelling, or tenderness at injection sites' },
            { value: 'headache', label: 'Mild headache for 24–48 hours' },
            { value: 'asymmetry', label: 'Possible asymmetry of results' },
            { value: 'eyelid_brow_droop', label: 'Eyelid or brow drooping (rare; temporary, weeks to months)' },
            { value: 'allergic_reaction', label: 'Allergic reaction (rare)' },
            { value: 'no_guaranteed_outcome', label: 'No guaranteed outcome — touch-ups may be needed and are at additional cost' },
            { value: 'onset_time', label: 'Results take 3–14 days to fully appear' },
            { value: 'duration', label: 'Effects last approximately 3–4 months and require maintenance' },
          ],
        },
        {
          id: 'aftercare_understood',
          type: 'choice_single',
          label: 'I have received and understand the post-treatment aftercare instructions',
          required: true,
          help_text: 'No lying down for 4 hours, no exercise / heat exposure for 24 hours, do not massage the treated area.',
          options: [
            { value: 'agree', label: 'I agree' },
          ],
        },
        {
          id: 'questions_addressed',
          type: 'long_text',
          label: 'Any questions or concerns? (Optional)',
          required: false,
          help_text: 'Note any specific concerns for your provider.',
        },
        {
          id: 'signature',
          type: 'signature',
          label:
            "I have read this form, my questions have been answered, and I consent to receive neurotoxin treatment.",
          required: true,
        },
      ],
    },
  },

  {
    id: 'filler-consent',
    name: 'Dermal filler consent',
    description:
      'Informed consent for hyaluronic acid dermal fillers (Juvederm, Restylane, etc.). Covers screening, risks specific to fillers (vascular occlusion, granulomas), and aftercare.',
    form_type: 'consent',
    recurrence: 'per_visit',
    schema: {
      fields: [
        {
          id: 'pregnant_or_nursing',
          type: 'choice_single',
          label: 'Are you currently pregnant or nursing?',
          required: true,
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes', label: 'Yes' },
            { value: 'unsure', label: 'Unsure' },
          ],
        },
        {
          id: 'history_filler',
          type: 'choice_single',
          label: 'Have you had dermal fillers before?',
          required: true,
          options: [
            { value: 'never', label: 'Never' },
            { value: 'within_year', label: 'Yes — within the past year' },
            { value: 'over_year', label: 'Yes — more than a year ago' },
          ],
        },
        {
          id: 'previous_reactions',
          type: 'long_text',
          label: 'Any previous reactions to filler, lidocaine, or hyaluronic acid?',
          required: true,
          help_text: 'Type "None" if not applicable.',
        },
        {
          id: 'cold_sores',
          type: 'choice_single',
          label: 'Do you have a history of cold sores (HSV-1)?',
          required: true,
          help_text: 'Filler injection can trigger an outbreak; antiviral prophylaxis may be recommended.',
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes', label: 'Yes' },
          ],
        },
        {
          id: 'risks_understood',
          type: 'choice_multiple',
          label: 'I understand the following risks',
          required: true,
          options: [
            { value: 'bruising_swelling', label: 'Bruising, swelling, redness, tenderness — usually 3–7 days' },
            { value: 'lumps_unevenness', label: 'Temporary lumps, bumps, or unevenness (massage / dissolution may be needed)' },
            { value: 'asymmetry', label: 'Possible asymmetry; touch-ups at additional cost' },
            { value: 'allergic_reaction', label: 'Allergic reaction (rare)' },
            { value: 'infection', label: 'Infection at injection site (rare)' },
            { value: 'vascular_occlusion', label: 'Vascular occlusion — a serious complication that can cause skin necrosis or vision loss (very rare; my provider has reversal agents on hand)' },
            { value: 'no_guarantee', label: 'No guaranteed result; longevity varies (6–18 months depending on product and area)' },
          ],
        },
        {
          id: 'reversal_understood',
          type: 'choice_single',
          label: 'I understand hyaluronic acid filler can be partially or fully dissolved with hyaluronidase if needed',
          required: true,
          options: [
            { value: 'agree', label: 'I agree' },
          ],
        },
        {
          id: 'aftercare_understood',
          type: 'choice_single',
          label: 'I have received post-treatment aftercare instructions',
          required: true,
          help_text: 'Avoid strenuous exercise for 24 hours, sleep elevated for first night, no facials / makeup for 24 hours, gentle cleansing only.',
          options: [
            { value: 'agree', label: 'I agree' },
          ],
        },
        {
          id: 'signature',
          type: 'signature',
          label:
            "I have read this form, my questions have been answered, and I consent to receive dermal filler treatment.",
          required: true,
        },
      ],
    },
  },

  {
    id: 'laser-consent',
    name: 'Laser treatment consent',
    description:
      'General-purpose laser treatment consent (hair removal, IPL, photo-rejuvenation). Covers skin-type screening, sun-exposure history, and laser-specific risks (burns, hyperpigmentation).',
    form_type: 'consent',
    recurrence: 'per_visit',
    schema: {
      fields: [
        {
          id: 'recent_sun_exposure',
          type: 'choice_single',
          label: 'Have you had significant sun exposure or used self-tanner in the last 4 weeks?',
          required: true,
          help_text: 'Tanned skin is a contraindication for many laser treatments — risk of burns and hyperpigmentation.',
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes', label: 'Yes' },
          ],
        },
        {
          id: 'recent_accutane',
          type: 'choice_single',
          label: 'Have you taken Accutane (isotretinoin) in the last 6 months?',
          required: true,
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes', label: 'Yes' },
          ],
        },
        {
          id: 'photosensitizing_medications',
          type: 'long_text',
          label: 'List any photosensitizing medications you currently take',
          required: true,
          help_text: 'Including some antibiotics (doxycycline, ciprofloxacin), retinoids, certain antidepressants, etc. Type "None" if applicable.',
        },
        {
          id: 'risks_understood',
          type: 'choice_multiple',
          label: 'I understand the following risks',
          required: true,
          options: [
            { value: 'discomfort', label: 'Discomfort during treatment (warm / snapping sensation)' },
            { value: 'redness_swelling', label: 'Redness and swelling for 24–72 hours' },
            { value: 'hyper_hypo_pigmentation', label: 'Temporary or permanent skin lightening or darkening' },
            { value: 'blistering_burns', label: 'Blistering or burns (rare; minimized by proper settings)' },
            { value: 'scarring', label: 'Scarring (very rare)' },
            { value: 'eye_protection', label: 'Eye protection is mandatory throughout the treatment' },
            { value: 'multiple_sessions', label: 'Multiple sessions are required for full results' },
            { value: 'no_guarantee', label: 'No guaranteed outcome; results vary by skin and hair type' },
          ],
        },
        {
          id: 'sun_avoidance_ack',
          type: 'choice_single',
          label: 'I will avoid direct sun exposure on the treated area for at least 2 weeks post-treatment and use SPF 30+',
          required: true,
          options: [
            { value: 'agree', label: 'I agree' },
          ],
        },
        {
          id: 'signature',
          type: 'signature',
          label:
            "I have read this form, my questions have been answered, and I consent to receive laser treatment.",
          required: true,
        },
      ],
    },
  },

  {
    id: 'photo-release',
    name: 'Photo & marketing release',
    description:
      'Standalone consent for using before / after photos in marketing materials (Instagram, website, in-clinic displays). Separate from chart-record photos collected at every visit.',
    form_type: 'consent',
    recurrence: 'once',
    schema: {
      fields: [
        {
          id: 'use_scope',
          type: 'choice_multiple',
          label: 'I authorize use of my before / after photos for the following purposes',
          required: true,
          help_text: "Choose any combination. You can revoke this consent at any time by contacting the spa.",
          options: [
            { value: 'instagram', label: 'Instagram and TikTok posts' },
            { value: 'website', label: 'Spa website (gallery, testimonials)' },
            { value: 'in_clinic', label: 'In-clinic displays and brochures' },
            { value: 'training', label: 'Provider training and continuing education' },
            { value: 'paid_ads', label: 'Paid digital advertising (Meta, Google, etc.)' },
          ],
        },
        {
          id: 'face_visibility',
          type: 'choice_single',
          label: 'How should my face appear?',
          required: true,
          options: [
            { value: 'fully_visible', label: 'Fully visible (full face)' },
            { value: 'cropped', label: 'Cropped (treated area only — eyes / mouth not shown)' },
            { value: 'blurred', label: 'Blurred / anonymized so I am not recognizable' },
          ],
        },
        {
          id: 'name_attribution',
          type: 'choice_single',
          label: 'May we use your first name with the photos?',
          required: true,
          options: [
            { value: 'no', label: 'No — anonymous only' },
            { value: 'first_name', label: 'Yes, first name only' },
          ],
        },
        {
          id: 'compensation_understood',
          type: 'choice_single',
          label: 'I understand I will not receive payment or other compensation for use of these photos',
          required: true,
          options: [
            { value: 'agree', label: 'I agree' },
          ],
        },
        {
          id: 'signature',
          type: 'signature',
          label:
            "I authorize the use of my photos as described above. I understand I may revoke this consent in writing at any time, and existing uses prior to revocation are not affected.",
          required: true,
        },
      ],
    },
  },
];

/** Look up a starter by id. Returns undefined for unknown ids
 *  (e.g. an old `?starter=` URL referencing a removed starter). */
export function getStarter(id: string): FormTemplateStarter | undefined {
  return STARTERS.find((s) => s.id === id);
}

/** Group starters by `form_type` for the picker UI. */
export function startersByType(): Record<FormType, FormTemplateStarter[]> {
  return {
    intake: STARTERS.filter((s) => s.form_type === 'intake'),
    consent: STARTERS.filter((s) => s.form_type === 'consent'),
  };
}
