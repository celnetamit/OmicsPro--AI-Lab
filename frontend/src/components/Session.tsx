import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { get, getToken, onUnauthorized, setToken } from '../lib/api'
import type { EntitlementMatrix, FeatureRow, Me } from '../lib/types'

interface SessionValue {
  me: Me | null
  matrix: EntitlementMatrix | null
  loading: boolean
  /** Single source of truth on the client, mirroring the server matrix. */
  feature: (key: string) => FeatureRow | undefined
  can: (key: string) => boolean
  refresh: () => Promise<void>
}

const SessionContext = createContext<SessionValue | null>(null)

/**
 * Who this session belongs to, according to this lab's own API.
 *
 * It never starts a session: by the time this mounts, LabAuthGuard has already
 * exchanged a NanoSchool launch for one, so the only question here is what the
 * server says about the token in hand. That split is deliberate — a component
 * that could both read *and* create a session is one that can paper over a
 * failed launch by quietly opening a different kind of session, which is what
 * the removed guest endpoint used to do.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [matrix, setMatrix] = useState<EntitlementMatrix | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setMe(null)
      setMatrix(null)
      setLoading(false)
      return
    }
    try {
      const [profile, entitlements] = await Promise.all([
        get<Me>('/api/auth/me'),
        get<EntitlementMatrix>('/api/entitlements/matrix'),
      ])
      setMe(profile)
      setMatrix(entitlements)
    } catch {
      setToken(null)
      setMe(null)
      setMatrix(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    //: The client never decides a token has expired; it reacts when the server
    //: rejects one, which also covers a revoked or deleted account. What the
    //: visitor then sees is the guard's business, not this provider's.
    return onUnauthorized(() => {
      setMe(null)
      setMatrix(null)
    })
  }, [])

  const value = useMemo<SessionValue>(() => {
    const byKey = new Map((matrix?.features ?? []).map((f) => [f.key, f]))
    return {
      me,
      matrix,
      loading,
      feature: (key) => byKey.get(key),
      // The client never decides entitlement on its own; it reads the matrix
      // the server sent, and the server checks again on every request.
      can: (key) => byKey.get(key)?.unlocked === true && byKey.get(key)?.available === true,
      refresh,
    }
  }, [me, matrix, loading, refresh])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession must be used inside SessionProvider')
  return value
}
