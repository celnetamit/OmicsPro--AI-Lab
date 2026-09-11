import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get } from '../lib/api'
import { PageHeader, SectionHead, Skeleton } from '../components/ui'
import { KIND_LABEL, TRACK_NAME, VALIDATION_LABEL, named } from '../lib/labels'

interface DatasetRow {
  id: string
  name: string
  track: string
  kind: string
  description: string
  provenance: {
    source: string
    accession: string
    citation: string
    license: string
    validationStatus: string
  }
  limitations: string[]
  selectable: boolean
  unlocked: boolean
  lockedExplanation: string
  requiredTier: string
}

function DatasetCard({ row }: { row: DatasetRow }) {
  return (
    <article className={`card${row.unlocked ? '' : ' locked'}`}>
      <span className="badge">
        {named(KIND_LABEL, row.kind)} · {named(TRACK_NAME, row.track)}
      </span>
      <h3>{row.name}</h3>
      <p>{row.description}</p>
      <div className="scroll">
        <table>
          <tbody>
            <tr>
              <th>Source</th>
              <td>{row.provenance.source || '—'}</td>
            </tr>
            <tr>
              <th>Accession</th>
              <td>{row.provenance.accession || '—'}</td>
            </tr>
            <tr>
              <th>Licence</th>
              <td>{row.provenance.license || '—'}</td>
            </tr>
            <tr>
              <th>Validation</th>
              <td>{named(VALIDATION_LABEL, row.provenance.validationStatus)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {row.limitations.map((limitation) => (
        <p className="caveat" key={limitation}>
          {limitation}
        </p>
      ))}
      <div className="dataset-state">
        {row.unlocked ? (
          row.selectable ? (
            <Link className="button secondary" to={`/datasets/${row.id}`}>
              Inspect and analyse
            </Link>
          ) : (
            <p className="hint">Opens once its files are ingested and pass validation.</p>
          )
        ) : (
          <>
            <p className="hint">{row.lockedExplanation}</p>
            <Link className="button secondary" to="/upgrade">
              Compare access options
            </Link>
          </>
        )}
      </div>
    </article>
  )
}

export function Datasets() {
  const [rows, setRows] = useState<DatasetRow[] | null>(null)

  useEffect(() => {
    void get<DatasetRow[]>('/api/datasets')
      .then(setRows)
      .catch(() => setRows([]))
  }, [])

  //: What can be opened today comes first; datasets still waiting for their
  //: files follow, with their provenance, so nothing is hidden.
  const ready = (rows ?? []).filter((row) => row.provenance.validationStatus === 'validated')
  const waiting = (rows ?? []).filter((row) => row.provenance.validationStatus !== 'validated')

  return (
    <>
      <PageHeader
        title="Dataset Selector"
        lede="Provenance is shown for every dataset, including ones your access level does not open."
      />

      {rows === null ? (
        <>
          <Skeleton lines={4} />
          <span className="visually-hidden" role="status">
            Loading datasets
          </span>
        </>
      ) : (
        <>
          <SectionHead
            title="Ready to analyse"
            sub={
              ready.length
                ? 'Ingested and validated. Open one to inspect it and start the guided analysis.'
                : 'No dataset has been ingested and validated yet.'
            }
          />
          {ready.length ? (
            <div className="grid dataset-grid">
              {ready.map((row) => (
                <DatasetCard key={row.id} row={row} />
              ))}
            </div>
          ) : null}

          {waiting.length ? (
            <>
              <SectionHead
                title="Not yet available"
                sub="Seeded with full provenance. Each opens once an operator has ingested its files and they pass validation."
              />
              <div className="grid dataset-grid">
                {waiting.map((row) => (
                  <DatasetCard key={row.id} row={row} />
                ))}
              </div>
            </>
          ) : null}
        </>
      )}
    </>
  )
}
