/**
 * Whether a reviewer may go into the lab yet.
 *
 * An account NanoSchool marks as an expert reviewer meets the Expert Reviewer
 * Agreement before anything else in this lab — before Lab Home, before a
 * dataset, before a single pre-release screen. The hub records the signature
 * per account, per lab and per version, so "signed" here means signed *this*
 * version *for OmicsLab*; a signature given in another lab does not carry over.
 *
 * Kept as a pure function because the wrong answers look fine on screen. The
 * one that matters most: a hub that cannot be reached is `unknown`, not `sign`
 * and not `open`. Showing the form would ask a reviewer to sign something they
 * may already have signed; opening the lab would let them past an undertaking
 * nobody has confirmed.
 *
 * Type-only imports, deliberately. This module sits on the path every learner
 * loads, and the agreement document behind the status client is only worth
 * downloading for the few accounts that are reviewers.
 */
import type { LabIdentity } from './hub/identity'
import type { AgreementStatus } from './hub/reviewerAgreementClient'

export type ReviewerGate =
  /** Not a reviewer, or a reviewer who has signed: into the lab. */
  | 'open'
  /** A reviewer whose status is still being asked of the hub. */
  | 'checking'
  /** A reviewer who has not signed this version for this lab. */
  | 'sign'
  /** A reviewer whose status the hub did not give. Neither form nor lab. */
  | 'unknown'

export function reviewerGateState(params: {
  identity: LabIdentity | null
  status: AgreementStatus | null
  /** The hub accepted a signature during this visit. */
  signedThisVisit?: boolean
}): ReviewerGate {
  const { identity, status, signedThisVisit = false } = params
  //: No identity is a development session, where nobody has been verified and
  //: there is no account to record an undertaking against.
  if (!identity || identity.isReviewer !== true) return 'open'
  //: The hub's own "recorded" reply is its answer; a status re-read straight
  //: afterwards that happens to fail must not send the reviewer back to a form
  //: they have just completed.
  if (signedThisVisit) return 'open'
  if (status === null) return 'checking'
  if (status.signed) return 'open'
  if (status.unknown) return 'unknown'
  return 'sign'
}
