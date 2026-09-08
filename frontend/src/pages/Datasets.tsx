import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get } from '../lib/api'

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

export function Datasets() {
  const [rows, setRows] = useState<DatasetRow[]>([])

  useEffect(() => {
    void get<DatasetRow[]>('/api/datasets').then(setRows)
  }, [])

  return (
    <>
      <h2>Dataset Selector</h2>
      <p className="lede">
        Provenance is shown for every dataset, including ones your access level does not
        open.
      </p>

      <div className="grid">
        {rows.map((row) => (
          <article className={`card${row.unlocked ? '' : ' locked'}`} key={row.id}>
            <span className="badge">{row.kind}</span>
            <h3>{row.name}</h3>
            <p>{row.description}</p>
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
                  <td>{row.provenance.validationStatus}</td>
                </tr>
              </tbody>
            </table>
            {row.limitations.map((limitation) => (
              <p className="caveat" key={limitation}>
                {limitation}
              </p>
            ))}
            {row.unlocked ? (
              row.selectable ? (
                <Link className="button secondary" to={`/datasets/${row.id}`}>
                  Inspect and analyse
                </Link>
              ) : (
                <p className="hint">
                  Not yet available: the files for this dataset have not been ingested and
                  validated.
                </p>
              )
            ) : (
              <>
                <p className="hint">{row.lockedExplanation}</p>
                <Link className="button secondary" to="/upgrade">
                  Compare access options
                </Link>
              </>
            )}
          </article>
        ))}
      </div>
    </>
  )
}
