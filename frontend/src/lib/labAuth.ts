/**
 * Getting into the lab.
 *
 * OmicsLab has no sign-in screen. A learner opens it from their NanoSchool
 * dashboard, which appends a one-shot launch token to the address; that token
 * is handed to this lab's own API, which asks the hub who it belongs to and
 * issues a lab session. The sibling Live Labs do the asking in the browser
 * because they have no server; this one does not, and
 * ``backend/app/core/hub.py`` explains why at length. The short version: the
 * work is stored server-side against an account, so the server has to be the
 * one that decides whose account it is.
 *
 * The decision of what to do on load is kept here, as a pure function over
 * three facts, because it is the part that is easy to get wrong in a way no
 * screenshot reveals — and it is the part that had a real bug in the sibling
 * labs: an effect that ran twice, stripped the token on the first pass, and
 * concluded on the second that the visitor had never brought one.
 */
import { ApiError, post, setToken } from './api'
import { hubBaseUrl } from './hub/hub'
import { setHubSessionToken } from './hub/hub'
import type { LabIdentity } from './hub/identity'
import { setIdentity } from './hub/identity'

/** The query parameter NanoSchool launches with. Its name is the hub's. */
export const LAUNCH_PARAM = 'auth_token'

/** Set to 'true' for a local run with no hub. Never in a hosted build. */
const AUTH_DISABLED = import.meta.env.VITE_DISABLE_LAB_AUTH === 'true'

export type LaunchPlan =
  /** A launch token is in the address: spend it on a lab session. */
  | { action: 'exchange'; token: string }
  /** This browser already holds a lab session; carry on into the lab. */
  | { action: 'resume' }
  /** Nothing to go on. Only the hub can start a session, so go there. */
  | { action: 'sign-in' }
  /** Local development: ask the API for a session with no hub at all. */
  | { action: 'development' }

/**
 * What to do with this page load.
 *
 * A launch token wins over a stored session: arriving from the dashboard is how
 * someone switches account, and honouring the old session instead would show
 * them somebody else's work on a shared machine.
 */
export function planLaunch(params: {
  /** ``window.location.search``. */
  search: string
  /** Whether a lab session token is already stored. */
  hasLabSession: boolean
  /** Whether the no-hub development path is compiled in. */
  developmentMode?: boolean
}): LaunchPlan {
  const token = new URLSearchParams(params.search).get(LAUNCH_PARAM)?.trim()
  if (token) return { action: 'exchange', token }
  if (params.hasLabSession) return { action: 'resume' }
  if (params.developmentMode ?? AUTH_DISABLED) return { action: 'development' }
  return { action: 'sign-in' }
}

/** Where to send someone who needs to start at the hub. */
export function hubSignInUrl(returnTo: string): string {
  return `${hubBaseUrl()}/login?callbackUrl=${encodeURIComponent(returnTo)}`
}

/** The hub's own catalogue of labs — the way back out of this one. */
export function hubLabsUrl(): string {
  return `${hubBaseUrl()}/labs`
}

/**
 * Take the launch token out of the address bar.
 *
 * Before the network call rather than after it: the value is already in hand,
 * and every extra moment is one in which it sits in history, in a screenshot,
 * or in anything the browser syncs.
 */
export function stripLaunchToken(): void {
  try {
    const url = new URL(window.location.href)
    if (!url.searchParams.has(LAUNCH_PARAM)) return
    url.searchParams.delete(LAUNCH_PARAM)
    window.history.replaceState({}, document.title, url.pathname + url.search + url.hash)
  } catch {
    /* An exotic URL is not worth failing a launch over. */
  }
}

export interface LabSessionPayload {
  access_token: string
  identity?: Partial<LabIdentity> & { userId?: unknown }
  hubSessionToken?: string | null
  /** Present and true only on a development session, which says so on screen. */
  development?: boolean
}

export type SessionOutcome =
  | { state: 'open'; identity: LabIdentity | null; development: boolean }
  /** The hub answered, and the answer was no. Relaunching is the way out. */
  | { state: 'refused'; message: string }
  /** No answer — from the hub or from this lab. A retry may well work. */
  | { state: 'unreachable'; message: string }

/**
 * Build an identity from this lab's session response.
 *
 * Null rather than a partial identity when there is no user id: a session
 * nobody can name must not be used to scope anything, and inventing a
 * placeholder is exactly how a whole browser once came to share one history.
 */
export function identityFromSession(payload: LabSessionPayload | null): LabIdentity | null {
  const source = payload?.identity
  const userId = typeof source?.userId === 'string' ? source.userId.trim() : ''
  if (!userId) return null
  return {
    userId,
    email: typeof source?.email === 'string' ? source.email : null,
    name: typeof source?.name === 'string' ? source.name : null,
    role:
      typeof source?.role === 'string' && source.role.trim() !== ''
        ? source.role.trim().toUpperCase()
        : 'USER',
    labId: typeof source?.labId === 'string' ? source.labId : null,
    labSlug: typeof source?.labSlug === 'string' ? source.labSlug : null,
    //: Absent means false: a hub that predates the reviewer flag simply offers
    //: no review form, which is the safe direction for a missing field.
    isReviewer: source?.isReviewer === true,
  }
}

/** Record a session this browser may use, and who it belongs to. */
function adopt(payload: LabSessionPayload): SessionOutcome {
  setToken(payload.access_token)
  const identity = identityFromSession(payload)
  setIdentity(identity)
  setHubSessionToken(
    typeof payload.hubSessionToken === 'string' ? payload.hubSessionToken : null,
  )
  return { state: 'open', identity, development: payload.development === true }
}

/**
 * End the session and return to the hub's catalogue.
 *
 * One control rather than two, because on a shared machine the useful action is
 * always both: leave the lab *and* leave nothing behind. The lab's own token,
 * the identity and the hub credential all go; the learner's work stays on the
 * server, where the next launch picks it up.
 */
export function leaveLab(): void {
  clearLabSession()
  window.location.assign(hubLabsUrl())
}

/** Forget everything about this session. Used on the way out, and on refusal. */
export function clearLabSession(): void {
  setToken(null)
  setIdentity(null)
  setHubSessionToken(null)
}

/** Exported for the tests: this mapping is the part that must not blur. */
export function outcomeFromError(error: unknown): SessionOutcome {
  if (error instanceof ApiError) {
    //: 403 is the hub's considered no; 503 is this lab saying it could not ask.
    //: They need different things from the reader, so they are not merged.
    if (error.status === 403) return { state: 'refused', message: error.message }
    if (error.status === 429) {
      return {
        state: 'unreachable',
        message:
          'Too many attempts to open a session from this address. Wait a few minutes and try again.',
      }
    }
    return { state: 'unreachable', message: error.message }
  }
  return { state: 'unreachable', message: 'Could not open a lab session.' }
}

/** Spend a launch token on a lab session. */
export async function openLabSession(token: string): Promise<SessionOutcome> {
  //: Anything this browser held belonged to whoever launched last. Cleared
  //: before the exchange so a refusal cannot leave a stale session in place.
  clearLabSession()
  try {
    const payload = await post<LabSessionPayload>('/api/auth/lab-session', {
      token,
      domainUrl: window.location.origin,
    })
    return adopt(payload)
  } catch (error) {
    return outcomeFromError(error)
  }
}

/** Open a session with no hub. Requires the API's development switch too. */
export async function openDevelopmentSession(): Promise<SessionOutcome> {
  try {
    return adopt(await post<LabSessionPayload>('/api/auth/dev-session', {}))
  } catch (error) {
    const outcome = outcomeFromError(error)
    if (error instanceof ApiError && error.status === 404) {
      return {
        state: 'refused',
        message:
          'This build was made with VITE_DISABLE_LAB_AUTH=true, but the API has no ' +
          'development session. Set OMICSLAB_DEV_LAB_SESSION=true on the API, or ' +
          'open the lab from NanoSchool.',
      }
    }
    return outcome
  }
}
