/**
 * The NanoSchool account this session belongs to.
 *
 * Reading only. The identity is recorded once, by LabAuthGuard, from the
 * lab-session response — which came from this lab's API, which got it from the
 * hub. That is the whole chain, and no part of it starts here: a component that
 * could also *establish* an identity would be a second answer to the question
 * "who is this?", and the two would eventually disagree.
 *
 * Every session in this lab has one, because a launch is the only way in. The
 * exception is a development session (`VITE_DISABLE_LAB_AUTH` with the API's
 * matching switch), where nobody has been verified and there is deliberately no
 * identity to hand out — the governance screens then say so rather than filing
 * an undertaking against an account nobody can name.
 */
import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { getIdentity, subscribeToIdentity } from '../lib/hub/identity'
import type { LabIdentity } from '../lib/hub/identity'

export type HubStatus = 'none' | 'signed-in'

interface HubSessionValue {
  identity: LabIdentity | null
  status: HubStatus
  /** Why there is no session, when that needs saying on screen. */
  message: string
}

const HubSessionContext = createContext<HubSessionValue>({
  identity: null,
  status: 'none',
  message: '',
})

export function useHubSession(): HubSessionValue {
  return useContext(HubSessionContext)
}

export function HubSessionProvider({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<LabIdentity | null>(() => getIdentity())

  useEffect(() => subscribeToIdentity(setIdentity), [])

  const value = useMemo<HubSessionValue>(
    () => ({
      identity,
      status: identity ? 'signed-in' : 'none',
      message: identity
        ? ''
        : 'This session was not opened from a NanoSchool dashboard, so there is no ' +
          'account to record feedback or a review against.',
    }),
    [identity],
  )

  return <HubSessionContext.Provider value={value}>{children}</HubSessionContext.Provider>
}
