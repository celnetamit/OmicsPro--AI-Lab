/**
 * Shared presentation primitives.
 *
 * These exist so that "loading", "empty", "failed" and "in progress" look the
 * same on all thirteen screens. Each state says what is happening and what the
 * reader can do next; none of them communicate through colour alone.
 */
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { RunStatus } from '../lib/types'

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="loading-inline" role="status">
      <span className="spinner" aria-hidden="true" />
      {label ? <span>{label}</span> : <span className="visually-hidden">Loading</span>}
    </span>
  )
}

/** Placeholder with the shape of the content that is coming. */
export function Skeleton({ lines = 3, title = true }: { lines?: number; title?: boolean }) {
  return (
    <div className="card" aria-hidden="true">
      {title ? <div className="skeleton title" /> : null}
      {Array.from({ length: lines }, (_, index) => (
        <div key={index} className={`skeleton${index === lines - 1 ? ' line-short' : ''}`} />
      ))}
    </div>
  )
}

export function PageHeader({
  title,
  lede,
  actions,
  eyebrow,
  hero = false,
  children,
}: {
  title: string
  lede?: ReactNode
  actions?: ReactNode
  eyebrow?: string
  /** The gradient band. One per screen, at the top, never behind body copy. */
  hero?: boolean
  children?: ReactNode
}) {
  if (hero) {
    //: Centred, edge to edge: the headline is the whole point of the band.
    return (
      <header className="hero">
        {eyebrow ? <span className="hero-eyebrow">{eyebrow}</span> : null}
        <h2>{title}</h2>
        {lede ? <p className="lede">{lede}</p> : null}
        {actions ? <div className="row">{actions}</div> : null}
        {children}
      </header>
    )
  }

  return (
    <header className="page-head">
      <div className="row">
        <div>
          {eyebrow ? <span className="tag">{eyebrow}</span> : null}
          <h2>{title}</h2>
          {lede ? <p className="lede">{lede}</p> : null}
        </div>
        {actions ? <div className="row">{actions}</div> : null}
      </div>
    </header>
  )
}

/** A figure with its label, for the hero band. */
export function HeroStats({ items }: { items: { value: ReactNode; name: string }[] }) {
  return (
    <div className="hero-stats">
      {items.map((item) => (
        <div className="hero-stat" key={item.name}>
          <div className="value">{item.value}</div>
          <div className="name">{item.name}</div>
        </div>
      ))}
    </div>
  )
}

/** Bold section title with an optional action on the right. */
export function SectionHead({
  title,
  sub,
  action,
}: {
  title: string
  sub?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="section-head">
      <div>
        <h3>{title}</h3>
        {sub ? <p className="sub">{sub}</p> : null}
      </div>
      {action}
    </div>
  )
}

const STATUS_TEXT: Record<string, string> = {
  queued: 'Queued',
  validating: 'Validating',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

/** Run status as a word plus a colour, never a colour alone. */
export function StatusPill({ status }: { status: RunStatus | string }) {
  const text = STATUS_TEXT[status] ?? status
  return (
    <span className={`status status-${status}`}>
      <span className="dot" aria-hidden="true" />
      {text}
    </span>
  )
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action ? <div className="row" style={{ justifyContent: 'center', marginTop: 16 }}>{action}</div> : null}
    </div>
  )
}

/**
 * A failed request, stated plainly. ``requestId`` is shown when the server sent
 * one so a learner reporting the problem can quote the exact request.
 */
export function ErrorNote({
  message,
  requestId,
  onRetry,
}: {
  message: string
  requestId?: string | null
  onRetry?: () => void
}) {
  return (
    <div className="note warning" role="alert">
      <div className="note-body">
        <strong>That did not work</strong>
        {message}
        {requestId ? (
          <div className="small mono mt-4">Reference: {requestId}</div>
        ) : null}
      </div>
      {onRetry ? (
        <button type="button" className="secondary small" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  )
}

/** Upgrade prompt used wherever a 403 came back with the matrix's own copy. */
export function UpgradeNote({ message }: { message: string }) {
  return (
    <div className="note caution">
      <div className="note-body">
        <strong>Not included at your access level</strong>
        {message} <Link to="/upgrade">Compare access options</Link>
      </div>
    </div>
  )
}
