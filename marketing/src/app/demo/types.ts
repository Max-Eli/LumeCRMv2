/**
 * Types + constants for the demo-request server action.
 *
 * Lives in a separate file (not `./actions.ts`) because that file
 * is marked `'use server'` and Next.js requires server-action
 * modules to export ONLY async functions. Runtime constants like
 * `INITIAL_STATE` would crash the route if exported from there.
 */

export interface DemoRequestState {
  status: 'idle' | 'success' | 'error';
  message: string;
}

export const INITIAL_STATE: DemoRequestState = {
  status: 'idle',
  message: '',
};
