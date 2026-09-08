import { useEffect, useState } from 'react'
import { get, post, ApiError } from '../lib/api'

interface Brief {
  id: string
  title: string
  context: string
  decisionGoal: string
  suggestedTracks: string[]
  designNotes: string
}

interface Tradeoffs {
  measures: string
  strengths: string[]
  limitations: string[]
}

interface SampleRow {
  sample_id: string
  donor: string
  condition: string
  batch: string
  replicate: string
  tissue: string
}

const EMPTY_ROW: SampleRow = {
  sample_id: '',
  donor: '',
  condition: '',
  batch: '',
  replicate: '',
  tissue: '',
}

const TRACK_LABEL: Record<string, string> = {
  foundation: 'Foundation — Bulk RNA-seq',
  core: 'Core — Single-cell RNA-seq',
  advanced: 'Advanced — Spatial Transcriptomics',
}

export function DesignStudio() {
  const [briefs, setBriefs] = useState<Brief[]>([])
  const [assays, setAssays] = useState<Record<string, Tradeoffs>>({})
  const [briefId, setBriefId] = useState('')
  const [question, setQuestion] = useState('')
  const [decisionGoal, setDecisionGoal] = useState('')
  const [assay, setAssay] = useState('')
  const [justification, setJustification] = useState('')
  const [rows, setRows] = useState<SampleRow[]>([{ ...EMPTY_ROW }])
  const [validation, setValidation] = useState<any>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    void get<{ briefs: Brief[]; assays: Record<string, Tradeoffs> }>('/api/design/briefs').then((d) => {
      setBriefs(d.briefs)
      setAssays(d.assays)
      setBriefId(d.briefs[0]?.id ?? '')
    })
  }, [])

  const brief = briefs.find((b) => b.id === briefId)
  const tradeoffs = assay ? assays[assay] : undefined

  function payload() {
    return {
      brief_id: briefId,
      biological_question: question,
      decision_goal: decisionGoal,
      chosen_assay: assay,
      assay_justification: justification,
      samples: rows.filter((row) => row.sample_id),
    }
  }

  async function check() {
    setSaved(false)
    setValidation(await post('/api/design/check', payload()))
  }

  async function save() {
    try {
      const result = await post<any>('/api/design/plan', payload())
      setValidation({ ok: true, errors: [], warnings: result.designWarnings, summary: {} })
      setSaved(true)
    } catch (error) {
      if (error instanceof ApiError) setValidation(error.detail)
      setSaved(false)
    }
  }

  return (
    <>
      <h2>Experimental Design Studio</h2>
      <p className="lede">
        Week 1. Turn a research brief into a design and a metadata plan before any data is
        touched.
      </p>

      <div className="card">
        <h3>Research brief</h3>
        <select value={briefId} onChange={(e) => setBriefId(e.target.value)}>
          {briefs.map((b) => (
            <option key={b.id} value={b.id}>
              {b.title}
            </option>
          ))}
        </select>
        {brief ? (
          <>
            <p style={{ marginTop: 12 }}>{brief.context}</p>
            <p className="hint">
              <strong>Decision goal:</strong> {brief.decisionGoal}
            </p>
          </>
        ) : null}

        <label htmlFor="question">Biological question</label>
        <textarea id="question" value={question} onChange={(e) => setQuestion(e.target.value)} />

        <label htmlFor="goal">What decision will this analysis support?</label>
        <textarea id="goal" value={decisionGoal} onChange={(e) => setDecisionGoal(e.target.value)} />
      </div>

      <div className="card">
        <h3>Choose an assay</h3>
        <select value={assay} onChange={(e) => setAssay(e.target.value)}>
          <option value="">Select…</option>
          {Object.keys(assays).map((key) => (
            <option key={key} value={key}>
              {TRACK_LABEL[key] ?? key}
            </option>
          ))}
        </select>
        {tradeoffs ? (
          <>
            <p style={{ marginTop: 12 }}>
              <strong>What it measures:</strong> {tradeoffs.measures}
            </p>
            <p>
              <strong>Strengths</strong>
            </p>
            <ul>
              {tradeoffs.strengths.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            {tradeoffs.limitations.map((item) => (
              <p className="caveat" key={item}>
                {item}
              </p>
            ))}
          </>
        ) : null}
        <label htmlFor="justify">Why this assay for this question?</label>
        <textarea id="justify" value={justification} onChange={(e) => setJustification(e.target.value)} />
      </div>

      <div className="card">
        <h3>Metadata builder</h3>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Sample ID</th>
                <th>Donor</th>
                <th>Condition</th>
                <th>Batch</th>
                <th>Replicate</th>
                <th>Tissue</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  {(Object.keys(EMPTY_ROW) as (keyof SampleRow)[]).map((field) => (
                    <td key={field}>
                      <input
                        value={row[field]}
                        onChange={(event) => {
                          const next = [...rows]
                          next[index] = { ...row, [field]: event.target.value }
                          setRows(next)
                        }}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          className="secondary"
          style={{ marginTop: 12 }}
          onClick={() => setRows([...rows, { ...EMPTY_ROW }])}
        >
          Add a sample
        </button>
        <p className="hint">
          Use coded donor identifiers. Names, dates of birth and record numbers are
          rejected at ingestion.
        </p>
      </div>

      {validation ? (
        <div className="card">
          <h3>Design check</h3>
          {validation.errors?.map((error: any) => (
            <p className="warning" key={error.code}>
              {error.message}
            </p>
          ))}
          {validation.warnings?.map((warning: any) => (
            <p className="caveat" key={warning.code}>
              {warning.message}
            </p>
          ))}
          {!validation.errors?.length && !validation.warnings?.length ? (
            <p>No replication or confounding problems detected in this design.</p>
          ) : null}
          {saved ? <p className="hint">Plan saved to your portfolio.</p> : null}
        </div>
      ) : null}

      <div style={{ display: 'flex', gap: 10 }}>
        <button className="secondary" onClick={check}>
          Check the design
        </button>
        <button onClick={save}>Save the plan</button>
      </div>
    </>
  )
}
