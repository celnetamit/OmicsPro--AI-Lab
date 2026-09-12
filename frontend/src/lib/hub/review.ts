/**
 * The expert review form's client side: drafts, and getting one to the hub.
 *
 * Two things here differ from the feedback form, and both come from what a
 * review is. A review takes an hour rather than a minute, so losing it to a
 * closed tab is unacceptable and the draft lives on the *server* as well as in
 * the browser — a reviewer who starts on a laptop and finishes on a desktop
 * finds their work. And a review is signed off rather than sent: saving and
 * submitting are different acts, and only the second is checked for
 * completeness.
 */

import { hubBaseUrl, hubFetch, hasHubSession } from './hub';
import { scopedKey } from './identity';
import {
  REVIEW_AREAS, missingRequired,
  type DomainChecks, type DomainId, type Ratings, type ReviewIssue, type ReviewSubmission,
} from './reviewForm';

export const REVIEW_DRAFT_KEY = 'omicslab.review_draft';

export function emptyIssue(): ReviewIssue {
  return { module: '', severity: '', observation: '', recommendation: '' };
}

export function emptyReview(build: string): ReviewSubmission {
  return {
    reviewerName: '',
    areaOfExpertise: '',
    versionBuild: build,
    // Prefilled with today, and editable: the form asks for the review's date,
    // which is not always the day it happens to be submitted.
    reviewDate: new Date().toISOString().slice(0, 10),
    ratings: {},
    issues: [emptyIssue()],
    domainChecks: {},
    finalRecommendation: '',
    mostImportantCorrection: '',
    optionalSuggestions: '',
    reviewerComments: '',
  };
}

/** How much of the form is done, for the progress line above the buttons. */
export function completeness(form: ReviewSubmission): { rated: number; total: number; missing: string[] } {
  return {
    rated: REVIEW_AREAS.filter((a) => form.ratings[a.id]).length,
    total: REVIEW_AREAS.length,
    missing: missingRequired(form),
  };
}

export function toggleDomainCheck(checks: DomainChecks, domain: DomainId, item: string): DomainChecks {
  const current = checks[domain] ?? [];
  const next = current.includes(item) ? current.filter((i) => i !== item) : [...current, item];
  return { ...checks, [domain]: next };
}

/* ---- Local draft, as a safety net under the server draft ---- */

export function draftKey(): string {
  return scopedKey(REVIEW_DRAFT_KEY);
}

export function saveLocalDraft(form: ReviewSubmission): void {
  try {
    localStorage.setItem(draftKey(), JSON.stringify(form));
  } catch {
    /* Private mode. The server draft is the real one. */
  }
}

export function loadLocalDraft(): ReviewSubmission | null {
  try {
    const raw = localStorage.getItem(draftKey());
    return raw ? (JSON.parse(raw) as ReviewSubmission) : null;
  } catch {
    return null;
  }
}

export function clearLocalDraft(): void {
  try {
    localStorage.removeItem(draftKey());
  } catch {
    /* nothing to clear */
  }
}

/* ---- The hub ---- */

export function reviewEndpoint(): string {
  return `${hubBaseUrl()}/api/labs/review`;
}

export type ReviewSaveResult =
  | { ok: true; id: string; status: string; savedAt: string; note: string }
  | { ok: false; code: string; message: string };

export interface LoadedReview {
  draft: (ReviewSubmission & { id: string; status: string; updatedAt: string }) | null;
  submittedCount: number;
}

/** Fetch the reviewer's open draft, so work follows them between machines. */
export async function loadReview(fetchImpl: typeof fetch = fetch): Promise<LoadedReview | null> {
  if (!hasHubSession()) return null;
  try {
    const response = await hubFetch(reviewEndpoint(), { method: 'GET' }, 20_000, fetchImpl);
    if (!response.ok) return null;
    const body = (await response.json()) as { draft?: unknown; submittedCount?: number };
    return {
      draft: (body.draft ?? null) as LoadedReview['draft'],
      submittedCount: typeof body.submittedCount === 'number' ? body.submittedCount : 0,
    };
  } catch {
    // A failed load is not a failure to report: the local draft covers it, and
    // an error banner on arrival would be alarming and unhelpful.
    return null;
  }
}

/**
 * Save a draft, or submit the review.
 *
 * `submit` is the only difference the caller passes, and it is what turns a
 * private working copy into a signed-off document. Every failure path reports
 * honestly and says the form is still on screen — a reviewer who has spent an
 * hour on this must never be told it went somewhere it did not.
 */
export async function saveReview(
  form: ReviewSubmission,
  submit: boolean,
  fetchImpl: typeof fetch = fetch,
): Promise<ReviewSaveResult> {
  if (!hasHubSession()) {
    return {
      ok: false,
      code: 'NO_SESSION',
      message:
        'This lab has no signed-in session, so the review cannot be saved to your account. Open the lab from ' +
        'your dashboard — everything you have typed is still on screen and kept in this browser.',
    };
  }

  if (submit) {
    const missing = missingRequired(form);
    if (missing.length > 0) {
      return {
        ok: false,
        code: 'INCOMPLETE',
        message: `Not submitted — the form still needs: ${missing.join('; ')}.`,
      };
    }
  }

  let response: Response;
  try {
    response = await hubFetch(
      reviewEndpoint(),
      { method: 'POST', body: JSON.stringify({ ...form, submit }) },
      30_000,
      fetchImpl,
    );
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === 'AbortError';
    return {
      ok: false,
      code: aborted ? 'TIMEOUT' : 'NETWORK',
      message: aborted
        ? 'The hub did not respond within 30 seconds. Nothing was saved to your account; the form is still on screen and kept in this browser.'
        : 'Could not reach the hub. Nothing was saved to your account; the form is still on screen and kept in this browser.',
    };
  }

  let body: Record<string, unknown> = {};
  try {
    body = (await response.json()) as Record<string, unknown>;
  } catch {
    /* fall through */
  }

  if (!response.ok) {
    return {
      ok: false,
      code: typeof body.code === 'string' ? body.code : `HTTP_${response.status}`,
      message:
        typeof body.message === 'string'
          ? body.message
          : `The hub refused this with status ${response.status}. Nothing was saved; the form is still on screen.`,
    };
  }

  return {
    ok: true,
    id: typeof body.id === 'string' ? body.id : 'unknown',
    status: typeof body.status === 'string' ? body.status : 'DRAFT',
    savedAt: typeof body.savedAt === 'string' ? body.savedAt : new Date().toISOString(),
    note: typeof body.note === 'string' ? body.note : 'Saved.',
  };
}

export type { DomainChecks, Ratings, ReviewIssue, ReviewSubmission };
