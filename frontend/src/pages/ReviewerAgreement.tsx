/**
 * The Expert Reviewer Agreement, shown in full and signed here.
 *
 * The text is rendered from the shared document module, which every Live Lab
 * carries byte-identically — a reviewer who signs in one lab has signed the
 * same words as one who signed in another, and the acknowledgement stored on
 * the hub carries the version and a fingerprint of the displayed text so a
 * later edit is detectable rather than silently applying to people who agreed
 * to the previous wording. Nothing here is summarised: what is displayed is
 * what is agreed to.
 *
 * Whether the agreement is signed is asked of the hub, never remembered in this
 * browser. An undertaking a browser could mark as given is not an undertaking.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader, Skeleton } from '../components/ui'
import { useHubSession } from '../components/HubSession'
import { BUILD_VERSION, LAB_DOMAIN, LAB_TITLE } from '../lib/hub/lab'
import { hasHubSession } from '../lib/hub/hub'
import {
  AGREEMENT_CONFIRMATION,
  AGREEMENT_ISSUER,
  AGREEMENT_PREAMBLE,
  AGREEMENT_SECTIONS,
  AGREEMENT_SUBTITLE,
  AGREEMENT_TITLE,
  AGREEMENT_VERSION,
  REVIEW_ROLES,
  missingAcknowledgementFields,
  type AcknowledgementForm,
  type ReviewRoleId,
} from '../lib/hub/reviewerAgreement'
import { fetchAgreementStatus, signAgreement, type AgreementStatus } from '../lib/hub/reviewerAgreementClient'

const today = () => new Date().toISOString().slice(0, 10)

function emptyForm(name: string, email: string): AcknowledgementForm {
  return {
    labTitle: LAB_TITLE,
    domain: LAB_DOMAIN,
    reviewBuild: BUILD_VERSION,
    reviewerName: name,
    designation: '',
    institution: '',
    email,
    dateAccessProvided: today(),
    expectedCompletion: '',
    reviewRoles: [],
    signature: '',
    signedDate: today(),
    confirmed: false,
  }
}

/** The document itself, exactly as issued. */
function AgreementText() {
  return (
    <div className="card agreement">
      <h3>{AGREEMENT_TITLE}</h3>
      <p className="hint">{AGREEMENT_SUBTITLE}</p>
      {AGREEMENT_PREAMBLE.map((paragraph) => (
        <p key={paragraph}>{paragraph}</p>
      ))}
      {AGREEMENT_SECTIONS.map((section) => (
        <section key={section.number}>
          <h4>
            {section.number}. {section.heading}
          </h4>
          {section.blocks.map((block, index) => {
            if (block.subheading) return <h5 key={index}>{block.subheading}</h5>
            if (block.bullets) {
              return (
                <ul key={index}>
                  {block.bullets.map((bullet) => (
                    <li key={bullet}>{bullet}</li>
                  ))}
                </ul>
              )
            }
            return <p key={index}>{block.text}</p>
          })}
        </section>
      ))}
      <section>
        <h4>Issued by</h4>
        {AGREEMENT_ISSUER.lines.map((line) => (
          <p key={line} className="issuer-line">
            {line}
          </p>
        ))}
        <p className="hint">{AGREEMENT_ISSUER.purpose}</p>
      </section>
    </div>
  )
}

export function ReviewerAgreement() {
  const { identity, message } = useHubSession()
  const [status, setStatus] = useState<AgreementStatus | null>(null)
  const [form, setForm] = useState<AcknowledgementForm>(() => emptyForm('', ''))
  const [failure, setFailure] = useState('')
  const [busy, setBusy] = useState(false)
  const [recorded, setRecorded] = useState<{ id: string; acknowledgedAt: string; note: string } | null>(null)

  useEffect(() => {
    if (!identity) return
    setForm((current) => ({
      ...current,
      reviewerName: current.reviewerName || identity.name || '',
      email: current.email || identity.email || '',
    }))
  }, [identity])

  useEffect(() => {
    if (!hasHubSession()) return
    void fetchAgreementStatus().then(setStatus)
  }, [])

  function change(patch: Partial<AcknowledgementForm>) {
    setForm((current) => ({ ...current, ...patch }))
  }

  function toggleRole(role: ReviewRoleId) {
    setForm((current) => ({
      ...current,
      reviewRoles: current.reviewRoles.includes(role)
        ? current.reviewRoles.filter((r) => r !== role)
        : [...current.reviewRoles, role],
    }))
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setFailure('')
    const missing = missingAcknowledgementFields(form)
    if (missing.length > 0) {
      setFailure(`Not recorded — still needed: ${missing.join('; ')}.`)
      return
    }
    setBusy(true)
    try {
      const result = await signAgreement(form)
      if (!result.ok) {
        setFailure(result.message)
        return
      }
      setRecorded({ id: result.id, acknowledgedAt: result.acknowledgedAt, note: result.note })
      setStatus(await fetchAgreementStatus())
    } finally {
      setBusy(false)
    }
  }

  if (!hasHubSession() || !identity) {
    return (
      <>
        <PageHeader title="Reviewer agreement" lede={AGREEMENT_SUBTITLE} />
        <div className="card measure">
          <h3>Open this lab from your NanoSchool dashboard</h3>
          <p>
            An agreement is recorded against a NanoSchool account, and this session does not carry
            one. Sign in at NanoSchool and open OmicsLab from there; this screen will then show the
            agreement and record your signature.
          </p>
          {message ? <p className="warning">{message}</p> : null}
        </div>
        <AgreementText />
      </>
    )
  }

  if (identity.isReviewer !== true) {
    return (
      <>
        <PageHeader title="Reviewer agreement" lede={AGREEMENT_SUBTITLE} />
        <div className="card measure">
          <h3>This account is not marked as an expert reviewer</h3>
          <p>
            The agreement is for reviewers invited to assess a pre-release lab. If you were invited,
            ask NanoSchool to mark the account {identity.email ?? ''} as a reviewer, then open the
            lab again. The document is below for reference.
          </p>
        </div>
        <AgreementText />
      </>
    )
  }

  const signed = status?.signed ?? null

  return (
    <>
      <PageHeader
        title="Reviewer agreement"
        lede={AGREEMENT_SUBTITLE}
        actions={
          signed ? (
            <Link className="button secondary" to="/expert-review">
              Open the review form
            </Link>
          ) : null
        }
      />

      {recorded ? (
        <div className="card measure">
          <h3>Signed and recorded</h3>
          <p>{recorded.note}</p>
          <p className="hint">
            Reference {recorded.id.slice(0, 8)} · recorded {new Date(recorded.acknowledgedAt).toLocaleString()}.
          </p>
          <Link className="button mt-4" to="/expert-review">
            Open the review form
          </Link>
        </div>
      ) : signed ? (
        <div className="card measure">
          <h3>You have signed the current agreement</h3>
          <p className="hint">
            Signed {new Date(signed.acknowledgedAt).toLocaleString()} as {signed.reviewerName},{' '}
            {signed.institution}. Version {signed.agreementVersion}.
          </p>
          <p>The text you agreed to is below, unchanged.</p>
        </div>
      ) : status?.unknown ? (
        <p className="caveat">
          NanoSchool could not be reached, so whether you have already signed this version is not
          known yet. Reload in a moment rather than signing twice.
        </p>
      ) : status?.previouslySignedVersion ? (
        <p className="caveat">
          You signed an earlier version ({status.previouslySignedVersion}) on{' '}
          {status.previouslySignedAt ? new Date(status.previouslySignedAt).toLocaleDateString() : 'an earlier date'}.
          The wording has changed since, so this version needs signing again.
        </p>
      ) : null}

      <AgreementText />

      {signed || recorded ? null : (
        <form className="card" onSubmit={submit}>
          <h3>Reviewer acknowledgement</h3>
          <p className="hint">
            Version {AGREEMENT_VERSION}. Recorded against your NanoSchool account together with a
            fingerprint of the text above.
          </p>

          <div className="grid-2">
            <div className="field">
              <label htmlFor="ra-lab">Lab under review</label>
              <input id="ra-lab" value={form.labTitle} readOnly />
            </div>
            <div className="field">
              <label htmlFor="ra-build">Build</label>
              <input id="ra-build" value={form.reviewBuild} readOnly />
            </div>
          </div>

          <div className="grid-2">
            <div className="field">
              <label htmlFor="ra-name">Reviewer name</label>
              <input id="ra-name" value={form.reviewerName} onChange={(e) => change({ reviewerName: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="ra-designation">Designation</label>
              <input
                id="ra-designation"
                value={form.designation}
                onChange={(e) => change({ designation: e.target.value })}
                placeholder="e.g. Professor, Principal Scientist"
              />
            </div>
          </div>

          <div className="grid-2">
            <div className="field">
              <label htmlFor="ra-institution">Institution or organisation</label>
              <input
                id="ra-institution"
                value={form.institution}
                onChange={(e) => change({ institution: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="ra-email">Email</label>
              <input id="ra-email" type="email" value={form.email} onChange={(e) => change({ email: e.target.value })} />
            </div>
          </div>

          <div className="grid-2">
            <div className="field">
              <label htmlFor="ra-domain">Domain</label>
              <input id="ra-domain" value={form.domain} onChange={(e) => change({ domain: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="ra-expected">Expected completion (optional)</label>
              <input
                id="ra-expected"
                type="date"
                value={form.expectedCompletion}
                onChange={(e) => change({ expectedCompletion: e.target.value })}
              />
            </div>
          </div>

          <div className="field">
            <span className="label-text">Review roles you are taking on</span>
            <div className="check-grid">
              {REVIEW_ROLES.map((role) => (
                <label className="check" key={role.id}>
                  <input
                    type="checkbox"
                    checked={form.reviewRoles.includes(role.id)}
                    onChange={() => toggleRole(role.id)}
                  />
                  {role.label}
                </label>
              ))}
            </div>
          </div>

          <div className="field">
            <label className="check">
              <input
                type="checkbox"
                checked={form.confirmed}
                onChange={(e) => change({ confirmed: e.target.checked })}
              />
              {AGREEMENT_CONFIRMATION}
            </label>
          </div>

          <div className="grid-2">
            <div className="field">
              <label htmlFor="ra-signature">Signature (type your full name)</label>
              <input id="ra-signature" value={form.signature} onChange={(e) => change({ signature: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="ra-signed-date">Date</label>
              <input
                id="ra-signed-date"
                type="date"
                value={form.signedDate}
                onChange={(e) => change({ signedDate: e.target.value })}
              />
            </div>
          </div>

          {failure ? <p className="warning" role="alert">{failure}</p> : null}

          <button type="submit" disabled={busy}>
            {busy ? 'Recording…' : 'Sign and record'}
          </button>
        </form>
      )}

      {status === null && hasHubSession() ? <Skeleton lines={2} title={false} /> : null}
    </>
  )
}
