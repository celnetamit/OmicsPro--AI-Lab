/**
 * Feedback from inside the lab.
 *
 * This is the client for NanoSchool's feedback endpoint, kept in step with the
 * other Live Labs. It is not the lab's own issue report: that one stays in this
 * lab's database for its administrators (see the Report an issue control), and
 * what is sent here reaches the people who run the programme.
 *
 * Why ask for identity the hub already has. The session token establishes which
 * account is signed in, and that is stored alongside whatever is typed here.
 * The two are not the same claim. Labs run on shared machines and in taught
 * sessions, so the person at the keyboard is often not the account holder, and
 * a reply address may legitimately differ from the registration one. The
 * designation is asked for the same reason rather than a different one: the
 * account holds one from registration, which goes stale and may not be the
 * capacity someone is writing in. It is the field that makes a report
 * actionable — "this is confusing" from a plant operator and from a
 * postgraduate are different findings that need different responses.
 *
 * The draft is kept in sessionStorage rather than localStorage. A half-written
 * message containing someone's name and email is personal data, and one that
 * outlived the browser session would sit on a shared machine after they had
 * walked away from it.
 */

import { hubBaseUrl, hubFetch, hasHubSession } from './hub';
import { scopedKey } from './identity';

export type FeedbackCategory = 'GENERAL' | 'BUG' | 'SCIENCE' | 'USABILITY' | 'FEATURE';

export const FEEDBACK_CATEGORIES: { value: FeedbackCategory; label: string; hint: string }[] = [
  { value: 'GENERAL', label: 'General', hint: 'Anything that does not fit the others.' },
  { value: 'BUG', label: 'Something is broken', hint: 'A control that does nothing, a number that looks wrong, a screen that fails.' },
  {
    value: 'SCIENCE',
    label: 'Scientific accuracy',
    hint: 'A claim you disagree with, a method you would have done differently, a citation that is wrong.',
  },
  { value: 'USABILITY', label: 'Hard to use or unclear', hint: 'Wording that confused you, a step you could not find.' },
  { value: 'FEATURE', label: 'Something missing', hint: 'What you needed the lab to do and it did not.' },
];

export interface FeedbackDraft {
  name: string;
  email: string;
  designation: string;
  category: FeedbackCategory;
  /** 0 means "not given" — a rating is optional and is not invented. */
  rating: number;
  message: string;
}

export const EMPTY_DRAFT: FeedbackDraft = {
  name: '',
  email: '',
  designation: '',
  category: 'GENERAL',
  rating: 0,
  message: '',
};

export const MAX_MESSAGE_LENGTH = 4000;
export const MAX_FIELD_LENGTH = 200;

/** Which fields are wrong, keyed by field, so each can be shown in place. */
export type FeedbackErrors = Partial<Record<keyof FeedbackDraft, string>>;

/**
 * Validation, deliberately permissive on the email.
 *
 * A shape check and nothing more. Address syntax is a poor proxy for
 * deliverability — a perfectly formed address can bounce and an unusual one can
 * be fine — so a strict pattern mostly turns away people with legitimate
 * addresses, which is a worse outcome than storing one that bounces.
 */
export function validateFeedback(draft: FeedbackDraft): FeedbackErrors {
  const errors: FeedbackErrors = {};
  if (!draft.name.trim()) errors.name = 'Please give a name we can address a reply to.';
  if (!draft.email.trim()) errors.email = 'An email address is needed to reply.';
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(draft.email.trim())) {
    errors.email = 'That does not look like an email address.';
  }
  if (!draft.designation.trim()) {
    errors.designation = 'Your role or job title — it decides how your feedback is read.';
  }
  if (!draft.message.trim()) errors.message = 'There is nothing to send yet.';
  else if (draft.message.trim().length < 10) {
    errors.message = 'A few more words would make this actionable.';
  }
  return errors;
}

export function isValid(errors: FeedbackErrors): boolean {
  return Object.keys(errors).length === 0;
}

/* ------------------------------------------------------------------ *
 * Draft persistence
 * ------------------------------------------------------------------ */

/** Where a half-written message is kept between reloads of the same tab. */
export const FEEDBACK_DRAFT_KEY = 'omicslab.feedback_draft';

export function draftStorageKey(): string {
  return scopedKey(FEEDBACK_DRAFT_KEY);
}

export function saveDraft(draft: FeedbackDraft): void {
  try {
    // Nothing to keep, and nothing to leave behind, if the form is empty.
    const empty = !draft.name && !draft.email && !draft.designation && !draft.message;
    if (empty) sessionStorage.removeItem(draftStorageKey());
    else sessionStorage.setItem(draftStorageKey(), JSON.stringify(draft));
  } catch {
    /* Private mode: the draft simply is not preserved across a reload. */
  }
}

export function loadDraft(): FeedbackDraft | null {
  try {
    const raw = sessionStorage.getItem(draftStorageKey());
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<FeedbackDraft>;
    return {
      ...EMPTY_DRAFT,
      ...parsed,
      // A stored category that is no longer offered falls back rather than
      // reaching the server as an unknown value.
      category: FEEDBACK_CATEGORIES.some((c) => c.value === parsed.category)
        ? (parsed.category as FeedbackCategory)
        : 'GENERAL',
    };
  } catch {
    return null;
  }
}

export function clearDraft(): void {
  try {
    sessionStorage.removeItem(draftStorageKey());
  } catch {
    /* Nothing to clear. */
  }
}

/* ------------------------------------------------------------------ *
 * Sending
 * ------------------------------------------------------------------ */

export type FeedbackResult =
  | {
      ok: true;
      id: string;
      receivedAt: string;
      note: string;
      /** The account the hub recorded this against, which may differ from the typed address. */
      signedInAs: string | null;
    }
  | { ok: false; code: string; message: string };

export function feedbackEndpoint(): string {
  return `${hubBaseUrl()}/api/labs/feedback`;
}

/**
 * Send it, and report honestly when it did not go.
 *
 * The failure paths matter more than the success one here. Someone who has just
 * written out a considered piece of feedback and sees a cheerful "thank you"
 * when nothing was transmitted has been lied to, and will not write the second
 * one. Every branch below returns ok: false with something the sender can act
 * on, and the caller keeps the draft.
 */
export async function sendFeedback(
  draft: FeedbackDraft,
  context: { screen: string; appVersion: string },
  fetchImpl: typeof fetch = fetch,
): Promise<FeedbackResult> {
  if (!hasHubSession()) {
    return {
      ok: false,
      code: 'NO_SESSION',
      message:
        'This lab has no signed-in session, so there is nowhere to send feedback. Open the lab from your ' +
        'dashboard and try again — your draft is kept.',
    };
  }

  const errors = validateFeedback(draft);
  if (!isValid(errors)) {
    return { ok: false, code: 'INVALID', message: Object.values(errors).join(' ') };
  }

  let response: Response;
  try {
    response = await hubFetch(
      feedbackEndpoint(),
      {
        method: 'POST',
        body: JSON.stringify({
          name: draft.name.trim(),
          email: draft.email.trim(),
          designation: draft.designation.trim(),
          category: draft.category,
          // 0 is the sentinel for "not given"; it is not sent as a score.
          rating: draft.rating > 0 ? draft.rating : undefined,
          message: draft.message.trim(),
          screen: context.screen,
          appVersion: context.appVersion,
        }),
      },
      20_000,
      fetchImpl,
    );
  } catch (error) {
    /*
     * Network failure or timeout. Named as such rather than folded into a
     * generic error, because "you are offline" and "the server rejected this"
     * call for different actions from the sender.
     */
    const aborted = error instanceof DOMException && error.name === 'AbortError';
    return {
      ok: false,
      code: aborted ? 'TIMEOUT' : 'NETWORK',
      message: aborted
        ? 'The hub did not respond within 20 seconds. Nothing was sent; your draft is kept.'
        : 'Could not reach the hub. Check your connection — nothing was sent, and your draft is kept.',
    };
  }

  let body: Record<string, unknown> = {};
  try {
    body = (await response.json()) as Record<string, unknown>;
  } catch {
    /* Fall through to the status-based message below. */
  }

  if (!response.ok) {
    return {
      ok: false,
      code: typeof body.code === 'string' ? body.code : `HTTP_${response.status}`,
      message:
        typeof body.message === 'string'
          ? body.message
          : `The hub refused this with status ${response.status}. Nothing was sent; your draft is kept.`,
    };
  }

  return {
    ok: true,
    id: typeof body.id === 'string' ? body.id : 'unknown',
    receivedAt: typeof body.receivedAt === 'string' ? body.receivedAt : new Date().toISOString(),
    note:
      typeof body.note === 'string'
        ? body.note
        : 'Stored for the team to read. No automatic reply is sent.',
    signedInAs: typeof body.signedInAs === 'string' ? body.signedInAs : null,
  };
}
