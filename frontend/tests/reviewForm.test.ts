/**
 * The review form's completeness rule.
 *
 * Only four things are required, and the test pins that deliberately: the
 * domain checklists are "complete only those relevant to your expertise" and
 * the issues table is empty for a lab a reviewer is happy with. Requiring
 * either would push reviewers into inventing content to get past a validator.
 */
import { describe, expect, it } from 'vitest'
import { REVIEW_AREAS, missingRequired, type ReviewSubmission } from '../src/lib/hub/reviewForm'

function reviewed(overrides: Partial<ReviewSubmission> = {}): ReviewSubmission {
  const ratings = Object.fromEntries(REVIEW_AREAS.map((area) => [area.id, 'GOOD']))
  return {
    reviewerName: 'A Reviewer',
    areaOfExpertise: 'Single-cell genomics',
    versionBuild: 'test',
    reviewDate: '2026-09-12',
    ratings,
    issues: [],
    domainChecks: {},
    finalRecommendation: 'RELEASE',
    mostImportantCorrection: '',
    optionalSuggestions: '',
    reviewerComments: '',
    ...overrides,
  } as ReviewSubmission
}

describe('submitting a review', () => {
  it('accepts a clean release recommendation with no issues raised', () => {
    expect(missingRequired(reviewed())).toEqual([])
  })

  it('asks for every one of the ten areas to be rated', () => {
    const partial = reviewed({ ratings: { SCIENTIFIC_ACCURACY: 'GOOD' } })
    expect(missingRequired(partial).join(' ')).toContain('All ten review areas')
  })

  it('asks what to correct whenever corrections are recommended', () => {
    const corrections = reviewed({ finalRecommendation: 'MINOR_CORRECTIONS' })
    expect(missingRequired(corrections)).toContain('Most important correction before release')
  })

  it('needs a name, an expertise and a recommendation', () => {
    const bare = reviewed({ reviewerName: '', areaOfExpertise: '', finalRecommendation: '' })
    const missing = missingRequired(bare)
    expect(missing).toContain('Reviewer name')
    expect(missing).toContain('Area of expertise')
    expect(missing).toContain('Final recommendation')
  })
})
