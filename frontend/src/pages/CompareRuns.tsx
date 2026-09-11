import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError, get } from '../lib/api'
import { Gated } from '../components/Locked'
import { PageHeader } from '../components/ui'
import type { RunSummary } from '../lib/types'
import { TRACK_NAME, humanise, named } from '../lib/labels'

interface SettingRow {
  key: string
  label: string
  before: unknown
  after: unknown
  changed: boolean
  methodRule: string
}

interface MetricRow {
  metric: string
  before: number | null
  after: number | null
  changed: boolean
  direction: string | null
}

interface Comparison {
  original: RunSummary
  alternate: RunSummary
  settings: SettingRow[]
  changedSettings: SettingRow[]
  metrics: MetricRow[]
  changedConclusions: { step: string; before: string | null; after: string | null }[]
  note: string
}

export function CompareRuns() {
  return (
    <>
      <PageHeader
        title="Compare Runs"
        lede="Put an original run beside one with alternate settings and see what changed — and, of what changed, which conclusions moved with it."
      />
      <Gated feature="compare_runs">
        <Comparison />
      </Gated>
    </>
  )
}

function Comparison() {
  const [params, setParams] = useSearchParams()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [result, setResult] = useState<Comparison | null>(null)
  const [error, setError] = useState('')

  const original = params.get('original') ?? ''
  const alternate = params.get('alternate') ?? ''

  useEffect(() => {
    void get<RunSummary[]>('/api/runs').then(setRuns)
  }, [])

  useEffect(() => {
    if (!original || !alternate) {
      setResult(null)
      return
    }
    setError('')
    void get<Comparison>('/api/runs/compare/pair', { original, alternate })
      .then(setResult)
      .catch((e: ApiError) => {
        setResult(null)
        setError(e.message)
      })
  }, [original, alternate])

  function choose(side: 'original' | 'alternate', value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(side, value)
    else next.delete(side)
    setParams(next)
  }

  const completed = runs.filter((run) => run.status === 'completed')

  return (
    <>
      <div className="card">
        <div className="grid-2">
          {(['original', 'alternate'] as const).map((side) => (
            <div key={side}>
              <label htmlFor={side}>{side === 'original' ? 'Original run' : 'Alternate run'}</label>
              <select
                id={side}
                value={side === 'original' ? original : alternate}
                onChange={(event) => choose(side, event.target.value)}
              >
                <option value="">Select…</option>
                {completed.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.id.slice(0, 8)} · {named(TRACK_NAME, run.track)}
                    {run.module ? ` · ${humanise(run.module)}` : ''} ·{' '}
                    {run.isOriginal ? 'original' : 'alternate'}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <p className="hint">
          Only runs of the same track on the same dataset are comparable. Anything else
          would be comparing two different experiments.
        </p>
      </div>

      {error ? <p className="warning">{error}</p> : null}

      {result ? (
        <>
          <div className="card">
            <h3>Settings that changed</h3>
            {result.changedSettings.length === 0 ? (
              <p className="hint">These two runs used identical settings.</p>
            ) : (
              <div className="scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Setting</th>
                      <th>Original</th>
                      <th>Alternate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.changedSettings.map((row) => (
                      <tr key={row.key}>
                        <td>
                          {row.label}
                          <div className="hint">{row.methodRule}</div>
                        </td>
                        <td>{String(row.before)}</td>
                        <td>{String(row.after)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card">
            <h3>What moved</h3>
            <div className="scroll">
              <table>
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Original</th>
                    <th>Alternate</th>
                    <th>Direction</th>
                  </tr>
                </thead>
                <tbody>
                  {result.metrics
                    .filter((row) => row.changed)
                    .map((row) => (
                      <tr key={row.metric}>
                        <td>{row.metric}</td>
                        <td>{row.before === null ? '—' : row.before}</td>
                        <td>{row.after === null ? '—' : row.after}</td>
                        <td>{row.direction ?? '—'}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            <p className="caveat">{result.note}</p>
          </div>

          <div className="card">
            <h3>Conclusions that changed</h3>
            {result.changedConclusions.length === 0 ? (
              <p className="hint">
                No recorded interpretation changed its label between these runs. If you
                have not written interpretations for both, there is nothing to compare
                here yet.
              </p>
            ) : (
              <div className="scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Step</th>
                      <th>Original label</th>
                      <th>Alternate label</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.changedConclusions.map((row) => (
                      <tr key={row.step}>
                        <td>{row.step}</td>
                        <td>{row.before ?? '—'}</td>
                        <td>{row.after ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : null}
    </>
  )
}
