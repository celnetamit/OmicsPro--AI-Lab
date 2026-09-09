import { Link } from 'react-router-dom'
import { useSession } from './Session'

const TIER_WORD = (tier?: string) =>
  tier ? tier.charAt(0).toUpperCase() + tier.slice(1) : 'A paid'

/**
 * Renders children when the tier carries the feature, and otherwise renders the
 * screen as visible-but-locked with its explanation and an upgrade action.
 * Locked capability is never hidden (spec 2).
 *
 * The screen it stands in already carries the feature's name in its heading, so
 * this states what the tier adds rather than repeating that name.
 */
export function Gated({ feature, children }: { feature: string; children: React.ReactNode }) {
  const { can, feature: lookup, matrix } = useSession()
  if (can(feature)) return <>{children}</>

  const row = lookup(feature)

  if (row && !row.available) {
    return (
      <div className="locked-state">
        <span className="badge">Scheduled for a later release</span>
        <h3>Not open yet</h3>
        <p>
          {row.label} is part of a later build phase. It is listed here so you can see
          what the program will cover, and it will open without any change on your side.
        </p>
      </div>
    )
  }

  //: What else the same tier carries, so a locked screen answers "what would I
  //: actually get?" rather than only "you cannot have this".
  const alsoIncluded = (matrix?.features ?? [])
    .filter((f) => f.minTier === row?.minTier && f.key !== feature && f.available)
    .slice(0, 6)

  return (
    <div className="locked-state">
      <span className="badge">Included with {TIER_WORD(row?.minTier)} access</span>
      <h3>Not included at your access level</h3>
      <p>{row?.lockedExplanation}</p>

      {alsoIncluded.length ? (
        <div className="also">
          <div className="also-title">{TIER_WORD(row?.minTier)} also adds</div>
          <ul>
            {alsoIncluded.map((f) => (
              <li key={f.key}>{f.label}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <Link className="button secondary mt-5" to="/upgrade">
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
