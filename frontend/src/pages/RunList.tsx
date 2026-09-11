import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, messageOf } from '../lib/api'
import { LockNote } from '../components/Locked'
import type { ParameterDescriptor, RunSummary } from '../lib/types'
import { useSession } from '../components/Session'
import { isInFlight } from '../lib/usePolledRun'
import { EmptyState, ErrorNote, PageHeader, Skeleton, StatusPill } from '../components/ui'
import { STEP_LABEL, TRACK_NAME, formatDate, named, plural } from '../lib/labels'

const TRACKS = ['foundation', 'core', 'advanced'] as const

export function RunList() {
  const { matrix } = useSession()
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [track, setTrack] = useState<string>('core')
  const [panel, setPanel] = useState<{ scope: string; parameters: ParameterDescriptor[] } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    void get<RunSummary[]>('/api/runs')
      .then(setRuns)
      .catch((e) => {
        setRuns([])
        setError(messageOf(e))
      })
  }, [])

  useEffect(() => {
    setPanel(null)
    void get<{ scope: string; parameters: ParameterDescriptor[] }>(`/api/runs/parameters/${track}`)
      .then(setPanel)
      .catch(() => setPanel({ scope: '', parameters: [] }))
  }, [track])

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

  const weekly = matrix?.allowance.runsPerModulePerWeek

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
              <table className="stacked">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Track</th>
                    <th>Status</th>
                    <th>Pipeline</th>
                    <th>Kind</th>
                    <th>Finished</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.id}>
                      <td data-label="Run">
                        <Link className="mono" to={`/runs/${run.id}`}>
                          {run.id.slice(0, 8)}
                        </Link>
                      </td>
                      <td data-label="Track">{named(TRACK_NAME, run.track)}</td>
                      <td data-label="Status">
                        <StatusPill status={run.status} />
                      </td>
                      <td data-label="Pipeline" className="mono small">
                        {run.pipelineVersion}
                      </td>
                      <td data-label="Kind">{run.isOriginal ? 'Original' : 'Alternate settings'}</td>
                      <td data-label="Finished">{formatDate(run.finishedAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Parameters available to you</h3>
          <div className="segmented" role="group" aria-label="Analysis track">
            {TRACKS.map((key) => (
              <button key={key} type="button" aria-pressed={track === key} onClick={() => setTrack(key)}>
                {TRACK_NAME[key]}
              </button>
            ))}
          </div>
        </div>
        <p className="hint">
          Range scope: <strong>{panel?.scope || '—'}</strong> ·{' '}
          {weekly === null || weekly === undefined
            ? 'unmetered runs'
            : `${plural(weekly, 'run')} per module per week`}
        </p>
        <LockNote feature="parameters_full" />
        {panel === null ? (
          <Skeleton lines={3} title={false} />
        ) : panel.parameters.length === 0 ? (
          <p className="hint">No learner-set parameters are registered for this track.</p>
        ) : (
          <div className="scroll">
            <table className="stacked">
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th>Step</th>
                  <th>Default</th>
                  <th>Range you may set</th>
                </tr>
              </thead>
              <tbody>
                {panel.parameters.map((parameter) => (
                  <tr key={parameter.key}>
                    <td data-label="Parameter" className="stack-block">
                      {parameter.label}
                      <div className="hint">{parameter.methodRule}</div>
                      {parameter.caveat ? <div className="caveat">{parameter.caveat}</div> : null}
                    </td>
                    <td data-label="Step">{named(STEP_LABEL, parameter.step)}</td>
                    <td data-label="Default">{String(parameter.default)}</td>
                    <td data-label="Range">
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
        )}
      </div>
    </>
  )
}
