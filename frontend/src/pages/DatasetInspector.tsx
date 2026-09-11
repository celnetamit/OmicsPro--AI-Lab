import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, get, post } from '../lib/api'
import { PageHeader, Skeleton } from '../components/ui'
import type { RunSummary } from '../lib/types'
import { VALIDATION_LABEL, formatDate, humanise, named } from '../lib/labels'

const PROVENANCE_LABEL: Record<string, string> = {
  source: 'Source',
  accession: 'Accession',
  citation: 'Citation',
  license: 'Licence',
  importedAt: 'Imported',
  validationStatus: 'Validation',
}

function provenanceValue(key: string, value: unknown): string {
  if (key === 'importedAt') return formatDate(String(value))
  if (key === 'validationStatus') return named(VALIDATION_LABEL, String(value))
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

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

interface Analysis {
  label: string
  reason: string
}

/** The Copilot's grounded explanation of the dataset (spec 9.6). */
interface Brief {
  available: boolean
  reason?: string
  sections?: { key: string; title: string; text: string }[]
  validAnalyses?: Analysis[]
  notSupported?: Analysis[]
  evidence?: { id: string; title: string; reference: string }[]
}

function DatasetBrief({ brief }: { brief: Brief }) {
  if (!brief.available) return null
  const notSupported = brief.notSupported ?? []
  return (
    <div className="card brief">
      <div className="brief-head">
        <h3>About this dataset</h3>
        <span className="badge">Omics Copilot</span>
      </div>
      <p className="hint">
        Composed from this dataset's recorded values: every number here is read from the
        object, not written by the Copilot.
      </p>
      {brief.sections?.map((section) => (
        <section key={section.key} className="brief-section">
          <h4>{section.title}</h4>
          <p>{section.text}</p>
        </section>
      ))}
      <div className="brief-analyses">
        <div>
          <h4>Analyses this design supports</h4>
          <ul className="brief-list">
            {(brief.validAnalyses ?? []).map((analysis) => (
              <li key={analysis.label}>
                <span className="brief-mark ok" aria-hidden="true">✓</span>
                <span>
                  {analysis.label}
                  {analysis.reason ? <span className="hint"> — {analysis.reason}</span> : null}
                </span>
              </li>
            ))}
          </ul>
        </div>
        {notSupported.length ? (
          <div>
            <h4>Not supported by this design</h4>
            <ul className="brief-list">
              {notSupported.map((analysis) => (
                <li key={analysis.label}>
                  <span className="brief-mark no" aria-hidden="true">✕</span>
                  <span>
                    {analysis.label}
                    <span className="hint"> — {analysis.reason}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
      {brief.evidence?.length ? (
        <p className="hint brief-sources">
          Sources:{' '}
          {brief.evidence.map((source) => `${source.title} (${source.reference})`).join('; ')}
        </p>
      ) : null}
    </div>
  )
}

export function DatasetInspector() {
  const { datasetId } = useParams()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<Detail | null>(null)
  const [brief, setBrief] = useState<Brief | null>(null)
  const [modules, setModules] = useState<ModuleRow[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void get<Detail>(`/api/datasets/${datasetId}`)
      .then(setDetail)
      .catch((e: ApiError) => setError(e.message))
    //: The explanation is an enhancement: the inspector stands without it.
    void get<Brief>(`/api/datasets/${datasetId}/brief`)
      .then(setBrief)
      .catch(() => setBrief(null))
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
      <PageHeader
        title={detail.name}
        lede={detail.description}
        actions={
          detail.inspection ? (
            <button type="button" onClick={() => startRun()} disabled={busy}>
              {busy ? 'Starting…' : 'Start the guided analysis'}
            </button>
          ) : null
        }
      />

      <div className="card">
        <h3>Provenance</h3>
        <div className="scroll">
          <table>
            <tbody>
              {Object.entries(detail.provenance).map(([key, value]) => (
                <tr key={key}>
                  <th>{PROVENANCE_LABEL[key] ?? humanise(key)}</th>
                  <td>{provenanceValue(key, value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {detail.limitations.map((limitation) => (
        <p className="caveat" key={limitation}>
          {limitation}
        </p>
      ))}

      {brief ? <DatasetBrief brief={brief} /> : null}

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

          <div className="grid">
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
          </div>
        </>
      ) : (
        <p className="warning">{detail.unavailableReason}</p>
      )}
    </>
  )
}
