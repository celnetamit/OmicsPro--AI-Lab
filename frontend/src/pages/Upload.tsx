import { useState } from 'react'
import { Gated } from '../components/Locked'
import { ApiError, getToken } from '../lib/api'
import { useSession } from '../components/Session'
import { PageHeader } from '../components/ui'
import { TRACK_LABEL } from '../lib/labels'

/** What each track reads. The server checks the same list; this only guides the picker. */
const FORMATS: Record<string, { accept: string; hint: string; metadataHint: string }> = {
  foundation: {
    accept: '.csv,.tsv,.gz',
    hint: 'CSV or TSV, optionally gzipped: genes as rows, samples as columns, raw counts.',
    metadataHint:
      'Required. One row per sample, with a sample_id matching the matrix columns and a condition.',
  },
  core: {
    accept: '.h5ad,.h5,.mtx,.gz',
    hint: 'AnnData (.h5ad) with raw counts in X, .raw or a "counts" layer; a 10x HDF5 file (.h5); or a 10x Matrix Market file (.mtx) with its features and barcodes files.',
    metadataHint:
      'One row per cell, naming it as the matrix does (cell_id or barcode), with its sample_id and condition. Optional for an .h5ad that already carries them.',
  },
  advanced: {
    accept: '.h5ad,.h5,.mtx,.gz',
    hint: "AnnData (.h5ad) with coordinates in obsm['spatial'], or Space Ranger's filtered matrix (.h5, or .mtx with features and barcodes) together with the tissue positions file.",
    metadataHint:
      'One row per spot (spot_id or barcode) with its sample_id and condition. Optional for an .h5ad that already carries them.',
  },
}

export function Upload() {
  return (
    <>
      <PageHeader
        title="Upload a Dataset"
        lede="Bring an analysis-ready dataset of your own. It is validated in full before any pipeline can read it."
      />
      <Gated feature="dataset_upload">
        <UploadForm />
      </Gated>
    </>
  )
}

function UploadForm() {
  const { matrix: entitlements } = useSession()
  const [track, setTrack] = useState('core')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [errors, setErrors] = useState<{ code: string; message: string }[]>([])
  const [warnings, setWarnings] = useState<{ code: string; message: string }[]>([])
  const format = FORMATS[track]

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setErrors([])
    setWarnings([])
    setResult(null)
    try {
      const response = await fetch('/api/datasets/upload', {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
        body: new FormData(event.currentTarget),
      })
      const body = await response.json()
      if (!response.ok) {
        const detail = body?.detail ?? {}
        setErrors(detail.errors ?? [{ code: 'error', message: detail.message ?? 'Upload failed.' }])
        setWarnings(detail.warnings ?? [])
        return
      }
      setResult(body)
      setWarnings(body.validation?.warnings ?? [])
    } catch (e) {
      setErrors([{ code: 'network', message: (e as ApiError).message }])
    } finally {
      setBusy(false)
    }
  }

  const limitMb = Math.round((entitlements?.allowance.maxUploadBytes ?? 0) / (1024 * 1024))

  return (
    <>
      <form className="card" onSubmit={submit}>
        <h3>Files</h3>
        <p className="hint">
          Analysis-ready formats only, up to {limitMb} MB. Raw sequencing files are not
          accepted: they need a compute and storage arrangement this platform does not
          provide.
        </p>

        <div className="field">
          <label htmlFor="track">Analysis track</label>
          <select id="track" name="track" required value={track} onChange={(e) => setTrack(e.target.value)}>
            {Object.entries(TRACK_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="matrix">Count matrix</label>
          <input id="matrix" name="matrix" type="file" accept={format.accept} required />
          <p className="hint">{format.hint}</p>
        </div>

        {track !== 'foundation' ? (
          <div className="grid-2">
            <div className="field">
              <label htmlFor="features">Features file (.mtx only)</label>
              <input id="features" name="features" type="file" accept=".tsv,.gz" />
            </div>
            <div className="field">
              <label htmlFor="barcodes">Barcodes file (.mtx only)</label>
              <input id="barcodes" name="barcodes" type="file" accept=".tsv,.gz" />
            </div>
          </div>
        ) : null}

        {track === 'advanced' ? (
          <div className="field">
            <label htmlFor="positions">Tissue positions (tissue_positions.csv)</label>
            <input id="positions" name="positions" type="file" accept=".csv,.gz" />
            <p className="hint">
              Needed with a Space Ranger matrix: it places each spot on the section. Spots
              outside the tissue are dropped.
            </p>
          </div>
        ) : null}

        <div className="field">
          <label htmlFor="metadata">{track === 'foundation' ? 'Sample metadata' : 'Cell or spot metadata'}</label>
          <input
            id="metadata"
            name="metadata"
            type="file"
            accept=".csv,.tsv"
            required={track === 'foundation'}
          />
          <p className="hint">
            {format.metadataHint} Metadata is matched to the matrix by identifier, never by
            row order. Use coded donor identifiers — names, dates of birth, record numbers
            and contact details are rejected outright.
          </p>
        </div>

        <h3 className="mt-5">Provenance</h3>
        <p className="hint">
          Provenance is required. A dataset with no recorded source cannot be cited in a
          report, so it cannot be analysed here.
        </p>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="name">Dataset name</label>
            <input id="name" name="name" required />
          </div>
          <div className="field">
            <label htmlFor="source">Source</label>
            <input id="source" name="source" required placeholder="e.g. NCBI Gene Expression Omnibus" />
          </div>
        </div>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="accession">Accession or internal identifier</label>
            <input id="accession" name="accession" required />
          </div>
          <div className="field">
            <label htmlFor="license">Licence or terms of use</label>
            <input id="license" name="license" required />
          </div>
        </div>
        <div className="field">
          <label htmlFor="citation">Citation</label>
          <input id="citation" name="citation" />
        </div>
        <div className="field">
          <label htmlFor="description">Description</label>
          <textarea id="description" name="description" />
        </div>

        <p className="caveat">
          Only public, teaching or properly de-identified data may be uploaded.
          Identifiable patient information and identifiable clinical genomic data are
          blocked at ingestion. Your data is never used to train models and is never
          shared with other users.
        </p>

        <button disabled={busy}>{busy ? 'Validating…' : 'Validate and upload'}</button>
      </form>

      {errors.length ? (
        <div className="card">
          <h3>Upload rejected</h3>
          {errors.map((error) => (
            <p className="warning" key={error.code + error.message}>
              {error.message}
            </p>
          ))}
          <p className="hint">Nothing was stored. Fix the issues above and try again.</p>
        </div>
      ) : null}

      {warnings.length ? (
        <div className="card">
          <h3>Accepted, with warnings about the design</h3>
          {warnings.map((warning) => (
            <p className="caveat" key={warning.code + warning.message}>
              {warning.message}
            </p>
          ))}
        </div>
      ) : null}

      {result ? (
        <div className="card">
          <h3>{result.name}</h3>
          <p>Validated and stored as an internal analysis object.</p>
          {result.validation?.summary?.ingestion?.length ? (
            <ul className="hint">
              {result.validation.summary.ingestion.map((note: string) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : null}
          <div className="scroll">
            <table>
              <tbody>
                <tr>
                  <th>Retention</th>
                  <td>
                    {result.governance.retentionDays
                      ? `${result.governance.retentionDays} days`
                      : 'indefinite'}
                  </td>
                </tr>
                <tr>
                  <th>Used for model training</th>
                  <td>no</td>
                </tr>
                <tr>
                  <th>Shared with other users</th>
                  <td>no</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="hint">{result.governance.note}</p>
        </div>
      ) : null}
    </>
  )
}
