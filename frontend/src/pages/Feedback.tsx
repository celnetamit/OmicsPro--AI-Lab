/**
 * Send feedback to NanoSchool.
 *
 * There are two places this can go, and the screen always says which one it
 * used. Opened from the NanoSchool dashboard, the lab holds a hub session and
 * the message reaches the programme team. Opened directly, there is no hub
 * credential to send it with — so rather than refuse and lose what someone has
 * written, it is filed in this lab's own issue register, which this lab's
 * administrators triage. What never happens is a thank-you for a message that
 * went nowhere.
 */
import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { messageOf, post } from '../lib/api'
import { PageHeader } from '../components/ui'
import { useHubSession } from '../components/HubSession'
import { BUILD_VERSION } from '../lib/hub/lab'
import { hasHubSession } from '../lib/hub/hub'
import {
  EMPTY_DRAFT,
  FEEDBACK_CATEGORIES,
  MAX_FIELD_LENGTH,
  MAX_MESSAGE_LENGTH,
  clearDraft,
  isValid,
  loadDraft,
  saveDraft,
  sendFeedback,
  validateFeedback,
  type FeedbackCategory,
  type FeedbackDraft,
  type FeedbackErrors,
} from '../lib/hub/feedback'

type Sent =
  | { where: 'nanoschool'; note: string; signedInAs: string | null }
  | { where: 'lab'; reference: string }

//: This lab's issue categories are not the hub's. Mapped rather than renamed on
//: either side: the two registers are read by different people for different
//: purposes, and each set of words suits its own reader.
const LAB_CATEGORY: Record<FeedbackCategory, string> = {
  GENERAL: 'other',
  BUG: 'technical',
  SCIENCE: 'scientific',
  USABILITY: 'content',
  FEATURE: 'other',
}

export function Feedback() {
  const location = useLocation()
  const { identity } = useHubSession()
  const [draft, setDraft] = useState<FeedbackDraft>(() => loadDraft() ?? EMPTY_DRAFT)
  const [errors, setErrors] = useState<FeedbackErrors>({})
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const [sent, setSent] = useState<Sent | null>(null)

  function change(patch: Partial<FeedbackDraft>) {
    const next = { ...draft, ...patch }
    setDraft(next)
    saveDraft(next)
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setFailure('')
    const found = validateFeedback(draft)
    setErrors(found)
    if (!isValid(found)) return

    setBusy(true)
    try {
      if (hasHubSession()) {
        const result = await sendFeedback(draft, {
          screen: location.pathname,
          appVersion: BUILD_VERSION,
        })
        if (!result.ok) {
          setFailure(result.message)
          return
        }
        clearDraft()
        setDraft(EMPTY_DRAFT)
        setSent({ where: 'nanoschool', note: result.note, signedInAs: result.signedInAs })
        return
      }

      //: No hub session. The message is still worth keeping, so it goes to this
      //: lab's register with the sender's details in the body — that register
      //: has no fields for them.
      const preamble = [
        `From: ${draft.name.trim()} <${draft.email.trim()}>`,
        `Designation: ${draft.designation.trim()}`,
        draft.rating > 0 ? `Rating: ${draft.rating} of 5` : null,
        `Build: ${BUILD_VERSION}`,
      ]
        .filter(Boolean)
        .join('\n')
      const issue = await post<{ id: string }>('/api/issues', {
        category: LAB_CATEGORY[draft.category],
        message: `${preamble}\n\n${draft.message.trim()}`,
        screen: location.pathname.slice(0, 128),
        run_id: null,
      })
      clearDraft()
      setDraft(EMPTY_DRAFT)
      setSent({ where: 'lab', reference: issue.id.slice(0, 8) })
    } catch (e) {
      setFailure(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  if (sent) {
    return (
      <>
        <PageHeader title="Send feedback" />
        <div className="card measure">
          <h3>Thank you — it is recorded</h3>
          {sent.where === 'nanoschool' ? (
            <>
              <p>{sent.note}</p>
              {sent.signedInAs ? (
                <p className="hint">Recorded against the NanoSchool account {sent.signedInAs}.</p>
              ) : null}
            </>
          ) : (
            <>
              <p>
                This session is not signed in to NanoSchool, so it went to this lab's own issue
                register instead, where its administrators read it. Your reference is{' '}
                <strong className="mono">{sent.reference}</strong>.
              </p>
              <p className="hint">
                To send feedback to the programme team instead, open this lab from your NanoSchool
                dashboard and write it again there.
              </p>
            </>
          )}
          <button type="button" className="secondary mt-4" onClick={() => setSent(null)}>
            Write another
          </button>
        </div>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Send feedback"
        lede="What went wrong, what was unclear, or what you needed the lab to do and it did not."
      />

      <form className="card measure" onSubmit={submit}>
        <p className="hint">
          {hasHubSession()
            ? `This goes to the NanoSchool team${identity?.email ? `, recorded against ${identity.email}` : ''}. No automatic reply is sent.`
            : 'This session is not signed in to NanoSchool, so this goes to this lab’s own issue register, which its administrators read. Open the lab from your NanoSchool dashboard to write to the programme team instead.'}
        </p>

        <div className="grid-2">
          <div className="field">
            <label htmlFor="fb-name">Your name</label>
            <input
              id="fb-name"
              maxLength={MAX_FIELD_LENGTH}
              value={draft.name}
              onChange={(e) => change({ name: e.target.value })}
            />
            {errors.name ? <p className="warning">{errors.name}</p> : null}
          </div>
          <div className="field">
            <label htmlFor="fb-email">Email for a reply</label>
            <input
              id="fb-email"
              type="email"
              maxLength={MAX_FIELD_LENGTH}
              value={draft.email}
              onChange={(e) => change({ email: e.target.value })}
            />
            {errors.email ? <p className="warning">{errors.email}</p> : null}
          </div>
        </div>

        <div className="field">
          <label htmlFor="fb-designation">Your role or job title</label>
          <input
            id="fb-designation"
            maxLength={MAX_FIELD_LENGTH}
            value={draft.designation}
            onChange={(e) => change({ designation: e.target.value })}
            placeholder="e.g. PhD student, bioinformatician, lab head"
          />
          <p className="hint">
            It decides how your feedback is read: the same sentence from a student and from a
            reviewer calls for different responses.
          </p>
          {errors.designation ? <p className="warning">{errors.designation}</p> : null}
        </div>

        <div className="field">
          <label htmlFor="fb-category">What kind of feedback is it?</label>
          <select
            id="fb-category"
            value={draft.category}
            onChange={(e) => change({ category: e.target.value as FeedbackCategory })}
          >
            {FEEDBACK_CATEGORIES.map((category) => (
              <option key={category.value} value={category.value}>
                {category.label}
              </option>
            ))}
          </select>
          <p className="hint">
            {FEEDBACK_CATEGORIES.find((c) => c.value === draft.category)?.hint}
          </p>
        </div>

        <div className="field">
          <span className="label-text">How would you rate the lab so far? (optional)</span>
          <div className="viz-chips" role="group" aria-label="Rating out of five">
            {[1, 2, 3, 4, 5].map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={draft.rating === value}
                onClick={() => change({ rating: draft.rating === value ? 0 : value })}
              >
                {value}
              </button>
            ))}
            <button type="button" aria-pressed={draft.rating === 0} onClick={() => change({ rating: 0 })}>
              No rating
            </button>
          </div>
        </div>

        <div className="field">
          <label htmlFor="fb-message">Your feedback</label>
          <textarea
            id="fb-message"
            rows={7}
            maxLength={MAX_MESSAGE_LENGTH}
            value={draft.message}
            onChange={(e) => change({ message: e.target.value })}
            placeholder="What you did, what you expected, and what happened instead."
          />
          <p className="hint">
            {draft.message.length} of {MAX_MESSAGE_LENGTH} characters. A draft is kept until this
            browser tab is closed.
          </p>
          {errors.message ? <p className="warning">{errors.message}</p> : null}
        </div>

        {failure ? <p className="warning" role="alert">{failure}</p> : null}

        <button type="submit" disabled={busy}>
          {busy ? 'Sending…' : 'Send feedback'}
        </button>
      </form>
    </>
  )
}
