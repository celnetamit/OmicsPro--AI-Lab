import { useEffect, useRef, useState } from 'react'
import { get } from './api'
import type { RunSummary } from './types'

/** Statuses that will still change on their own. */
export const RUN_IN_FLIGHT = ['queued', 'validating', 'running']

export function isInFlight(status: string | undefined): boolean {
  return !!status && RUN_IN_FLIGHT.includes(status)
}

/**
 * Poll a run while the server is still working on it.
 *
 * Pipelines execute on the API's worker pool rather than inside the request
 * that created them, so a freshly created run arrives queued and reaches its
 * result later. Polling backs off from 1.5s to 8s so a long Advanced run does
 * not generate hundreds of requests, and stops the moment the run is terminal.
 */
export function usePolledRun(
  run: RunSummary | null,
  onUpdate: (run: RunSummary) => void,
): boolean {
  const [polling, setPolling] = useState(false)
  const updateRef = useRef(onUpdate)
  updateRef.current = onUpdate

  const runId = run?.id
  const status = run?.status

  useEffect(() => {
    if (!runId || !isInFlight(status)) {
      setPolling(false)
      return
    }
    setPolling(true)
    let cancelled = false
    let delay = 1500
    let timer: number

    const tick = async () => {
      try {
        const latest = await get<RunSummary>(`/api/runs/${runId}`)
        if (cancelled) return
        updateRef.current(latest)
        if (!isInFlight(latest.status)) {
          setPolling(false)
          return
        }
      } catch {
        //: A blip mid-run is not worth surfacing: the next poll either
        //: recovers or the request that follows reports the real failure.
      }
      if (cancelled) return
      delay = Math.min(delay * 1.4, 8000)
      timer = window.setTimeout(tick, delay)
    }

    timer = window.setTimeout(tick, delay)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
      setPolling(false)
    }
  }, [runId, status])

  return polling
}
