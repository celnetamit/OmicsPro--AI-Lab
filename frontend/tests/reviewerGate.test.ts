/**
 * The reviewer's first screen in the lab.
 *
 * A reviewer must sign before the lab opens; everyone else must never see the
 * gate at all; and a hub that does not answer must neither open the lab nor ask
 * for a signature that may already exist.
 */
import { describe, expect, it } from 'vitest'
import { reviewerGateState } from '../src/lib/reviewerGate'
import type { LabIdentity } from '../src/lib/hub/identity'
import type { AgreementStatus } from '../src/lib/hub/reviewerAgreementClient'

const person = (isReviewer: boolean): LabIdentity => ({
  userId: isReviewer ? 'hub-reviewer' : 'hub-learner',
  email: 'someone@nanoschool.example',
  name: 'Someone',
  role: 'USER',
  labId: 'lab-omics',
  labSlug: 'omicslab',
  isReviewer,
})

const signed: AgreementStatus = {
  signed: {
    id: 'ack-1',
    acknowledgedAt: '2026-09-15T10:00:00.000Z',
    agreementVersion: 'nanoschool-reviewer-agreement-2026-09',
    agreementFingerprint: 'fnv1a-3d58a7d0-7254',
    reviewerName: 'Dr A Reviewer',
    designation: 'Professor',
    institution: 'An institute',
    email: 'reviewer@nanoschool.example',
    domain: 'Bio / Genomics / Medical',
    reviewRoles: ['SCIENTIFIC'],
  },
  previouslySignedVersion: 'nanoschool-reviewer-agreement-2026-09',
  previouslySignedAt: '2026-09-15T10:00:00.000Z',
  unknown: false,
}
const notSigned: AgreementStatus = {
  signed: null,
  previouslySignedVersion: null,
  previouslySignedAt: null,
  unknown: false,
}
const olderVersionOnly: AgreementStatus = {
  signed: null,
  previouslySignedVersion: 'nanoschool-reviewer-agreement-2025-11',
  previouslySignedAt: '2025-11-02T09:00:00.000Z',
  unknown: false,
}
const hubSilent: AgreementStatus = {
  signed: null,
  previouslySignedVersion: null,
  previouslySignedAt: null,
  unknown: true,
}

describe('reviewerGateState', () => {
  it('never stops a learner who is not a reviewer, whatever the status says', () => {
    for (const status of [null, notSigned, hubSilent, signed]) {
      expect(reviewerGateState({ identity: person(false), status })).toBe('open')
    }
  })

  it('does not gate a session with no identity to record an undertaking against', () => {
    expect(reviewerGateState({ identity: null, status: null })).toBe('open')
  })

  it('holds a reviewer while the hub is being asked', () => {
    expect(reviewerGateState({ identity: person(true), status: null })).toBe('checking')
  })

  it('asks a reviewer who has not signed to sign before the lab opens', () => {
    expect(reviewerGateState({ identity: person(true), status: notSigned })).toBe('sign')
  })

  it('asks again when only an earlier version of the wording was signed', () => {
    expect(reviewerGateState({ identity: person(true), status: olderVersionOnly })).toBe('sign')
  })

  it('lets a reviewer who has signed this version straight in', () => {
    expect(reviewerGateState({ identity: person(true), status: signed })).toBe('open')
  })

  it('neither opens the lab nor shows the form when the hub did not answer', () => {
    //: Opening would skip an undertaking nobody confirmed; the form would ask
    //: for a signature that may already exist.
    expect(reviewerGateState({ identity: person(true), status: hubSilent })).toBe('unknown')
  })

  it('opens the lab once the hub has accepted a signature in this visit', () => {
    //: Even if the status re-read straight afterwards fails.
    for (const status of [notSigned, hubSilent, null]) {
      expect(
        reviewerGateState({ identity: person(true), status, signedThisVisit: true }),
      ).toBe('open')
    }
  })
})
