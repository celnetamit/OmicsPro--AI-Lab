/**
 * "Report an issue" (spec 14): a learner reports a problem from wherever it
 * happened. The screen is captured, and on a run's page the run can be attached,
 * so an admin can reproduce what the learner saw.
 */
import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useLocation } from 'react-router-dom'
import { messageOf, post } from '../lib/api'

const CATEGORIES: [string, string][] = [
  ['scientific', 'A scientific result looks wrong'],
  ['technical', 'Something broke or would not load'],
  ['content', 'Teaching content is unclear or incorrect'],
  ['access', 'Access, tiers or payment'],
  ['other', 'Something else'],
]

export function ReportIssue() {
  const dialog = useRef<HTMLDialogElement>(null)
  const location = useLocation()
  const runId = location.pathname.match(/^\/runs\/([0-9a-f-]{36})/i)?.[1]
  const [category, setCategory] = useState('technical')
  const [message, setMessage] = useState('')
  const [attachRun, setAttachRun] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reference, setReference] = useState<string | null>(null)

  function open() {
    setError('')
    setReference(null)
    dialog.current?.showModal()
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (message.trim().length < 10) {
      setError('Describe what happened in a sentence or two (at least 10 characters).')
      return
    }
    setBusy(true)
    setError('')
    try {
      const issue = await post<{ id: string }>('/api/issues', {
        category,
        message: message.trim(),
        screen: location.pathname.slice(0, 128),
        run_id: attachRun && runId ? runId : null,
      })
      setReference(issue.id.slice(0, 8))
      setMessage('')
    } catch (e) {
      setError(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button type="button" className="issue-trigger" onClick={open}>
        Report an issue
      </button>
      <dialog ref={dialog} className="issue-dialog" aria-labelledby="issue-title">
        <div className="issue-dialog-head">
          <h3 id="issue-title">Report an issue</h3>
          <button type="button" className="secondary" onClick={() => dialog.current?.close()}>
            Close
          </button>
        </div>
        {reference ? (
          <>
            <p>
              Your report is logged. Reference <strong>{reference}</strong>. An administrator
              reviews every report; you will see its status change on this form's history.
            </p>
            <button type="button" onClick={() => setReference(null)}>
              Report something else
            </button>
          </>
        ) : (
          <form onSubmit={submit}>
            <label htmlFor="issue-category">What kind of problem is it?</label>
            <select id="issue-category" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>

            <label htmlFor="issue-message">What happened?</label>
            <textarea
              id="issue-message"
              rows={5}
              maxLength={4000}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="What you did, what you expected, and what you saw instead."
            />

            <p className="hint">
              Sent with this report: the screen you are on ({location.pathname})
              {runId ? ' and, if you keep it ticked, this run.' : '.'} Nothing else.
            </p>
            {runId ? (
              <label className="check">
                <input
                  type="checkbox"
                  checked={attachRun}
                  onChange={(e) => setAttachRun(e.target.checked)}
                />
                Attach this run so it can be reproduced
              </label>
            ) : null}

            {error ? <p className="warning">{error}</p> : null}
            <button type="submit" disabled={busy}>
              {busy ? 'Sending…' : 'Send report'}
            </button>
          </form>
        )}
      </dialog>
    </>
  )
}
