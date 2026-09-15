/**
 * An expert reviewer signs before the lab opens.
 *
 * When NanoSchool marks an account as an expert reviewer, the first thing that
 * account sees on launching OmicsLab is the Expert Reviewer Agreement — not Lab
 * Home, not a dataset, not any pre-release screen. Once the hub has recorded the
 * signature, the lab opens at Lab Home. A reviewer who has already signed this
 * version for this lab goes straight in and is never shown the form again.
 *
 * Everything reviewer-specific is loaded only for reviewers: the status client,
 * the agreement document and the form arrive through dynamic imports, so an
 * ordinary learner's first page load carries none of it.
 *
 * What this does not do: stop the lab's own API. The undertaking is recorded on
 * the hub, which is also where the review form is filed and where the signature
 * is re-checked on every review call; this gate makes sure the agreement is the
 * reviewer's first screen rather than something they have to find.
 */
import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useHubSession } from './HubSession'
import { hubLabsUrl } from '../lib/labAuth'
import { reviewerGateState } from '../lib/reviewerGate'
import type { AgreementStatus } from '../lib/hub/reviewerAgreementClient'

const AgreementGateScreen = lazy(() =>
  import('../pages/ReviewerAgreement').then((m) => ({ default: m.AgreementGateScreen })),
)

function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">OL</span>
      <span className="brand-text">
        <span className="brand-name">OmicsLab Pro</span>
        <span className="brand-sub">NanoSchool Live Lab</span>
      </span>
    </div>
  )
}

function Holding({ title, children, busy = false }: { title: string; children: ReactNode; busy?: boolean }) {
  return (
    <div className="auth-shell">
      <div className="auth">
        <Brand />
        <h2>{title}</h2>
        <div className="card" role={busy ? 'status' : undefined} aria-live={busy ? 'polite' : undefined}>
          {children}
        </div>
      </div>
    </div>
  )
}

export function ReviewerAgreementGate({ children }: { children: ReactNode }) {
  const { identity } = useHubSession()
  const navigate = useNavigate()
  const [status, setStatus] = useState<AgreementStatus | null>(null)
  const [signedThisVisit, setSignedThisVisit] = useState(false)
  const reviewer = identity?.isReviewer === true

  const check = useCallback(async () => {
    setStatus(null)
    const { fetchAgreementStatus } = await import('../lib/hub/reviewerAgreementClient')
    setStatus(await fetchAgreementStatus())
  }, [])

  useEffect(() => {
    if (reviewer) void check()
  }, [reviewer, check])

  const gate = reviewerGateState({ identity, status, signedThisVisit })

  if (gate === 'open') return <>{children}</>

  if (gate === 'checking') {
    return (
      <Holding title="Checking your reviewer agreement" busy>
        <p>This account is an expert reviewer, so the lab first asks NanoSchool whether you have signed the agreement.</p>
      </Holding>
    )
  }

  if (gate === 'unknown') {
    return (
      <Holding title="Could not check your reviewer agreement">
        <p>
          NanoSchool did not answer, so it is not known yet whether you have already signed the agreement for this
          lab. Rather than ask you to sign something you may have signed, or open the lab without it, the lab waits.
        </p>
        <p className="muted">
          If trying again does not help, your NanoSchool session may have expired — launch the lab again from your
          dashboard.
        </p>
        <div className="row">
          <button type="button" onClick={() => void check()}>Try again</button>
          <a className="button secondary" href={hubLabsUrl()}>Back to Labs</a>
        </div>
      </Holding>
    )
  }

  return (
    <div className="gate-page">
      <div className="container">
        <div className="gate-bar">
          <Brand />
          <a className="button secondary small" href={hubLabsUrl()}>Back to Labs</a>
        </div>
        <Suspense fallback={<p className="hint" role="status">Loading the agreement…</p>}>
          <AgreementGateScreen
            status={status}
            name={identity?.name ?? ''}
            email={identity?.email ?? ''}
            onSigned={() => {
              setSignedThisVisit(true)
              //: Into the lab at its front door, whatever address the launch used.
              navigate('/', { replace: true })
              window.scrollTo({ top: 0 })
            }}
          />
        </Suspense>
      </div>
    </div>
  )
}
