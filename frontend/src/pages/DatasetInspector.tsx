import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, get, post } from '../lib/api'
import { PageHeader, Skeleton } from '../components/ui'
import type { RunSummary } from '../lib/types'

interface Inspection {
  shape: number[]
  nFeatures: number
  metadataFields: string[]
  groups: Record<string, Record<string, number>>
  missingness: Record<string, number>
  preview: Record<string, string>[]
}

interface ModuleRow {
  module: string
  label: string
  track: string
  unlocked: boolean
  requiredTier: string
  lockedExplanation: string
}

interface Detail {
  id: string
  name: string
  track: string
  description: string
  limitations: string[]
  provenance: Record<string, string>
  inspection: Inspection | null
  unavailableReason?: string
}

export function DatasetInspector() {
  const { datasetId } = useParams()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<Detail | null>(null)
  const [modules, setModules] = useState<ModuleRow[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void get<Detail>(`/api/datasets/${datasetId}`)
      .then(setDetail)
      .catch((e: ApiError) => setError(e.message))
    void get<{ availableModules: ModuleRow[] }>('/api/program/home').then((home) =>
      setModules(home.availableModules ?? []),
    )
  }, [datasetId])

  async function startRun(module?: string) {
    if (!detail) return
    setBusy(true)
    setError('')
    try {
      // No parameter overrides: this is the guided run every learner can start.
      const run = await post<RunSummary>('/api/runs', {
        dataset_id: detail.id,
        track: detail.track,
        module: module ?? null,
      })
      navigate(`/runs/${run.id}`)
    } catch (e) {
      setError((e as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  if (error) return <p className="warning">{error}</p>
  if (!detail) {
    return (
      <>
        <PageHeader title="Dataset" />
        <Skeleton lines={4} />
        <span className="visually-hidden" role="status">
          Loading
        </span>
      </>
    )
  }

  return (
    <>
      <h2>{detail.name}</h2>
      <p className="lede">{detail.description}</p>

      <div className="card">
        <h3>Provenance</h3>
        <table>
          <tbody>
            {Object.entries(detail.provenance).map(([key, value]) => (
              <tr key={key}>
                <th style={{ width: 180 }}>{key}</th>
                <td>{String(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail.limitations.map((limitation) => (
        <p className="caveat" key={limitation}>
          {limitation}
        </p>
      ))}

      {detail.inspection ? (
        <>
          <div className="card">
            <h3>Contents</h3>
            <p>
              {detail.inspection.shape[0]} rows × {detail.inspection.shape[1]} columns ·{' '}
              {detail.inspection.nFeatures} features
            </p>
            <h4>Groups</h4>
            {Object.entries(detail.inspection.groups).map(([field, counts]) => (
              <p key={field}>
                <strong>{field}:</strong>{' '}
                {Object.entries(counts)
                  .map(([value, count]) => `${value} (${count})`)
                  .join(', ')}
              </p>
            ))}
            <h4>Missing values</h4>
            <p className="hint">
              {Object.entries(detail.inspection.missingness)
                .map(([field, count]) => `${field}: ${count}`)
                .join(' · ')}
            </p>
          </div>

          <button onClick={() => startRun()} disabled={busy}>
            {busy ? 'Starting…' : 'Start the guided analysis'}
          </button>

          {modules
            .filter((module) => module.track === detail.track)
            .map((module) => (
              <div className={`card${module.unlocked ? '' : ' locked'}`} key={module.module}>
                <span className="badge">Extension module</span>
                <h3>{module.label}</h3>
                {module.unlocked ? (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => startRun(module.module)}
                  >
                    Run this module on this dataset
                  </button>
                ) : (
                  <>
                    <p className="hint">{module.lockedExplanation}</p>
                    <Link className="button secondary" to="/upgrade">
                      Compare access options
                    </Link>
                  </>
                )}
              </div>
            ))}
        </>
      ) : (
        <p className="warning">{detail.unavailableReason}</p>
      )}
    </>
  )
}
