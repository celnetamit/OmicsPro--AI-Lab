/**
 * The NanoSchool Expert Review Form.
 *
 * The fields, the severity definitions and the recommendation wording come from
 * the shared form module and are reproduced rather than paraphrased: a reviewer
 * choosing "Recommended after Minor Corrections" is making a defined statement,
 * and softening the definition changes what they said.
 *
 * A review takes an hour, so saving and submitting are separate acts: the draft
 * goes to the reviewer's account (so work follows them between machines) with a
 * copy in this browser as a safety net, and only submission is checked for
 * completeness. Every failure says plainly that the form is still on screen.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader, Skeleton } from '../components/ui'
import { useHubSession } from '../components/HubSession'
import { BUILD_VERSION } from '../lib/hub/lab'
import { hasHubSession } from '../lib/hub/hub'
import { fetchAgreementStatus, type AgreementStatus } from '../lib/hub/reviewerAgreementClient'
import {
  clearLocalDraft,
  completeness,
  emptyIssue,
  emptyReview,
  loadLocalDraft,
  loadReview,
  saveLocalDraft,
  saveReview,
  toggleDomainCheck,
} from '../lib/hub/review'
import {
  DOMAIN_CHECKS,
  RATING_LABELS,
  RATING_VALUES,
  RECOMMENDATIONS,
  REVIEW_AREAS,
  SEVERITIES,
  SEVERITY_DEFINITIONS,
  type DomainId,
  type RatingValue,
  type RecommendationId,
  type ReviewIssue,
  type ReviewSubmission,
  type Severity,
} from '../lib/hub/reviewForm'

export function ExpertReview() {
  const { identity, message } = useHubSession()
  const [agreement, setAgreement] = useState<AgreementStatus | null>(null)
  const [form, setForm] = useState<ReviewSubmission>(() => {
    const local = loadLocalDraft()
    return local ? { ...local, versionBuild: BUILD_VERSION } : emptyReview(BUILD_VERSION)
  })
  const [serverDraft, setServerDraft] = useState<{ status: string; updatedAt: string } | null>(null)
  const [submittedCount, setSubmittedCount] = useState(0)
  const [busy, setBusy] = useState<'save' | 'submit' | null>(null)
  const [failure, setFailure] = useState('')
  const [saved, setSaved] = useState('')
  const [submitted, setSubmitted] = useState<{ id: string; savedAt: string; note: string } | null>(null)

  useEffect(() => {
    if (!hasHubSession()) return
    void fetchAgreementStatus().then(setAgreement)
    void loadReview().then((loaded) => {
      if (!loaded) return
      setSubmittedCount(loaded.submittedCount)
      if (loaded.draft) {
        const { id: _id, status, updatedAt, ...draft } = loaded.draft
        setServerDraft({ status, updatedAt })
        //: The account's draft wins over this browser's copy: it is the one
        //: that followed the reviewer here from wherever they started.
        setForm({ ...draft, versionBuild: BUILD_VERSION })
      }
    })
  }, [])

  useEffect(() => {
    if (identity?.name && !form.reviewerName) {
      setForm((current) => ({ ...current, reviewerName: identity.name ?? '' }))
    }
  }, [identity, form.reviewerName])

  function change(patch: Partial<ReviewSubmission>) {
    setForm((current) => {
      const next = { ...current, ...patch }
      saveLocalDraft(next)
      return next
    })
    setSaved('')
  }

  function changeIssue(index: number, patch: Partial<ReviewIssue>) {
    change({ issues: form.issues.map((issue, i) => (i === index ? { ...issue, ...patch } : issue)) })
  }

  async function send(submit: boolean) {
    setFailure('')
    setSaved('')
    setBusy(submit ? 'submit' : 'save')
    try {
      const result = await saveReview(form, submit)
      if (!result.ok) {
        setFailure(result.message)
        return
      }
      if (submit) {
        clearLocalDraft()
        setSubmitted({ id: result.id, savedAt: result.savedAt, note: result.note })
        setSubmittedCount((count) => count + 1)
      } else {
        setServerDraft({ status: result.status, updatedAt: result.savedAt })
        setSaved(`Saved to your account at ${new Date(result.savedAt).toLocaleTimeString()}.`)
      }
    } finally {
      setBusy(null)
    }
  }

  if (!hasHubSession() || !identity) {
    return (
      <>
        <PageHeader title="Expert review form" />
        <div className="card measure">
          <h3>Open this lab from your NanoSchool dashboard</h3>
          <p>
            A review is filed against a NanoSchool account, and this session does not carry one.
            Sign in at NanoSchool and open OmicsLab from there.
          </p>
          {message ? <p className="warning">{message}</p> : null}
        </div>
      </>
    )
  }

  if (identity.isReviewer !== true) {
    return (
      <>
        <PageHeader title="Expert review form" />
        <div className="card measure">
          <h3>This account is not marked as an expert reviewer</h3>
          <p>
            The review form is for reviewers invited to assess this lab before release. If you were
            invited, ask NanoSchool to mark {identity.email ?? 'your account'} as a reviewer.
          </p>
        </div>
      </>
    )
  }

  if (agreement === null) {
    return (
      <>
        <PageHeader title="Expert review form" />
        <Skeleton lines={3} />
        <span className="visually-hidden" role="status">
          Checking whether the reviewer agreement is signed
        </span>
      </>
    )
  }

  if (agreement.unknown) {
    return (
      <>
        <PageHeader title="Expert review form" />
        <div className="card measure">
          <h3>NanoSchool could not be reached</h3>
          <p>
            Whether you have signed the current reviewer agreement is not known yet, and the form
            opens only once that is confirmed. Try again in a moment.
          </p>
        </div>
      </>
    )
  }

  if (!agreement.signed) {
    return (
      <>
        <PageHeader title="Expert review form" />
        <div className="card measure">
          <h3>The reviewer agreement comes first</h3>
          <p>
            The form opens once the current Expert Reviewer Agreement is signed. It takes a minute
            and is recorded against your NanoSchool account.
          </p>
          <Link className="button mt-4" to="/reviewer-agreement">
            Read and sign the agreement
          </Link>
        </div>
      </>
    )
  }

  if (submitted) {
    return (
      <>
        <PageHeader title="Expert review form" />
        <div className="card measure">
          <h3>Review submitted</h3>
          <p>{submitted.note}</p>
          <p className="hint">
            Reference {submitted.id.slice(0, 8)} · {new Date(submitted.savedAt).toLocaleString()}.
          </p>
        </div>
      </>
    )
  }

  const progress = completeness(form)

  return (
    <>
      <PageHeader
        title="Expert review form"
        lede={`Reviewing ${form.versionBuild}. Save as often as you like; submitting is a separate act.`}
      />

      {serverDraft ? (
        <p className="hint">
          A draft is held on your account, last saved {new Date(serverDraft.updatedAt).toLocaleString()}.
          {submittedCount > 0 ? ` You have submitted ${submittedCount} review(s) of this lab before.` : ''}
        </p>
      ) : null}

      <div className="card">
        <h3>Reviewer</h3>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="rv-name">Reviewer name</label>
            <input id="rv-name" value={form.reviewerName} onChange={(e) => change({ reviewerName: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="rv-expertise">Area of expertise</label>
            <input
              id="rv-expertise"
              value={form.areaOfExpertise}
              onChange={(e) => change({ areaOfExpertise: e.target.value })}
              placeholder="e.g. single-cell genomics, spatial biology, biostatistics"
            />
          </div>
        </div>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="rv-build">Version / build reviewed</label>
            <input id="rv-build" value={form.versionBuild} readOnly />
          </div>
          <div className="field">
            <label htmlFor="rv-date">Date of review</label>
            <input id="rv-date" type="date" value={form.reviewDate} onChange={(e) => change({ reviewDate: e.target.value })} />
          </div>
        </div>
      </div>

      <div className="card">
        <h3>A. Overall assessment</h3>
        <p className="hint">Rate all ten areas. "N/A" is a rating; leaving a row blank is not.</p>
        <div className="scroll">
          <table className="stacked">
            <thead>
              <tr>
                <th>Area</th>
                {RATING_VALUES.map((value) => (
                  <th key={value} className="num">
                    {RATING_LABELS[value]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {REVIEW_AREAS.map((area) => (
                <tr key={area.id}>
                  <td data-label="Area">{area.label}</td>
                  {RATING_VALUES.map((value) => (
                    <td key={value} data-label={RATING_LABELS[value]} className="num">
                      <input
                        type="radio"
                        name={`rating-${area.id}`}
                        aria-label={`${area.label}: ${RATING_LABELS[value]}`}
                        checked={form.ratings[area.id] === value}
                        onChange={() => change({ ratings: { ...form.ratings, [area.id]: value as RatingValue } })}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>B. Issues and recommended corrections</h3>
        <ul className="hint severity-key">
          {SEVERITIES.map((severity) => (
            <li key={severity}>
              <strong>{SEVERITY_DEFINITIONS[severity].label}:</strong>{' '}
              {SEVERITY_DEFINITIONS[severity].definition}
            </li>
          ))}
        </ul>
        <p className="hint">Leave this empty if you found nothing to correct.</p>
        {form.issues.map((issue, index) => (
          <div className="issue-row" key={index}>
            <div className="grid-2">
              <div className="field">
                <label htmlFor={`issue-module-${index}`}>Lab step or module</label>
                <input
                  id={`issue-module-${index}`}
                  value={issue.module}
                  onChange={(e) => changeIssue(index, { module: e.target.value })}
                  placeholder="e.g. Cell quality control"
                />
              </div>
              <div className="field">
                <label htmlFor={`issue-severity-${index}`}>Severity</label>
                <select
                  id={`issue-severity-${index}`}
                  value={issue.severity}
                  onChange={(e) => changeIssue(index, { severity: e.target.value as Severity | '' })}
                >
                  <option value="">Select…</option>
                  {SEVERITIES.map((severity) => (
                    <option key={severity} value={severity}>
                      {SEVERITY_DEFINITIONS[severity].label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="field">
              <label htmlFor={`issue-observation-${index}`}>Observation</label>
              <textarea
                id={`issue-observation-${index}`}
                rows={3}
                value={issue.observation}
                onChange={(e) => changeIssue(index, { observation: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor={`issue-recommendation-${index}`}>Recommended change or reference</label>
              <textarea
                id={`issue-recommendation-${index}`}
                rows={3}
                value={issue.recommendation}
                onChange={(e) => changeIssue(index, { recommendation: e.target.value })}
              />
            </div>
            {form.issues.length > 1 ? (
              <button
                type="button"
                className="secondary"
                onClick={() => change({ issues: form.issues.filter((_, i) => i !== index) })}
              >
                Remove this issue
              </button>
            ) : null}
          </div>
        ))}
        <button type="button" className="secondary" onClick={() => change({ issues: [...form.issues, emptyIssue()] })}>
          Add another issue
        </button>
      </div>

      <div className="card">
        <h3>C. Domain-specific checks</h3>
        <p className="hint">Complete only those relevant to your expertise.</p>
        <div className="grid-2">
          {DOMAIN_CHECKS.map((domain) => (
            <div key={domain.id}>
              <h4>{domain.label}</h4>
              <div className="check-grid">
                {domain.items.map((item) => (
                  <label className="check" key={item.id}>
                    <input
                      type="checkbox"
                      checked={(form.domainChecks[domain.id as DomainId] ?? []).includes(item.id)}
                      onChange={() =>
                        change({ domainChecks: toggleDomainCheck(form.domainChecks, domain.id as DomainId, item.id) })
                      }
                    />
                    {item.label}
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>D. Final recommendation</h3>
        <div className="check-grid">
          {RECOMMENDATIONS.map((recommendation) => (
            <label className="check" key={recommendation.id}>
              <input
                type="radio"
                name="final-recommendation"
                checked={form.finalRecommendation === recommendation.id}
                onChange={() => change({ finalRecommendation: recommendation.id as RecommendationId })}
              />
              {recommendation.label}
            </label>
          ))}
        </div>

        <div className="field mt-4">
          <label htmlFor="rv-correction">Most important correction before release</label>
          <textarea
            id="rv-correction"
            rows={3}
            value={form.mostImportantCorrection}
            onChange={(e) => change({ mostImportantCorrection: e.target.value })}
          />
          <p className="hint">Needed for anything other than "Recommended for Release".</p>
        </div>
        <div className="field">
          <label htmlFor="rv-suggestions">Optional suggestions</label>
          <textarea
            id="rv-suggestions"
            rows={3}
            value={form.optionalSuggestions}
            onChange={(e) => change({ optionalSuggestions: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="rv-comments">Reviewer comments</label>
          <textarea
            id="rv-comments"
            rows={4}
            value={form.reviewerComments}
            onChange={(e) => change({ reviewerComments: e.target.value })}
          />
        </div>
      </div>

      <div className="card">
        <p className="hint">
          {progress.rated} of {progress.total} areas rated.
          {progress.missing.length > 0 ? ` Before submitting: ${progress.missing.join('; ')}.` : ' Ready to submit.'}
        </p>
        {failure ? <p className="warning" role="alert">{failure}</p> : null}
        {saved ? <p className="success" role="status">{saved}</p> : null}
        <div className="row">
          <button type="button" className="secondary" disabled={busy !== null} onClick={() => void send(false)}>
            {busy === 'save' ? 'Saving…' : 'Save draft'}
          </button>
          <button type="button" disabled={busy !== null || progress.missing.length > 0} onClick={() => void send(true)}>
            {busy === 'submit' ? 'Submitting…' : 'Submit review'}
          </button>
        </div>
      </div>
    </>
  )
}
