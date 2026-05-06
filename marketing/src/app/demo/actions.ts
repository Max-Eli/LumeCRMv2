/**
 * Server action for the marketing-site demo request form.
 *
 * Sends a plain-text email to `CONTACT_FORM_TO_EMAIL` via Resend.
 * Designed to be a Vercel-deployable serverless function — no DB,
 * no PHI, no auth.
 *
 * Required env vars on Vercel:
 *   RESEND_API_KEY        - From https://resend.com/api-keys
 *   CONTACT_FORM_TO_EMAIL - Inbox that receives the lead. Production
 *                           value: codenestwebstudios@gmail.com
 *   CONTACT_FORM_FROM     - Verified sender address. Until your
 *                           sending domain is verified in Resend,
 *                           this can be `onboarding@resend.dev`
 *                           (Resend's testing sender). After domain
 *                           verification, switch to e.g.
 *                           `demo-requests@<your-domain>`.
 *
 * If `RESEND_API_KEY` is unset, the action falls back to a stub
 * mode: it logs the lead to the server console and pretends success.
 * Lets local-dev work without a key. Production deploys without
 * the key would silently swallow leads — that's acceptable for
 * now since the deploy will fail loudly if env vars are missing
 * and we intend to set them in Vercel.
 */

'use server';

import { Resend } from 'resend';

export interface DemoRequestState {
  status: 'idle' | 'success' | 'error';
  message: string;
}

export const INITIAL_STATE: DemoRequestState = {
  status: 'idle',
  message: '',
};

interface DemoRequestPayload {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  spa_name: string;
  locations: string;
  providers: string;
  current_software: string;
  message: string;
}

function pull(formData: FormData, key: string): string {
  const v = formData.get(key);
  return typeof v === 'string' ? v.trim() : '';
}

function validate(data: DemoRequestPayload): string | null {
  if (!data.first_name) return 'First name is required.';
  if (!data.last_name) return 'Last name is required.';
  if (!data.email) return 'Email is required.';
  if (!/.+@.+\..+/.test(data.email)) return 'Enter a valid email address.';
  if (!data.spa_name) return 'Spa name is required.';
  return null;
}

function renderText(data: DemoRequestPayload): string {
  return [
    `New demo request from ${data.first_name} ${data.last_name}`,
    '',
    `Spa: ${data.spa_name}`,
    `Email: ${data.email}`,
    data.phone ? `Phone: ${data.phone}` : null,
    data.locations ? `Locations: ${data.locations}` : null,
    data.providers ? `Providers: ${data.providers}` : null,
    data.current_software
      ? `Currently using: ${data.current_software}`
      : null,
    '',
    data.message ? 'Message:' : null,
    data.message ? data.message : null,
  ]
    .filter((line) => line !== null)
    .join('\n');
}

export async function sendDemoRequest(
  _prev: DemoRequestState,
  formData: FormData,
): Promise<DemoRequestState> {
  const data: DemoRequestPayload = {
    first_name: pull(formData, 'first_name'),
    last_name: pull(formData, 'last_name'),
    email: pull(formData, 'email'),
    phone: pull(formData, 'phone'),
    spa_name: pull(formData, 'spa_name'),
    locations: pull(formData, 'locations'),
    providers: pull(formData, 'providers'),
    current_software: pull(formData, 'current_software'),
    message: pull(formData, 'message'),
  };

  const validationError = validate(data);
  if (validationError) {
    return { status: 'error', message: validationError };
  }

  const apiKey = process.env.RESEND_API_KEY;
  const to = process.env.CONTACT_FORM_TO_EMAIL;
  const from =
    process.env.CONTACT_FORM_FROM
    ?? 'Lumè Demo Requests <onboarding@resend.dev>';

  // Local-dev fallback: log + pretend success when key is missing.
  // Lets `npm run dev` work without leaking keys into the repo.
  if (!apiKey || !to) {
    console.warn(
      '[sendDemoRequest] RESEND_API_KEY or CONTACT_FORM_TO_EMAIL not set — stub mode.',
    );
    console.log(renderText(data));
    return {
      status: 'success',
      message: "Thanks — we'll be in touch.",
    };
  }

  try {
    const resend = new Resend(apiKey);
    const { error } = await resend.emails.send({
      from,
      to,
      replyTo: data.email,
      subject: `Demo request: ${data.spa_name} (${data.first_name} ${data.last_name})`,
      text: renderText(data),
    });
    if (error) {
      console.error('[sendDemoRequest] Resend error:', error);
      return {
        status: 'error',
        message: "Couldn't send right now. Please email us directly.",
      };
    }
  } catch (err) {
    console.error('[sendDemoRequest] threw:', err);
    return {
      status: 'error',
      message: "Couldn't send right now. Please email us directly.",
    };
  }

  return {
    status: 'success',
    message: "Thanks — we'll be in touch.",
  };
}
