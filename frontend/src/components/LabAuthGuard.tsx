/**
 * The Live Labs access gate.
 *
 * Nothing in the lab renders until NanoSchool has vouched for the visitor. The
 * sibling labs each carry a version of this component; ours differs in one way
 * that matters — the verification is done by this lab's own API rather than by
 * the browser, so the account the server stores work against is the account the
 * hub named, and not whatever the page claimed. See src/lib/labAuth.ts.
 *
 * Four things can happen, and they are deliberately four rather than two:
 *
 *   checking     — we are asking. Say so, and say nothing else.
 *   open         — render the lab.
 *   refused      — the hub answered no. Launching again from the dashboard is
 *                  what fixes it, so that is the only button offered.
 *   unreachable  — nobody answered. Bouncing to a login that is already
 *                  reachable would blame the visitor for a network fault, so
 *                  this one offers a retry and keeps the launch token in hand
 *                  to retry *with*.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { getToken, onUnauthorized } from '../lib/api'
import {
  clearLabSession,
  hubLabsUrl,
  hubSignInUrl,
  openDevelopmentSession,
  openLabSession,
  planLaunch,
  stripLaunchToken,
} from '../lib/labAuth'
import type { SessionOutcome } from '../lib/labAuth'

type Gate =
  | { phase: 'checking' }
  | { phase: 'leaving' }
  | { phase: 'open'; development: boolean }
  | { phase: 'refused'; message: string }
  | { phase: 'unreachable'; message: string; retry: () => void }
  /** A session that was open and has since been rejected by the server. */
  | { phase: 'ended' }

function Shell({
  title,
  children,
  busy = false,
}: {
  title: string
  children?: ReactNode
  busy?: boolean
}) {
  return (
    <div className="auth-shell">
      <div className="auth">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">OL</span>
          <span className="brand-text">
            <span className="brand-name">OmicsLab Pro</span>
            <span className="brand-sub">NanoSchool Live Lab</span>
          </span>
        </div>
        <h2>{title}</h2>
        <div className="card" role={busy ? 'status' : undefined} aria-live={busy ? 'polite' : undefined}>
          {children}
        </div>
      </div>
    </div>
  )
}

export function LabAuthGuard({ children }: { children: ReactNode }) {
  const [gate, setGate] = useState<Gate>({ phase: 'checking' })

  /*
   * Once per mount, and a ref rather than state because React's development
   * StrictMode runs effects twice: the first pass takes the launch token out of
   * the address bar, and a second pass reading state that had not updated yet
   * would find no token anywhere and send the learner back to the hub. That
   * exact race made the sibling labs unopenable in development.
   */
  const started = useRef(false)

  const apply = useCallback((outcome: SessionOutcome, retry: () => void) => {
    if (outcome.state === 'open') {
      setGate({ phase: 'open', development: outcome.development })
      return
    }
    if (outcome.state === 'refused') {
      setGate({ phase: 'refused', message: outcome.message })
      return
    }
    setGate({ phase: 'unreachable', message: outcome.message, retry })
  }, [])

  const run = useCallback(async () => {
    const plan = planLaunch({
      search: window.location.search,
      hasLabSession: getToken() !== null,
    })

    if (plan.action === 'resume') {
      //: A stored session. Whether it is still valid is the server's call, and
      //: it makes it on the first request the app sends; a 401 lands on the
      //: subscription below rather than being guessed at here.
      setGate({ phase: 'open', development: false })
      return
    }

    if (plan.action === 'sign-in') {
      setGate({ phase: 'leaving' })
      window.location.replace(hubSignInUrl(window.location.href))
      return
    }

    setGate({ phase: 'checking' })

    if (plan.action === 'development') {
      const retry = () => void run()
      apply(await openDevelopmentSession(), retry)
      return
    }

    //: Out of the address bar first, then spent. The token is held in this
    //: closure so a retry after a network failure still has one to present —
    //: the hub allows the same launch to be verified again within its replay
    //: window, and a lost token would mean a trip back to the dashboard.
    stripLaunchToken()
    const retry = () => {
      setGate({ phase: 'checking' })
      void openLabSession(plan.token).then((outcome) => apply(outcome, retry))
    }
    apply(await openLabSession(plan.token), retry)
  }, [apply])

  useEffect(() => {
    if (started.current) return
    started.current = true
    void run()
  }, [run])

  useEffect(() => {
    //: The server rejected the token mid-session: it expired, or the account
    //: was closed. Nothing the lab can do about it, and pretending otherwise
    //: would leave every screen showing its own error.
    return onUnauthorized(() => {
      clearLabSession()
      setGate({ phase: 'ended' })
    })
  }, [])

  if (gate.phase === 'open') {
    return (
      <>
        {gate.development ? (
          <div className="note caution" role="status">
            Development session: NanoSchool has not verified anyone. Nothing here is
            attributed to a real account.
          </div>
        ) : null}
        {children}
      </>
    )
  }

  if (gate.phase === 'checking') {
    return (
      <Shell title="Opening your lab session" busy>
        <p>Checking your launch with NanoSchool.</p>
      </Shell>
    )
  }

  if (gate.phase === 'leaving') {
    return (
      <Shell title="Taking you to NanoSchool" busy>
        <p>
          This lab opens from your NanoSchool dashboard, which is where your programme
          enrolment lives.
        </p>
      </Shell>
    )
  }

  if (gate.phase === 'unreachable') {
    return (
      <Shell title="Could not open your session">
        <p>{gate.message}</p>
        <p className="muted">
          This is a connection problem rather than a problem with your account.
        </p>
        <div className="row">
          <button type="button" onClick={gate.retry}>Try again</button>
          <a className="button secondary" href={hubLabsUrl()}>Back to Labs</a>
        </div>
      </Shell>
    )
  }

  if (gate.phase === 'ended') {
    return (
      <Shell title="Your lab session has ended">
        <p>
          Lab sessions expire, and yours has. Your runs, reports and capstone are
          untouched — launch the lab again from your dashboard to pick them up.
        </p>
        <div className="row">
          <a className="button" href={hubLabsUrl()}>Return to NanoSchool</a>
        </div>
      </Shell>
    )
  }

  return (
    <Shell title="NanoSchool did not open this lab">
      <p>{gate.message}</p>
      <p className="muted">
        Launch links are single-use and short-lived, so an old one, a copied address or a
        bookmarked link will land here. Opening the lab from your dashboard issues a new one.
      </p>
      <div className="row">
        <a className="button" href={hubLabsUrl()}>Back to Labs</a>
      </div>
    </Shell>
  )
}
