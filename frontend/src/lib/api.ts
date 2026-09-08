/** Thin API client. Entitlement decisions are the server's; this only relays. */

const TOKEN_KEY = 'omicslab.token'

/** Fired when the server rejects the stored token, so the session can reset. */
const UNAUTHORIZED_EVENT = 'omicslab:unauthorized'

/** A request that has not answered by now is treated as a network failure. */
const REQUEST_TIMEOUT_MS = 30_000

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    //: Private browsing modes and blocked site data both throw here.
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* the session simply does not survive a reload */
  }
}

export function onUnauthorized(handler: () => void): () => void {
  window.addEventListener(UNAUTHORIZED_EVENT, handler)
  return () => window.removeEventListener(UNAUTHORIZED_EVENT, handler)
}

export class ApiError extends Error {
  status: number
  detail: unknown
  /** The server's request id, when it sent one. Quote it in a bug report. */
  requestId: string | null

  constructor(status: number, detail: unknown, message: string, requestId: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.requestId = requestId
  }

  /** The upgrade copy the server sent with a 403, when it sent one. */
  get entitlementMessage(): string | null {
    const detail = this.detail as { message?: string; error?: string } | undefined
    if (detail && detail.error === 'entitlement_required') return detail.message ?? null
    return null
  }

  /** Per-field messages from a 422, keyed by field name. */
  get fieldErrors(): Record<string, string> {
    const detail = this.detail as { fields?: Record<string, string> } | undefined
    return detail?.fields ?? {}
  }

  /** True when the request never reached the server. */
  get isNetworkError(): boolean {
    return this.status === 0
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  let response: Response
  try {
    response = await fetch(path, {
      ...options,
      signal: options.signal ?? controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers ?? {}),
      },
    })
  } catch (cause) {
    //: Distinguish "the server said no" from "the server was never reached":
    //: they need different things from the reader.
    if ((cause as Error)?.name === 'AbortError' && !options.signal) {
      throw new ApiError(0, null, 'The server took too long to answer. Check your connection and try again.')
    }
    if ((cause as Error)?.name === 'AbortError') throw cause
    throw new ApiError(0, null, 'Could not reach the server. Check your connection and try again.')
  } finally {
    clearTimeout(timeout)
  }

  const requestId = response.headers.get('X-Request-ID')
  const text = await response.text()
  let body: any = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = null
  }

  if (!response.ok) {
    //: An expired or invalid token: drop it and let the app return to sign-in
    //: rather than leaving every subsequent screen showing an error.
    if (response.status === 401) {
      setToken(null)
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    }
    const detail = body?.detail ?? body
    const message =
      typeof detail === 'string'
        ? detail
        : detail?.message ?? `Request failed (${response.status})`
    throw new ApiError(response.status, detail, message, detail?.requestId ?? requestId)
  }
  return body as T
}

export const get = <T,>(path: string, params?: Record<string, string | number | undefined>) => {
  const query = params
    ? '?' +
      new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)]),
      ).toString()
    : ''
  return api<T>(`${path}${query}`)
}

export const post = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(body) })

/** Human-readable message for anything thrown by this client. */
export function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}

export function requestIdOf(error: unknown): string | null {
  return error instanceof ApiError ? error.requestId : null
}
