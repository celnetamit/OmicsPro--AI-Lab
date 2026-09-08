import { useState } from 'react'
import type { PerturbationOffer } from '../lib/types'
import { EvidenceList } from './Evidence'

const DIRECTION_TEXT: Record<string, string> = {
  increase: 'is expected to increase',
  decrease: 'is expected to decrease',
  unchanged: 'is expected to stay unchanged',
  uncertain: 'could move in either direction',
}

/**
 * The TEST / SKIP interrupt (spec 8.1).
 *
 * It blocks execution rather than sitting beside it: there is no dismiss
 * affordance, no backdrop click-through and no default action. Expected
 * consequences are stated as direction and effect; no numeric result is
 * promised, because none has been computed yet.
 */
export function PerturbationDialog({
  offer,
  busy,
  onDecide,
}: {
  offer: PerturbationOffer
  busy: boolean
  onDecide: (decision: 'test' | 'skip') => void
}) {
  const [acknowledged, setAcknowledged] = useState(false)

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={offer.label}>
      <div className="modal">
        <span className="badge">Proposed change</span>
        <h3>{offer.label}</h3>
        <p>
          <strong>{offer.parameterKey}</strong>: {String(offer.currentValue)} →{' '}
          {String(offer.proposedValue)}
        </p>

        <h4>Why this is worth testing</h4>
        <p>{offer.scientificReason}</p>

        <h4>What to expect</h4>
        <ul>
          {offer.expectedConsequence.map((expectation) => (
            <li key={expectation.metric}>
              The {expectation.metricLabel} {DIRECTION_TEXT[expectation.direction]} —{' '}
              {expectation.reason}
            </li>
          ))}
        </ul>
        <p className="hint">
          Directions only. The Copilot does not predict a numerical result, because the
          result has not been computed.
        </p>

        <h4>What to observe</h4>
        <p>{offer.whatToObserve}</p>

        <h4>Limitation</h4>
        <p className="caveat">{offer.limitation}</p>

        <EvidenceList sources={offer.evidence} />

        <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginTop: 16 }}>
          <input
            type="checkbox"
            style={{ width: 'auto', marginTop: 4 }}
            checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)}
          />
          <span style={{ fontWeight: 400 }}>
            I have read the expected consequence and the limitation.
          </span>
        </label>

        <div className="actions">
          <button disabled={!acknowledged || busy} onClick={() => onDecide('test')}>
            {busy ? 'Running the alternate analysis…' : 'Test this'}
          </button>
          <button
            className="secondary"
            disabled={!acknowledged || busy}
            onClick={() => onDecide('skip')}
          >
            Skip
          </button>
        </div>
        <p className="hint">
          Either choice is recorded in your reproducibility log. Testing creates a second
          run; your original run is kept unchanged.
        </p>
      </div>
    </div>
  )
}
