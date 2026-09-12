/** What the feedback form will and will not send. */
import { describe, expect, it } from 'vitest'
import { EMPTY_DRAFT, isValid, validateFeedback } from '../src/lib/hub/feedback'

describe('feedback validation', () => {
  it('asks for a name, an email, a designation and something to say', () => {
    const errors = validateFeedback(EMPTY_DRAFT)
    expect(Object.keys(errors).sort()).toEqual(['designation', 'email', 'message', 'name'])
    expect(isValid(errors)).toBe(false)
  })

  it('accepts an ordinary message', () => {
    const draft = {
      ...EMPTY_DRAFT,
      name: 'A Learner',
      email: 'learner@example.org',
      designation: 'PhD student',
      message: 'The UMAP step took a while to explain itself.',
    }
    expect(isValid(validateFeedback(draft))).toBe(true)
  })

  it('turns away an address that is not one, and a message too short to act on', () => {
    const draft = {
      ...EMPTY_DRAFT,
      name: 'A Learner',
      email: 'learner-at-example',
      designation: 'PhD student',
      message: 'broken',
    }
    const errors = validateFeedback(draft)
    expect(errors.email).toBeDefined()
    expect(errors.message).toBeDefined()
  })
})
