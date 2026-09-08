import { useEffect, useState } from 'react'
import { get } from '../lib/api'
import { LabelPill } from '../components/Evidence'
import type { InterpretationLabel, RunSummary } from '../lib/types'

interface InteractionRow {
  id: string
  function: string
  step: string
  label: InterpretationLabel | null
  labelRationale: string
  audit: { action: string; learnerRationale: string } | null
}

/**
 * Assessment (spec 9.11): concept answers, the analytical decisions actually
 * taken, and the quality of the interpretation recorded against them.
 */
export function Assessment() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [runId, setRunId] = useState('')
  const [interactions, setInteractions] = useState<InteractionRow[]>([])
  const [interpretations, setInterpretations] = useState<any[]>([])

  useEffect(() => {
    void get<RunSummary[]>('/api/runs').then((rows) => {
      setRuns(rows)
      setRunId(rows[0]?.id ?? '')
    })
  }, [])

  useEffect(() => {
    if (!runId) return
    void get<InteractionRow[]>('/api/copilot/interactions', { run_id: runId }).then(setInteractions)
    void get<any[]>(`/api/runs/${runId}/interpretation`).then(setInterpretations)
  }, [runId])

  const reviewed = interactions.filter((row) => row.audit).length

  return (
    <>
      <h2>Assessment</h2>
      <p className="lede">
        Your concept answers sit in the Pre-Lab screen. This page assesses the decisions you
        took during analysis and how you interpreted them.
      </p>

      <div className="card">
        <label htmlFor="run">Run</label>
        <select id="run" value={runId} onChange={(e) => setRunId(e.target.value)}>
          {runs.map((run) => (
            <option key={run.id} value={run.id}>
              {run.id.slice(0, 8)} · {run.track} · {run.status}
            </option>
          ))}
        </select>
      </div>

      <div className="card">
        <h3>AI Research Audit</h3>
        <p className="hint">
          {reviewed} of {interactions.length} Copilot outputs adjudicated.
        </p>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Step</th>
                <th>Copilot function</th>
                <th>Label</th>
                <th>Your decision</th>
              </tr>
            </thead>
            <tbody>
              {interactions.map((row) => (
                <tr key={row.id}>
                  <td>{row.step}</td>
                  <td>{row.function}</td>
                  <td>{row.label ? <LabelPill label={row.label} /> : '—'}</td>
                  <td>{row.audit?.action ?? 'Not reviewed'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Interpretation quality</h3>
        {interpretations.length === 0 ? (
          <p className="hint">No interpretations recorded for this run yet.</p>
        ) : (
          interpretations.map((entry) => (
            <div key={entry.id} style={{ marginBottom: 16 }}>
              <h4>{entry.step}</h4>
              <p>
                <strong>Observation:</strong> {entry.observation || '—'}
              </p>
              <p>
                <strong>Statistical evidence:</strong> {entry.statisticalEvidence || '—'}
              </p>
              <p>
                <strong>Biological interpretation:</strong> {entry.biologicalInterpretation || '—'}
              </p>
              <p>
                <strong>Hypothesis:</strong> {entry.hypothesis || '—'}
              </p>
              {!entry.observation || !entry.statisticalEvidence ? (
                <p className="caveat">
                  An interpretation is only assessable when the observation and the
                  statistical evidence are stated separately from the biological reading.
                </p>
              ) : null}
            </div>
          ))
        )}
      </div>
    </>
  )
}
