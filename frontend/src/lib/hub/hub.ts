/**
 * Where the hub is, and the session credential for talking to it.
 *
 * The lab runs on its own origin and holds no cookie for live-labs.org, so
 * every call back to the hub carries the session token that `authorize-lab`
 * issued after verifying the launch. That token is deliberately not the launch
 * token: the launch token rides in a URL, lives five minutes, and is
 * replay-checked, so a lab using it as an API credential would stop working
 * part-way through the learner's first project.
 *
 * The base URL is a build-time variable with a sensible default, so a normal
 * deployment needs no configuration and a staging deployment needs one line.
 *
 * In this lab the hub session sits alongside the lab's own account system
 * rather than replacing it. OmicsLab signs its own learners in and stores their
 * runs; the credential here is only for the three governance screens, which
 * belong to NanoSchool rather than to this lab: feedback, the reviewer
 * agreement and the expert review form. A learner without a hub session uses
 * every scientific screen exactly as before.
 */

function env(name: string): string | undefined {
  //: Vite inlines this at build time, and the test runner is Vite's own, so
  //: there is one source here rather than the process.env fallback the other
  //: labs carry for their Node-typed test setups.
  const value = (import.meta as { env?: Record<string, string | undefined> }).env?.[name];
  return value && value.trim() !== '' ? value.trim() : undefined;
}

/** The hub. Override for a staging platform; trailing slashes are tolerated. */
export function hubBaseUrl(): string {
  return (env('VITE_HUB_URL') ?? 'https://live-labs.org').replace(/\/+$/, '');
}

export const hubEndpoints = {
  authorize: () => `${hubBaseUrl()}/api/auth/authorize-lab`,
};

/* ------------------------------------------------------------------ *
 * The session credential
 * ------------------------------------------------------------------ */

const SESSION_TOKEN_KEY = '__lab_session_token';

/**
 * sessionStorage, not localStorage, and the distinction is the point: a
 * credential that outlived the browser session would keep working on a shared
 * machine after the learner had walked away from it.
 */
export function setHubSessionToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(SESSION_TOKEN_KEY, token);
    else sessionStorage.removeItem(SESSION_TOKEN_KEY);
  } catch {
    /* Private mode — the session simply has no server-side storage. */
  }
}

export function getHubSessionToken(): string | null {
  try {
    return sessionStorage.getItem(SESSION_TOKEN_KEY);
  } catch {
    return null;
  }
}

/** True when this session can reach the hub on the learner's behalf. */
export function hasHubSession(): boolean {
  return getHubSessionToken() !== null;
}

/**
 * A hub request carrying the session token.
 *
 * Times out rather than hanging: this sits behind the project history screen
 * and the access check, and a hub that is slow to answer must degrade to the
 * local cache rather than leaving a spinner on screen indefinitely.
 */
export async function hubFetch(
  url: string,
  init: RequestInit = {},
  timeoutMs = 15_000,
  fetchImpl: typeof fetch = fetch,
): Promise<Response> {
  const token = getHubSessionToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetchImpl(url, {
      ...init,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init.headers ?? {}),
      },
    });
  } finally {
    clearTimeout(timer);
  }
}
