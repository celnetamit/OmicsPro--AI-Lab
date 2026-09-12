/**
 * The reviewer agreement is one document across every Live Lab.
 *
 * The fingerprint is pinned to the value the other labs pin, and that is the
 * whole point of the test: the acknowledgement stored on the hub carries this
 * fingerprint, so a signature given in this lab counts as a signature against
 * the same words as one given in MicrobeAI or RepurposeAI. If this test fails,
 * either this copy has been edited alone — which forks the document silently —
 * or the wording changed everywhere and every lab's pin moves together.
 */
import { describe, expect, it } from 'vitest'
import {
  AGREEMENT_CONFIRMATION,
  AGREEMENT_SECTIONS,
  AGREEMENT_VERSION,
  agreementFingerprint,
  missingAcknowledgementFields,
  REVIEW_ROLES,
  type AcknowledgementForm,
} from '../src/lib/hub/reviewerAgreement'

/** The value pinned in every other lab that carries this document. */
const ORG_WIDE_FINGERPRINT = 'fnv1a-3d58a7d0-7254'

function complete(): AcknowledgementForm {
  return {
    labTitle: 'OmicsLab Pro',
    domain: 'Bio / Genomics / Medical',
    reviewBuild: 'test',
    reviewerName: 'A Reviewer',
    designation: 'Professor',
    institution: 'An institute',
    email: 'reviewer@example.org',
    dateAccessProvided: '2026-09-12',
    expectedCompletion: '2026-09-20',
    reviewRoles: ['SCIENTIFIC'],
    signature: 'A Reviewer',
    signedDate: '2026-09-12',
    confirmed: true,
  }
}

describe('the agreement document', () => {
  it('is the same text every other lab displays', () => {
    expect(agreementFingerprint()).toBe(ORG_WIDE_FINGERPRINT)
  })

  it('carries the version the hub stores against a signature', () => {
    expect(AGREEMENT_VERSION).toBe('nanoschool-reviewer-agreement-2026-09')
  })

  it('is rendered in full rather than summarised', () => {
    expect(AGREEMENT_SECTIONS.length).toBeGreaterThan(5)
    for (const section of AGREEMENT_SECTIONS) {
      expect(section.heading.trim()).not.toBe('')
      expect(section.blocks.length).toBeGreaterThan(0)
    }
    expect(AGREEMENT_CONFIRMATION).toContain('read and understood')
  })
})

describe('what an acknowledgement must carry', () => {
  it('accepts a complete one', () => {
    expect(missingAcknowledgementFields(complete())).toEqual([])
  })

  it('asks for the signature and the confirmation separately', () => {
    const unsigned = { ...complete(), signature: '', confirmed: false }
    const missing = missingAcknowledgementFields(unsigned)
    expect(missing).toContain('Reviewer signature')
    expect(missing.some((m) => m.toLowerCase().includes('confirmation'))).toBe(true)
  })

  it('will not record one with no review role, institution or valid email', () => {
    const thin = { ...complete(), reviewRoles: [], institution: '', email: 'not-an-address' }
    const missing = missingAcknowledgementFields(thin)
    expect(missing).toContain('At least one review role')
    expect(missing).toContain('Institution / organisation')
    expect(missing).toContain('A valid email address')
  })

  it('offers the roles the document lists', () => {
    expect(REVIEW_ROLES.map((r) => r.id)).toContain('COMPLETE')
  })
})
