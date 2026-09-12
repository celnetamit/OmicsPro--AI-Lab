/**
 * Signing the reviewer agreement, and remembering that it was signed.
 *
 * The status is fetched from the hub rather than kept in this browser, and that
 * is the whole design. An undertaking that a browser could mark as given is not
 * an undertaking; the review form is gated on the hub's answer, and the hub
 * re-reads the reviewer flag and the signature on every call.
 *
 * Nothing here is cached in localStorage on purpose. A cached "already signed"
 * would survive the agreement being revoked, and a cached form draft would
 * leave someone's name, institution and email sitting on a shared machine for
 * an undertaking they never completed.
 */

import { hubBaseUrl, hubFetch, hasHubSession } from './hub';
import {
  AGREEMENT_VERSION, agreementFingerprint, missingAcknowledgementFields,
  type AcknowledgementForm, type ReviewRoleId,
} from './reviewerAgreement';

export function agreementEndpoint(): string {
  return `${hubBaseUrl()}/api/labs/reviewer-agreement`;
}

export interface SignedAgreement {
  id: string;
  acknowledgedAt: string;
  agreementVersion: string;
  agreementFingerprint: string;
  reviewerName: string;
  designation: string;
  institution: string;
  email: string;
  domain: string;
  reviewRoles: ReviewRoleId[];
}

export interface AgreementStatus {
  signed: SignedAgreement | null;
  /** Set when an earlier version was signed but the current one has not been. */
  previouslySignedVersion: string | null;
  previouslySignedAt: string | null;
  /** True when the hub could not be reached, as against "definitely not signed". */
  unknown: boolean;
}

const UNKNOWN: AgreementStatus = {
  signed: null,
  previouslySignedVersion: null,
  previouslySignedAt: null,
  unknown: true,
};

/**
 * Has this reviewer signed the current agreement?
 *
 * An unreachable hub returns `unknown: true` rather than "not signed". The two
 * call for different words on screen: one is "please sign this", the other is
 * "we cannot tell yet". Showing the first when the second is true would ask a
 * reviewer to sign something they may already have signed.
 */
export async function fetchAgreementStatus(fetchImpl: typeof fetch = fetch): Promise<AgreementStatus> {
  if (!hasHubSession()) return UNKNOWN;
  try {
    const url = `${agreementEndpoint()}?version=${encodeURIComponent(AGREEMENT_VERSION)}`;
    const response = await hubFetch(url, { method: 'GET' }, 20_000, fetchImpl);
    if (!response.ok) return UNKNOWN;
    const body = (await response.json()) as {
      signed?: SignedAgreement | null;
      previouslySignedVersion?: string | null;
      previouslySignedAt?: string | null;
    };
    return {
      signed: body.signed ?? null,
      previouslySignedVersion: body.previouslySignedVersion ?? null,
      previouslySignedAt: body.previouslySignedAt ?? null,
      unknown: false,
    };
  } catch {
    return UNKNOWN;
  }
}

export type SignResult =
  | { ok: true; id: string; acknowledgedAt: string; note: string }
  | { ok: false; code: string; message: string };

/** Record the signature. Every failure says plainly that nothing was recorded. */
export async function signAgreement(
  form: AcknowledgementForm,
  fetchImpl: typeof fetch = fetch,
): Promise<SignResult> {
  if (!hasHubSession()) {
    return {
      ok: false,
      code: 'NO_SESSION',
      message:
        'This lab has no signed-in session, so the agreement cannot be recorded against your account. Open the ' +
        'lab from your dashboard and sign it there.',
    };
  }

  const missing = missingAcknowledgementFields(form);
  if (missing.length > 0) {
    return { ok: false, code: 'INCOMPLETE', message: `Not recorded — still needed: ${missing.join('; ')}.` };
  }

  let response: Response;
  try {
    response = await hubFetch(
      agreementEndpoint(),
      {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          reviewRoles: form.reviewRoles,
          agreementVersion: AGREEMENT_VERSION,
          agreementFingerprint: agreementFingerprint(),
        }),
      },
      30_000,
      fetchImpl,
    );
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === 'AbortError';
    return {
      ok: false,
      code: aborted ? 'TIMEOUT' : 'NETWORK',
      message: aborted
        ? 'The hub did not respond within 30 seconds. Nothing was recorded — the form is still on screen.'
        : 'Could not reach the hub. Nothing was recorded — the form is still on screen.',
    };
  }

  let body: Record<string, unknown> = {};
  try {
    body = (await response.json()) as Record<string, unknown>;
  } catch {
    /* fall through to the status-based message */
  }

  if (!response.ok) {
    return {
      ok: false,
      code: typeof body.code === 'string' ? body.code : `HTTP_${response.status}`,
      message:
        typeof body.message === 'string'
          ? body.message
          : `The hub refused this with status ${response.status}. Nothing was recorded.`,
    };
  }

  return {
    ok: true,
    id: typeof body.id === 'string' ? body.id : 'unknown',
    acknowledgedAt: typeof body.acknowledgedAt === 'string' ? body.acknowledgedAt : new Date().toISOString(),
    note: typeof body.note === 'string' ? body.note : 'Recorded.',
  };
}
