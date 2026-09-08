import { useState } from 'react'
import { Gated } from '../components/Locked'
import { ApiError, getToken } from '../lib/api'
import { useSession } from '../components/Session'
import { PageHeader } from '../components/ui'

const TRACK_LABEL: Record<string, string> = {
  foundation: 'Foundation — Bulk RNA-seq',
  core: 'Core — Single-cell RNA-seq',
  advanced: 'Advanced — Spatial Transcriptomics',
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
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [errors, setErrors] = useState<{ code: string; message: string }[]>([])
  const [warnings, setWarnings] = useState<{ code: string; message: string }[]>([])

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
          <select id="track" name="track" required defaultValue="core">
            {Object.entries(TRACK_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="matrix">Expression matrix (genes as rows)</label>
          <input id="matrix" name="matrix" type="file" accept=".csv,.tsv" required />
        </div>

        <div className="field">
          <label htmlFor="metadata">Sample or cell metadata</label>
          <input id="metadata" name="metadata" type="file" accept=".csv" required />
          <p className="hint">
            Every row needs a sample identifier and a condition. Use coded donor
            identifiers — names, dates of birth, record numbers and contact details are
            rejected outright.
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
