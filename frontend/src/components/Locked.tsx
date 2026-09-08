import { Link } from 'react-router-dom'
import { useSession } from './Session'

/**
 * Renders children when the tier carries the feature, and otherwise renders the
 * control as visible-but-locked with its explanation and an upgrade action.
 * Locked capability is never hidden (spec 2).
 */
export function Gated({ feature, children }: { feature: string; children: React.ReactNode }) {
  const { can, feature: lookup } = useSession()
  if (can(feature)) return <>{children}</>

  const row = lookup(feature)
  if (row && !row.available) {
    return (
      <div className="card locked">
        <span className="badge">Scheduled for a later release</span>
        <h3>{row.label}</h3>
        <p className="hint">
          This module is part of a later build phase and is not open yet.
        </p>
      </div>
    )
  }

  return (
    <div className="card locked">
      <span className="badge">Included with {row?.minTier ?? 'a paid'} access</span>
      <h3>{row?.label ?? feature}</h3>
      <p className="hint">{row?.lockedExplanation}</p>
      <Link className="button secondary" to="/upgrade">
        Compare access options
      </Link>
    </div>
  )
}

/** Inline lock note for a single control inside an otherwise open screen. */
export function LockNote({ feature }: { feature: string }) {
  const { can, feature: lookup } = useSession()
  if (can(feature)) return null
  const row = lookup(feature)
  return (
    <div className="caveat">
      {row?.lockedExplanation} <Link to="/upgrade">Compare access options</Link>
    </div>
  )
}
