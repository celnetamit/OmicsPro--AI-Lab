import type { EvidenceRef, InterpretationLabel } from '../lib/types'

const LABEL_TEXT: Record<InterpretationLabel, string> = {
  supported: 'Supported',
  partially_supported: 'Partially Supported',
  needs_validation: 'Needs Validation',
  speculative: 'Speculative',
}

export function EvidenceList({ sources }: { sources: EvidenceRef[] }) {
  if (!sources?.length) return null
  return (
    <div className="evidence">
      <strong>Evidence</strong>
      <ul>
        {sources.map((source) => (
          <li key={source.id}>
            <em>{source.source_type}</em> — {source.title} ({source.reference})
          </li>
        ))}
      </ul>
    </div>
  )
}

export function LabelPill({
  label,
  rationale,
}: {
  label: InterpretationLabel
  rationale?: string
}) {
  return (
    <div>
      <span className={`label-pill label-${label}`}>{LABEL_TEXT[label]}</span>
      {rationale ? <p className="hint">{rationale}</p> : null}
    </div>
  )
}

export function Caveats({ items }: { items: string[] }) {
  if (!items?.length) return null
  return (
    <>
      {items.map((item) => (
        <p className="caveat" key={item}>
          {item}
        </p>
      ))}
    </>
  )
}
