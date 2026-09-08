/**
 * Inline SVG icons.
 *
 * Inline rather than an icon package: the bundle stays small, and the strokes
 * inherit `currentColor` so a tile recolours with its theme token.
 */
import type { ReactNode } from 'react'

const base = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
}

/** Bulk RNA-seq: a column chart of expression across conditions. */
const Foundation = (
  <svg {...base}>
    <path d="M4 20V10M9.5 20V4M15 20v-7M20.5 20V7" />
  </svg>
)

/** Single-cell: discrete populations in a reduced-dimension embedding. */
const Core = (
  <svg {...base}>
    <circle cx="8" cy="8.5" r="3.2" />
    <circle cx="16.5" cy="7" r="2.2" />
    <circle cx="14" cy="16" r="3.6" />
  </svg>
)

/** Spatial: a capture array over tissue. */
const Advanced = (
  <svg {...base}>
    <rect x="3.5" y="3.5" width="17" height="17" rx="3" />
    <path d="M3.5 9.5h17M3.5 15h17M9.5 3.5v17M15 3.5v17" />
  </svg>
)

export const TRACK_ICONS: Record<string, ReactNode> = {
  foundation: Foundation,
  core: Core,
  advanced: Advanced,
  default: Core,
}
