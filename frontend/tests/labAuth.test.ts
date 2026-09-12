/**
 * The gate's decisions, without a browser.
 *
 * What is worth pinning here is not the markup but the choices: which of four
 * things to do on load, and which of three answers a failed exchange is. Both
 * have a wrong version that looks fine on screen — a stored session honoured
 * over a fresh launch (someone else's work, on a shared machine), and a network
 * fault reported as a refused account (the learner blamed for a server).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  hubLabsUrl,
  hubSignInUrl,
  identityFromSession,
  openLabSession,
  outcomeFromError,
  planLaunch,
} from '../src/lib/labAuth'
import { ApiError, getToken, setToken } from '../src/lib/api'
import { getIdentity, setIdentity } from '../src/lib/hub/identity'
import { getHubSessionToken, setHubSessionToken } from '../src/lib/hub/hub'

describe('planLaunch', () => {
  it('spends a launch token from the address bar', () => {
    expect(planLaunch({ search: '?auth_token=abc123', hasLabSession: false })).toEqual({
      action: 'exchange',
      token: 'abc123',
    })
  })

  it('prefers a fresh launch over a session this browser already holds', () => {
    //: Arriving from the dashboard is how someone switches account. Honouring
    //: the stored session instead would show them the previous learner's work.
    expect(planLaunch({ search: '?auth_token=abc123', hasLabSession: true })).toEqual({
      action: 'exchange',
      token: 'abc123',
    })
  })

  it('resumes a session already held when no token is presented', () => {
    expect(planLaunch({ search: '', hasLabSession: true })).toEqual({ action: 'resume' })
  })

  it('sends a visitor with nothing to the hub, not to a sign-in of our own', () => {
    expect(planLaunch({ search: '', hasLabSession: false })).toEqual({ action: 'sign-in' })
  })

  it('treats an empty or blank token as no token', () => {
    expect(planLaunch({ search: '?auth_token=', hasLabSession: false }).action).toBe('sign-in')
    expect(planLaunch({ search: '?auth_token=%20%20', hasLabSession: false }).action).toBe(
      'sign-in',
    )
  })

  it('ignores other query parameters', () => {
    expect(
      planLaunch({ search: '?utm_source=email&auth_token=abc&week=3', hasLabSession: false }),
    ).toEqual({ action: 'exchange', token: 'abc' })
  })

  it('uses the development path only when that build asked for it', () => {
    expect(
      planLaunch({ search: '', hasLabSession: false, developmentMode: true }).action,
    ).toBe('development')
    //: And never in preference to a real launch.
    expect(
      planLaunch({ search: '?auth_token=abc', hasLabSession: false, developmentMode: true })
        .action,
    ).toBe('exchange')
  })
})

describe('hub addresses', () => {
  it('sends the visitor back to where they came from after signing in', () => {
    const url = hubSignInUrl('https://omicslab.live-labs.org/runs/42?tab=qc')
    expect(url.startsWith(`${hubLabsUrl().replace(/\/labs$/, '')}/login?callbackUrl=`)).toBe(true)
    expect(url).toContain(encodeURIComponent('https://omicslab.live-labs.org/runs/42?tab=qc'))
  })
})

describe('identityFromSession', () => {
  const payload = {
    access_token: 'lab-token',
    identity: {
      userId: 'hub-1',
      email: 'learner@nanoschool.example',
      name: 'A Learner',
      role: 'super_admin',
      labId: 'lab-1',
      labSlug: 'omicslab',
      isReviewer: true,
    },
  }

  it('reads the account the server named', () => {
    expect(identityFromSession(payload)).toEqual({
      userId: 'hub-1',
      email: 'learner@nanoschool.example',
      name: 'A Learner',
      //: Upper-cased, because every comparison against it is upper-case.
      role: 'SUPER_ADMIN',
      labId: 'lab-1',
      labSlug: 'omicslab',
      isReviewer: true,
    })
  })

  it('refuses to invent an identity when the response names no account', () => {
    //: A session nobody can name must not scope anything. A placeholder here is
    //: how a whole browser once came to share one project history.
    expect(identityFromSession({ access_token: 't' })).toBeNull()
    expect(identityFromSession({ access_token: 't', identity: { userId: '  ' } })).toBeNull()
    expect(identityFromSession(null)).toBeNull()
  })

  it('defaults a missing role and reviewer flag to the closed position', () => {
    const identity = identityFromSession({
      access_token: 't',
      identity: { userId: 'hub-2' },
    })
    expect(identity?.role).toBe('USER')
    expect(identity?.isReviewer).toBe(false)
  })

  it('treats anything but a literal true as not a reviewer', () => {
    for (const value of ['true', 1, {}, null]) {
      const identity = identityFromSession({
        access_token: 't',
        identity: { userId: 'hub-3', isReviewer: value as never },
      })
      expect(identity?.isReviewer).toBe(false)
    }
  })
})

describe('what a failed exchange means', () => {
  it('calls the hub’s considered no a refusal, carrying its reason', () => {
    const outcome = outcomeFromError(
      new ApiError(403, { error: 'launch_refused' }, 'You are not authorized to access this lab.'),
    )
    expect(outcome).toEqual({
      state: 'refused',
      message: 'You are not authorized to access this lab.',
    })
  })

  it('calls a hub that did not answer unreachable, not a refusal', () => {
    //: 503 is this lab saying it could not ask. Sending someone to sign in
    //: again cannot fix that, and telling them their account was refused would
    //: be a lie about where the fault is.
    expect(outcomeFromError(new ApiError(503, null, 'Could not reach NanoSchool.')).state).toBe(
      'unreachable',
    )
    expect(outcomeFromError(new ApiError(0, null, 'Could not reach the server.')).state).toBe(
      'unreachable',
    )
    expect(outcomeFromError(new Error('boom')).state).toBe('unreachable')
  })

  it('explains a rate limit in its own terms', () => {
    const outcome = outcomeFromError(new ApiError(429, null, 'Too many requests'))
    expect(outcome.state).toBe('unreachable')
    expect(outcome.message).toContain('Wait a few minutes')
  })
})

describe('openLabSession', () => {
  const origin = 'https://omicslab.live-labs.org'

  /** Just enough of the Storage interface for the session to be stored. */
  function memoryStorage(): Storage {
    const entries = new Map<string, string>()
    return {
      get length() {
        return entries.size
      },
      key: (index: number) => [...entries.keys()][index] ?? null,
      getItem: (key: string) => (entries.has(key) ? entries.get(key)! : null),
      setItem: (key: string, value: string) => void entries.set(key, String(value)),
      removeItem: (key: string) => void entries.delete(key),
      clear: () => entries.clear(),
    } as Storage
  }

  beforeEach(() => {
    //: No jsdom in this suite: the handful of browser globals the exchange
    //: touches are supplied directly, which also keeps the test honest about
    //: exactly which ones it depends on.
    ;(globalThis as Record<string, unknown>).window = { location: { origin } }
    vi.stubGlobal('localStorage', memoryStorage())
    vi.stubGlobal('sessionStorage', memoryStorage())
    setToken(null)
    setIdentity(null)
    setHubSessionToken(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    delete (globalThis as Record<string, unknown>).window
  })

  function stubFetch(status: number, body: unknown) {
    const calls: { url: string; body: unknown }[] = []
    vi.stubGlobal('fetch', (url: string, init: RequestInit) => {
      calls.push({ url, body: JSON.parse(String(init.body)) })
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    })
    return calls
  }

  it('presents the launch token to this lab’s API and keeps what comes back', async () => {
    const calls = stubFetch(200, {
      access_token: 'lab-session-token',
      identity: { userId: 'hub-9', email: 'a@b.example', name: 'A', role: 'USER' },
      hubSessionToken: 'hub-session-token',
    })

    const outcome = await openLabSession('launch-abc')

    //: The hub is never called from the browser: only our own API is.
    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe('/api/auth/lab-session')
    expect(calls[0].body).toEqual({ token: 'launch-abc', domainUrl: origin })

    expect(outcome.state).toBe('open')
    expect(getToken()).toBe('lab-session-token')
    expect(getIdentity()?.userId).toBe('hub-9')
    //: Held for the browser's own calls to NanoSchool: feedback, the reviewer
    //: agreement, the review form.
    expect(getHubSessionToken()).toBe('hub-session-token')
  })

  it('leaves nothing behind when the launch is refused', async () => {
    setToken('a-previous-session')
    setIdentity({
      userId: 'someone-else',
      email: null,
      name: null,
      role: 'USER',
      labId: null,
      labSlug: null,
      isReviewer: false,
    })
    stubFetch(403, { detail: { error: 'launch_refused', message: 'Launch link already used.' } })

    const outcome = await openLabSession('stale-token')

    expect(outcome).toEqual({ state: 'refused', message: 'Launch link already used.' })
    //: A refusal that left the previous learner's session in place would be
    //: worse than no gate at all.
    expect(getToken()).toBeNull()
    expect(getIdentity()).toBeNull()
    expect(getHubSessionToken()).toBeNull()
  })

  it('does not open a session when the response names no account', async () => {
    stubFetch(200, { access_token: 'lab-token', identity: {} })
    const outcome = await openLabSession('launch-abc')
    expect(outcome.state).toBe('open')
    //: The token is usable — the server issued it — but nothing is attributed
    //: to an account nobody can name, and the governance screens stay shut.
    expect(getIdentity()).toBeNull()
  })
})
