import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, messageOf } from '../lib/api'
import { LockNote } from '../components/Locked'
import type { ParameterDescriptor, RunSummary } from '../lib/types'
import { useSession } from '../components/Session'
import { isInFlight } from '../lib/usePolledRun'
import { EmptyState, ErrorNote, PageHeader, Skeleton, StatusPill } from '../components/ui'

export function RunList() {
  const { matrix } = useSession()
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [panel, setPanel] = useState<{ scope: string; parameters: ParameterDescriptor[] } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    void get<RunSummary[]>('/api/runs')
      .then(setRuns)
      .catch((e) => {
        setRuns([])
        setError(messageOf(e))
      })
    void get<{ scope: string; parameters: ParameterDescriptor[] }>(
      '/api/runs/parameters/core',
    ).then(setPanel).catch(() => undefined)
  }, [])

  //: Runs execute on the server's worker pool, so the list refreshes itself
  //: while any of them is still in flight and settles once none are.
  const anyInFlight = (runs ?? []).some((run) => isInFlight(run.status))
  useEffect(() => {
    if (!anyInFlight) return
    const timer = window.setInterval(() => {
      void get<RunSummary[]>('/api/runs').then(setRuns).catch(() => undefined)
    }, 4000)
    return () => window.clearInterval(timer)
  }, [anyInFlight])

  return (
    <>
      <PageHeader
        title="Analysis Workspace"
        lede="Every run records its dataset, method versions, parameters and decisions, so it can be reconstructed later."
        actions={
          <Link className="button" to="/datasets">
            Start an analysis
          </Link>
        }
      />

      {error ? <ErrorNote message={error} /> : null}

      {runs === null ? (
        <>
          <Skeleton lines={4} />
          <span className="visually-hidden" role="status">
            Loading your runs
          </span>
        </>
      ) : (
        <div className="card">
          <h3>Your runs</h3>
          {runs.length === 0 ? (
            <EmptyState
              title="No analyses yet"
              action={
                <Link className="button secondary" to="/datasets">
                  Open the Dataset Selector
                </Link>
              }
            >
              Pick a dataset to start the guided analysis. Each run keeps its own record,
              so you can return to it later.
            </EmptyState>
          ) : (
            <div className="scroll">
              <table>
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Track</th>
                    <th>Status</th>
                    <th>Pipeline</th>
                    <th>Kind</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.id}>
                      <td>
                        <Link className="mono" to={`/runs/${run.id}`}>
                          {run.id.slice(0, 8)}
                        </Link>
                      </td>
                      <td>{run.track}</td>
                      <td>
                        <StatusPill status={run.status} />
                      </td>
                      <td>{run.pipelineVersion}</td>
                      <td>{run.isOriginal ? 'Original' : 'Alternate settings'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="card">
        <h3>Parameters available to you</h3>
        <p className="hint">
          Range scope: <strong>{panel?.scope ?? '—'}</strong> ·{' '}
          {matrix?.allowance.runsPerModulePerWeek === null
            ? 'unmetered runs'
            : `${matrix?.allowance.runsPerModulePerWeek} runs per module per week`}
        </p>
        <LockNote feature="parameters_full" />
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Step</th>
                <th>Default</th>
                <th>Range you may set</th>
              </tr>
            </thead>
            <tbody>
              {(panel?.parameters ?? []).map((parameter) => (
                <tr key={parameter.key}>
                  <td>
                    {parameter.label}
                    <div className="hint">{parameter.methodRule}</div>
                    {parameter.caveat ? <div className="caveat">{parameter.caveat}</div> : null}
                  </td>
                  <td>{parameter.step}</td>
                  <td>{String(parameter.default)}</td>
                  <td>
                    {parameter.min !== null
                      ? `${parameter.min} – ${parameter.max}`
                      : parameter.choices
                        ? parameter.choices.join(', ')
                        : parameter.freeform
                          ? 'free text'
                          : 'true / false'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
