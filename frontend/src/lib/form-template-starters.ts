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
    id: 'iv-therapy-consent',
    name: 'IV therapy consent',
    description:
      'Informed consent for intravenous vitamin / hydration / NAD+ therapy. Covers screening (kidney, heart, allergy history), risks (vein irritation, infection, vasovagal, electrolyte imbalance), and required acknowledgements.',
    form_type: 'consent',
    recurrence: 'per_visit',
    schema: {
      fields: [
        {
          id: 'about_iv_therapy',
          type: 'paragraph',
          label: 'About IV therapy',
          body: 'Intravenous (IV) therapy delivers fluids, vitamins, minerals, or other approved compounds directly into the bloodstream through a small catheter placed in a vein. Most clients tolerate IV therapy well and feel benefits within minutes to hours of the infusion. As with any medical procedure, however, there are risks.',
        },
        {
          id: 'pregnant_or_nursing',
          type: 'choice_single',
          label: 'Are you currently pregnant, trying to conceive, or breastfeeding?',
          required: true,
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes', label: 'Yes' },
            { value: 'unsure', label: 'Unsure' },
          ],
        },
        {
          id: 'medical_conditions_iv',
          type: 'choice_multiple',
          label: 'Do you have any of the following? (Select all that apply)',
          required: true,
          help_text: 'Some conditions are contraindications for IV therapy or require modified protocols.',
          options: [
            { value: 'kidney_disease', label: 'Kidney disease or impaired kidney function' },
            { value: 'heart_failure', label: 'Congestive heart failure or heart disease' },
            { value: 'high_blood_pressure', label: 'Uncontrolled high blood pressure' },
            { value: 'g6pd', label: 'G6PD deficiency' },
            { value: 'hemochromatosis', label: 'Hemochromatosis or iron-overload disorder' },
            { value: 'bleeding_disorder', label: 'Bleeding or clotting disorder' },
            { value: 'diabetes', label: 'Diabetes' },
            { value: 'thyroid_disease', label: 'Thyroid disease' },
            { value: 'liver_disease', label: 'Liver disease' },
            { value: 'cancer_active', label: 'Active cancer or chemotherapy' },
            { value: 'none', label: 'None of the above' },
          ],
        },
        {
          id: 'current_medications_iv',
          type: 'long_text',
          label: 'Current medications and supplements',
          required: true,
          help_text: 'Including blood thinners, diuretics, antihypertensives, and any prescription, OTC, or herbal supplements. Type "None" if applicable.',
        },
        {
          id: 'allergies_iv',
          type: 'long_text',
          label: 'Known allergies (medications, vitamins, latex, adhesives, foods)',
          required: true,
          help_text: 'Type "None" if you have no known allergies.',
        },
        {
          id: 'risks_disclosure',
          type: 'paragraph',
          label: 'Risks & complications',
          body: 'Common, generally minor: bruising, soreness, or swelling at the insertion site; cool sensation during infusion; temporary mineral or vitamin taste in the mouth; lightheadedness or vasovagal response. Less common: vein irritation (phlebitis) or inflammation; localized infection at the IV site; allergic reaction to one of the infused compounds (mild to severe, including anaphylaxis in rare cases); fluid overload or electrolyte imbalance (more likely with underlying heart, kidney, or liver disease); extravasation (the fluid leaks outside the vein, causing pain and tissue irritation). Rare but serious: severe allergic reaction; infiltration or vascular injury requiring further medical care; nerve injury; bloodstream infection. Notify your provider immediately if you experience chest pain, shortness of breath, severe swelling, hives, fainting, or any reaction that feels abnormal during or after the infusion.',
        },
        {
          id: 'risks_acknowledgment',
          type: 'choice_multiple',
          label: 'I acknowledge the following',
          required: true,
          options: [
            { value: 'read_risks', label: 'I have read and understand the risks described above' },
            { value: 'asked_questions', label: 'I have had the opportunity to ask questions and they have been answered' },
            { value: 'no_guarantee', label: 'I understand that no specific outcome or benefit is guaranteed' },
            { value: 'not_medical_advice', label: 'I understand IV therapy is not a substitute for medical care from my primary physician' },
            { value: 'medical_history_accurate', label: 'The medical information I have provided is accurate to the best of my knowledge' },
            { value: 'right_to_refuse', label: 'I understand I may refuse or stop the infusion at any time' },
          ],
        },
        {
          id: 'emergency_contact_iv',
          type: 'short_text',
          label: 'Emergency contact (name and phone)',
          required: true,
        },
        {
          id: 'signature',
          type: 'signature',
          label:
            'I voluntarily consent to IV therapy. I have read this consent form, my questions have been answered, and I understand the risks and benefits.',
          required: true,
        },
      ],
    },
  },

  {
    id: 'blood-draw-consent',
    name: 'Blood draw consent',
    description:
      'Informed consent for venipuncture / phlebotomy. Covers risks (hematoma, vasovagal, infection), pre-draw screening (blood thinners, fasting), and acknowledgements.',
    form_type: 'consent',
    recurrence: 'per_visit',
    schema: {
      fields: [
        {
          id: 'about_blood_draw',
          type: 'paragraph',
          label: 'About the procedure',
          body: 'Venipuncture is the standard method of collecting a blood sample, performed by inserting a small needle into a vein (typically in the arm). The sample is then sent to a clinical laboratory for the tests ordered by your provider. Blood draws are routine and most people experience no problems beyond a brief pinch.',
        },
        {
          id: 'blood_thinners_check',
          type: 'choice_single',
          label: 'Are you currently taking blood-thinning medications?',
          required: true,
          help_text: 'Including warfarin (Coumadin), apixaban (Eliquis), rivaroxaban (Xarelto), heparin, aspirin, clopidogrel (Plavix), or daily NSAIDs.',
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes', label: 'Yes — please tell your phlebotomist which one(s)' },
          ],
        },
        {
          id: 'bleeding_disorders_check',
          type: 'choice_single',
          label: 'Do you have a bleeding or clotting disorder (e.g. hemophilia, von Willebrand disease)?',
          required: true,
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes', label: 'Yes' },
          ],
        },
        {
          id: 'prior_reactions',
          type: 'choice_single',
          label: 'Have you ever fainted, felt dizzy, or had a severe reaction during a blood draw?',
          required: true,
          help_text: 'If yes, please tell the phlebotomist before the draw so they can take precautions (lying flat, slower draw, etc.).',
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes_fainted', label: 'Yes — I have fainted before' },
            { value: 'yes_dizzy', label: 'Yes — I have felt dizzy / lightheaded' },
            { value: 'yes_other', label: 'Yes — other reaction (please describe to your phlebotomist)' },
          ],
        },
        {
          id: 'latex_allergy',
          type: 'choice_single',
          label: 'Are you allergic to latex or adhesives?',
          required: true,
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes_latex', label: 'Yes — latex' },
            { value: 'yes_adhesive', label: 'Yes — adhesives / bandages' },
            { value: 'yes_both', label: 'Yes — both' },
          ],
        },
        {
          id: 'arm_history',
          type: 'long_text',
          label: 'Any arm / vein history we should know about?',
          required: false,
          help_text: 'Mastectomy with lymph node removal, prior IV infiltrations, dialysis access (AV fistula), difficult vein access in the past, etc. Type "None" if not applicable.',
        },
        {
          id: 'blood_draw_risks',
          type: 'paragraph',
          label: 'Risks of venipuncture',
          body: 'Common, generally minor: brief discomfort at the needle insertion site; small bruise (hematoma) at the draw site lasting a few days; lightheadedness or fainting (vasovagal response). Uncommon: prolonged bleeding (more likely on blood thinners); nerve irritation causing temporary numbness, tingling, or shooting pain in the arm; localized infection at the puncture site; vein scarring or collapse with repeat draws. Rare: significant hematoma or arterial puncture requiring further medical care; persistent nerve injury. Tell your phlebotomist immediately if you feel faint, develop persistent sharp pain or numbness during or after the draw, or notice significant swelling.',
        },
        {
          id: 'aftercare_blood_draw',
          type: 'paragraph',
          label: 'Aftercare',
          body: 'Keep the bandage on for at least 15 minutes. Avoid heavy lifting or strenuous use of the arm for the next few hours. Apply gentle pressure if any bleeding restarts and elevate the arm. If you develop significant swelling, persistent pain, or signs of infection (redness, warmth, drainage, fever), contact the clinic or your primary provider.',
        },
        {
          id: 'risks_acknowledgment_bd',
          type: 'choice_multiple',
          label: 'I acknowledge the following',
          required: true,
          options: [
            { value: 'read_risks', label: 'I have read and understand the risks described above' },
            { value: 'asked_questions', label: 'My questions have been answered to my satisfaction' },
            { value: 'medical_history_accurate', label: 'The medical information I have provided is accurate to the best of my knowledge' },
            { value: 'right_to_refuse', label: 'I understand I may withdraw consent at any time before the draw' },
            { value: 'lab_results', label: 'I understand my results will be released to the ordering provider and used to inform my care' },
          ],
        },
        {
          id: 'signature',
          type: 'signature',
          label:
            'I voluntarily consent to the blood draw described above and authorize the laboratory testing ordered by my provider.',
          required: true,
        },
      ],
    },
  },

  {
    id: 'patient-insurance',
    name: 'Patient insurance & financial agreement',
    description:
      'Insurance intake + financial responsibility + HIPAA-authorized disclosure. Captures primary / secondary insurance, payment responsibility, and patient authorization to bill and release information to the carrier.',
    form_type: 'intake',
    recurrence: 'once',
    schema: {
      fields: [
        {
          id: 'insurance_intro',
          type: 'paragraph',
          label: 'Insurance & financial responsibility',
          body: 'Please provide your current insurance information. You are responsible for verifying that our providers are in-network with your plan and for any amounts your carrier does not cover (deductibles, copays, coinsurance, and non-covered services). If you have no insurance coverage, write "Self-pay" below.',
        },
        {
          id: 'has_insurance',
          type: 'choice_single',
          label: 'Insurance status',
          required: true,
          options: [
            { value: 'primary_only', label: 'I have primary insurance only' },
            { value: 'primary_secondary', label: 'I have primary and secondary insurance' },
            { value: 'self_pay', label: 'Self-pay (no insurance)' },
          ],
        },
        {
          id: 'primary_carrier',
          type: 'short_text',
          label: 'Primary insurance — carrier name',
          required: false,
          help_text: 'Leave blank if self-pay.',
        },
        {
          id: 'primary_member_id',
          type: 'short_text',
          label: 'Primary insurance — member / subscriber ID',
          required: false,
        },
        {
          id: 'primary_group',
          type: 'short_text',
          label: 'Primary insurance — group number',
          required: false,
        },
        {
          id: 'primary_holder',
          type: 'short_text',
          label: 'Primary insurance — policyholder name (if not you)',
          required: false,
          help_text: 'Leave blank if you are the policyholder.',
        },
        {
          id: 'primary_holder_dob',
          type: 'date',
          label: 'Primary policyholder date of birth (if not you)',
          required: false,
        },
        {
          id: 'primary_holder_relation',
          type: 'choice_single',
          label: 'Relationship to policyholder',
          required: false,
          options: [
            { value: 'self', label: 'Self' },
            { value: 'spouse', label: 'Spouse / domestic partner' },
            { value: 'parent', label: 'Parent' },
            { value: 'child', label: 'Child' },
            { value: 'other', label: 'Other' },
          ],
        },
        {
          id: 'secondary_carrier',
          type: 'short_text',
          label: 'Secondary insurance — carrier name (if applicable)',
          required: false,
        },
        {
          id: 'secondary_member_id',
          type: 'short_text',
          label: 'Secondary insurance — member / subscriber ID',
          required: false,
        },
        {
          id: 'secondary_group',
          type: 'short_text',
          label: 'Secondary insurance — group number',
          required: false,
        },
        {
          id: 'financial_responsibility',
          type: 'paragraph',
          label: 'Financial responsibility',
          body: 'I understand that I am financially responsible for all services provided to me, regardless of insurance coverage. Charges not covered by insurance — including deductibles, copays, coinsurance, services deemed not medically necessary, and out-of-network charges — are my responsibility. Payment for self-pay services and patient portions is due at the time of service unless other arrangements have been made in writing.',
        },
        {
          id: 'assignment_of_benefits',
          type: 'paragraph',
          label: 'Assignment of benefits',
          body: 'I authorize my insurance benefits to be paid directly to this practice for services provided to me. I understand that any balance not covered by insurance will be my responsibility.',
        },
        {
          id: 'hipaa_disclosure_authorization',
          type: 'paragraph',
          label: 'HIPAA-authorized disclosure',
          body: 'Under the Health Insurance Portability and Accountability Act (HIPAA), I authorize this practice to release the minimum necessary protected health information (PHI) to my insurance carrier(s), their agents, and any third-party payor or clearinghouse for the purposes of: (1) processing claims for payment, (2) obtaining authorizations or referrals required by my plan, (3) coordinating benefits between primary and secondary carriers, and (4) any healthcare operations directly related to my treatment and payment. This authorization remains in effect for the duration of my care unless I revoke it in writing. A copy of this authorization is as valid as the original.',
        },
        {
          id: 'agreements',
          type: 'choice_multiple',
          label: 'I agree to the following',
          required: true,
          options: [
            { value: 'financial_resp', label: 'I accept financial responsibility as described above' },
            { value: 'assignment', label: 'I authorize the assignment of insurance benefits' },
            { value: 'hipaa_release', label: 'I authorize the HIPAA-permitted disclosures described above' },
            { value: 'accurate', label: 'The insurance information I have provided is accurate to the best of my knowledge' },
            { value: 'update', label: 'I will notify the practice promptly of any changes to my insurance or contact information' },
          ],
        },
        {
          id: 'signature',
          type: 'signature',
          label:
            'I have read, understand, and agree to the financial and HIPAA-authorization terms above.',
          required: true,
        },
      ],
    },
  },

  {
    id: 'medical-history',
    name: 'Medical history intake',
    description:
      'Comprehensive new-patient medical history: allergies, current medications, conditions, surgical history, family history, and lifestyle. Asked once on the first appointment ever; updated periodically.',
    form_type: 'intake',
    recurrence: 'once',
    schema: {
      fields: [
        {
          id: 'history_intro',
          type: 'paragraph',
          label: 'About this form',
          body: 'This information helps your provider deliver safe, personalized care. All responses are confidential and protected under HIPAA. Please answer to the best of your knowledge — if you are unsure, write "Unknown" rather than guessing.',
        },
        {
          id: 'allergies_meds',
          type: 'long_text',
          label: 'Medication allergies',
          required: true,
          help_text: 'List the medication and the reaction (e.g. "Penicillin — hives"). Type "None" if you have no known medication allergies.',
        },
        {
          id: 'allergies_other',
          type: 'long_text',
          label: 'Other allergies (latex, foods, environmental, etc.)',
          required: true,
          help_text: 'Type "None" if not applicable.',
        },
        {
          id: 'current_medications',
          type: 'long_text',
          label: 'Current medications and supplements',
          required: true,
          help_text: 'Include prescription, over-the-counter, vitamins, herbal supplements. Dose and frequency if known. Type "None" if applicable.',
        },
        {
          id: 'medical_conditions_history',
          type: 'choice_multiple',
          label: 'Have you ever been diagnosed with any of the following? (Select all that apply)',
          required: true,
          options: [
            { value: 'high_blood_pressure', label: 'High blood pressure (hypertension)' },
            { value: 'high_cholesterol', label: 'High cholesterol' },
            { value: 'heart_disease', label: 'Heart disease (heart attack, angina, CHF)' },
            { value: 'stroke_tia', label: 'Stroke or TIA' },
            { value: 'diabetes', label: 'Diabetes (Type 1 or 2)' },
            { value: 'thyroid', label: 'Thyroid disorder' },
            { value: 'kidney_disease', label: 'Kidney disease' },
            { value: 'liver_disease', label: 'Liver disease or hepatitis' },
            { value: 'asthma_copd', label: 'Asthma or COPD' },
            { value: 'autoimmune', label: 'Autoimmune disorder (lupus, RA, MS, etc.)' },
            { value: 'cancer', label: 'Cancer (any type)' },
            { value: 'bleeding_disorder', label: 'Bleeding or clotting disorder' },
            { value: 'mental_health', label: 'Anxiety, depression, or other mental health condition' },
            { value: 'seizures', label: 'Seizures or epilepsy' },
            { value: 'hsv', label: 'Cold sores / herpes simplex' },
            { value: 'none', label: 'None of the above' },
          ],
        },
        {
          id: 'conditions_details',
          type: 'long_text',
          label: 'Details on any condition checked above',
          required: false,
          help_text: 'Diagnosis date, current status, and any specialists you see.',
        },
        {
          id: 'surgical_history',
          type: 'long_text',
          label: 'Surgical history',
          required: true,
          help_text: 'List prior surgeries with approximate year. Type "None" if not applicable.',
        },
        {
          id: 'hospitalizations',
          type: 'long_text',
          label: 'Hospitalizations not related to surgery',
          required: false,
          help_text: 'Year and reason. Type "None" if not applicable.',
        },
        {
          id: 'pregnancy_status',
          type: 'choice_single',
          label: 'Pregnancy status',
          required: true,
          options: [
            { value: 'not_applicable', label: 'Not applicable' },
            { value: 'not_pregnant', label: 'Not pregnant / not nursing' },
            { value: 'pregnant', label: 'Currently pregnant' },
            { value: 'nursing', label: 'Currently breastfeeding' },
            { value: 'trying', label: 'Trying to conceive' },
          ],
        },
        {
          id: 'family_history',
          type: 'choice_multiple',
          label: 'Family history (parents, siblings, grandparents)',
          required: false,
          options: [
            { value: 'heart_disease', label: 'Heart disease before age 55' },
            { value: 'stroke', label: 'Stroke' },
            { value: 'cancer', label: 'Cancer' },
            { value: 'diabetes', label: 'Diabetes' },
            { value: 'autoimmune', label: 'Autoimmune disorder' },
            { value: 'bleeding_disorder', label: 'Bleeding or clotting disorder' },
            { value: 'mental_health', label: 'Mental health condition' },
            { value: 'none', label: 'None of the above' },
          ],
        },
        {
          id: 'tobacco_use',
          type: 'choice_single',
          label: 'Tobacco use',
          required: true,
          options: [
            { value: 'never', label: 'Never' },
            { value: 'former', label: 'Former — quit' },
            { value: 'current_occasional', label: 'Currently — occasional' },
            { value: 'current_daily', label: 'Currently — daily' },
          ],
        },
        {
          id: 'alcohol_use',
          type: 'choice_single',
          label: 'Alcohol use',
          required: true,
          options: [
            { value: 'none', label: 'None' },
            { value: 'occasional', label: 'Occasional (< 1 drink/week)' },
            { value: 'moderate', label: 'Moderate (1–7 drinks/week)' },
            { value: 'heavy', label: 'Heavy (> 7 drinks/week)' },
          ],
        },
        {
          id: 'recreational_drug_use',
          type: 'choice_single',
          label: 'Recreational drug use',
          required: false,
          help_text: 'Information is confidential and only used to inform safe care.',
          options: [
            { value: 'no', label: 'No' },
            { value: 'yes', label: 'Yes — willing to discuss with provider' },
            { value: 'prefer_not_say', label: 'Prefer not to say' },
          ],
        },
        {
          id: 'accuracy_attestation',
          type: 'choice_single',
          label: 'I attest that the information above is accurate to the best of my knowledge',
          required: true,
          help_text: 'Please update us at future visits if anything changes.',
          options: [
            { value: 'agree', label: 'I agree' },
          ],
        },
        {
          id: 'signature',
          type: 'signature',
          label:
            'I confirm that this medical history is accurate and complete to the best of my knowledge.',
          required: true,
        },
      ],
    },
  },

  {
    id: 'post-treatment-followup',
    name: 'Post-treatment follow-up & notes',
    description:
      'General post-care acknowledgement + structured follow-up: how the area is healing, any side effects, and free-text notes. Use after any treatment to capture client-reported outcomes.',
    form_type: 'consent',
    recurrence: 'per_visit',
    schema: {
      fields: [
        {
          id: 'about_post_treatment',
          type: 'paragraph',
          label: 'Post-treatment care',
          body: 'You have completed your treatment today. This form gathers your post-care acknowledgement and gives you a place to share how the treated area is responding. Following the aftercare instructions below protects your results and helps reduce the risk of complications.',
        },
        {
          id: 'aftercare_instructions',
          type: 'paragraph',
          label: 'Aftercare instructions',
          body: '• Avoid touching, rubbing, or applying pressure to the treated area for at least 24 hours.\n• Avoid strenuous exercise, hot showers, saunas, and steam rooms for the first 24 hours.\n• Avoid direct sun exposure on the treated area; use SPF 30+ for at least 2 weeks.\n• Apply any topical products provided by your provider as directed.\n• Avoid alcohol and blood-thinning medications (aspirin, ibuprofen, fish oil) for 24 hours unless prescribed.\n• If the treated area is on your face, sleep elevated on your back the first night.\n• Some redness, swelling, tenderness, or mild bruising is normal and usually resolves within 24–72 hours.',
        },
        {
          id: 'warning_signs',
          type: 'paragraph',
          label: 'When to call us',
          body: 'Call the clinic right away if you experience: severe or worsening pain not relieved by Tylenol; significant swelling or asymmetry; skin color changes (white, gray, dusky, or blue-ish) at the treated area; signs of infection (increasing redness, warmth, pus, fever); blistering or open wounds; vision changes (if treated near the eyes); or any reaction that feels abnormal. After clinic hours, go to your nearest urgent care or emergency department for any severe or rapidly progressing symptom.',
        },
        {
          id: 'how_area_feels',
          type: 'choice_single',
          label: 'How does the treated area feel right now?',
          required: true,
          options: [
            { value: 'normal', label: 'Normal — no pain or unusual sensation' },
            { value: 'mild', label: 'Mildly tender / sore (expected)' },
            { value: 'moderate', label: 'Moderately uncomfortable' },
            { value: 'significant', label: 'Significant pain or discomfort (notify your provider)' },
          ],
        },
        {
          id: 'side_effects_observed',
          type: 'choice_multiple',
          label: 'Any side effects you have noticed? (Select all that apply)',
          required: false,
          options: [
            { value: 'redness', label: 'Redness' },
            { value: 'swelling', label: 'Swelling' },
            { value: 'bruising', label: 'Bruising' },
            { value: 'tenderness', label: 'Tenderness or soreness' },
            { value: 'itching', label: 'Itching' },
            { value: 'headache', label: 'Headache' },
            { value: 'dizziness', label: 'Dizziness or lightheadedness' },
            { value: 'nausea', label: 'Nausea' },
            { value: 'none', label: 'None of the above' },
          ],
        },
        {
          id: 'provider_notes',
          type: 'long_text',
          label: 'Notes for your provider (optional)',
          required: false,
          help_text: 'Anything else you want the team to know about how the treatment went or how the area is responding.',
        },
        {
          id: 'aftercare_received',
          type: 'choice_multiple',
          label: 'I acknowledge',
          required: true,
          options: [
            { value: 'received_instructions', label: 'I received and understand the aftercare instructions' },
            { value: 'asked_questions', label: 'I had the opportunity to ask questions about my treatment and aftercare' },
            { value: 'know_when_to_call', label: 'I understand when to contact the clinic with concerns' },
            { value: 'follow_up_understood', label: 'I understand any recommended follow-up visits and their purpose' },
          ],
        },
        {
          id: 'signature',
          type: 'signature',
          label:
            'I confirm I received post-treatment instructions and have reported the information above accurately.',
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
