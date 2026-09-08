import { useEffect, useState } from 'react'
import { ApiError, get, post } from '../lib/api'
import { LockNote } from '../components/Locked'
import { useSession } from '../components/Session'
import { PageHeader } from '../components/ui'
import type { RunSummary } from '../lib/types'

interface ReportRow {
  id: string
  runId: string
  exportFormat: string
  generatedTier: string
  createdAt: string
}

export function Reports() {
  const { matrix } = useSession()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [reports, setReports] = useState<ReportRow[]>([])
  const [content, setContent] = useState<any>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    void get<RunSummary[]>('/api/runs').then(setRuns)
    void get<ReportRow[]>('/api/reports').then(setReports)
  }, [])

  async function build(runId: string, format: string) {
    setError('')
    try {
      const report = await post<any>('/api/reports', { run_id: runId, export_format: format })
      setContent(report.content)
      setReports(await get<ReportRow[]>('/api/reports'))
    } catch (e) {
      setError((e as ApiError).message)
    }
  }

  return (
    <>
      <PageHeader
        title="Report and Portfolio"
        lede="Methods, settings, results, interpretations, limitations and references, exported at your access level."
      />

      <div className="card">
        <h3>Build a report</h3>
        <p className="hint">
          Formats available to you: {matrix?.allowance.exportFormats.join(', ')}
        </p>
        <LockNote feature="report_full" />
        <div className="stack">
          {runs
            .filter((run) => run.status === 'completed')
            .map((run) => (
              <div key={run.id} className="row">
                <span>
                  <strong>{run.id.slice(0, 8)}</strong> · {run.track} ·
                </span>
                {(matrix?.allowance.exportFormats ?? []).map((format) => (
                  <button
                    key={format}
                    className="secondary"
                    onClick={() => build(run.id, format)}
                  >
                    {format}
                  </button>
                ))}
              </div>
            ))}
        </div>
        {error ? <p className="warning">{error}</p> : null}
      </div>

      <div className="card">
        <h3>Saved reports</h3>
        {reports.length === 0 ? (
          <p className="hint">No reports yet.</p>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Report</th>
                  <th>Format</th>
                  <th>Generated at tier</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {reports.map((report) => (
                  <tr key={report.id}>
                    <td>
                      <a
                        href="#"
                        onClick={async (event) => {
                          event.preventDefault()
                          const full = await get<any>(`/api/reports/${report.id}`)
                          setContent(full.content)
                        }}
                      >
                        {report.id.slice(0, 8)}
                      </a>
                    </td>
                    <td>{report.exportFormat}</td>
                    <td>{report.generatedTier}</td>
                    <td>{new Date(report.createdAt).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="hint">
          Reports stay readable if a paid tier later expires. Access changes do not delete
          work you already produced.
        </p>
      </div>

      {content ? (
        <div className="card">
          <h3>Report contents</h3>
          <h4>Methods</h4>
          <pre style={{ fontSize: 12.5 }}>{JSON.stringify(content.methods, null, 2)}</pre>
          <h4>Settings</h4>
          <div className="scroll">
            <table>
              <tbody>
                {content.settings?.map((setting: any) => (
                  <tr key={setting.key}>
                    <th>{setting.label}</th>
                    <td>{String(setting.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h4>Limitations</h4>
          <ul>
            {content.limitations?.map((limitation: string) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
          <h4>References</h4>
          <ul>
            {content.references?.map((reference: any) => (
              <li key={reference.id}>
                {reference.title} ({reference.reference})
              </li>
            ))}
          </ul>
          {content.aiAuditNote ? <p className="caveat">{content.aiAuditNote}</p> : null}
        </div>
      ) : null}
    </>
  )
}
