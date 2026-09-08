import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { get, getToken, onUnauthorized, post, setToken } from '../lib/api'
import type { EntitlementMatrix, FeatureRow, Me } from '../lib/types'

interface SessionValue {
  me: Me | null
  /** True when the deployment opens straight into the lab, with no sign-in. */
  openAccess: boolean
  matrix: EntitlementMatrix | null
  loading: boolean
  /** Single source of truth on the client, mirroring the server matrix. */
  feature: (key: string) => FeatureRow | undefined
  can: (key: string) => boolean
  refresh: () => Promise<void>
  signOut: () => void
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [matrix, setMatrix] = useState<EntitlementMatrix | null>(null)
  const [loading, setLoading] = useState(true)
  const [openAccess, setOpenAccess] = useState(false)

  const refresh = useCallback(async () => {
    if (!getToken()) {
      //: Open access: the deployment hands out a shared lab session rather
      //: than asking for credentials. A 404 means the sign-in screen is the
      //: intended entry point, so fall through to it.
      try {
        const guest = await post<{ access_token: string }>('/api/auth/guest', {})
        setToken(guest.access_token)
        setOpenAccess(true)
      } catch {
        setOpenAccess(false)
        setMe(null)
        setMatrix(null)
        setLoading(false)
        return
      }
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
    //: rejects one, which also covers a revoked or deleted account.
    return onUnauthorized(() => {
      setMe(null)
      setMatrix(null)
      //: An expired token on an open-access deployment should quietly become a
      //: fresh lab session, not a dead end the visitor cannot get past.
      setLoading(true)
      void refresh()
    })
  }, [refresh])

  const value = useMemo<SessionValue>(() => {
    const byKey = new Map((matrix?.features ?? []).map((f) => [f.key, f]))
    return {
      me,
      matrix,
      loading,
      //: The server is the authority: a visitor returning with a stored token
      //: never calls the guest endpoint, so the local flag alone would be stale.
      openAccess: me?.openAccess ?? openAccess,
      feature: (key) => byKey.get(key),
      // The client never decides entitlement on its own; it reads the matrix
      // the server sent, and the server checks again on every request.
      can: (key) => byKey.get(key)?.unlocked === true && byKey.get(key)?.available === true,
      refresh,
      signOut: () => {
        setToken(null)
        setMe(null)
        setMatrix(null)
      },
    }
  }, [me, matrix, loading, openAccess, refresh])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession must be used inside SessionProvider')
  return value
}
