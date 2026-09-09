import { useEffect, useState } from 'react'
import { get, messageOf, post } from '../lib/api'
import { LabelPill } from '../components/Evidence'
import { ErrorNote, PageHeader, SectionHead } from '../components/ui'
import { useSession } from '../components/Session'
import type { InterpretationLabel, RunSummary } from '../lib/types'

interface ConceptQuestion {
  id: string
  prompt: string
  options: string[]
}

interface AssessmentComponent {
  key: string
  label: string
  measures: string
  assessable: boolean
  score: number | null
  counted: number
  total: number
  notes: string[]
}

interface WeekAssessment {
  assessmentId: string
  week: number
  questions: ConceptQuestion[]
  components: AssessmentComponent[]
  note: string
  previousScore: number | null
}

interface WeekResult {
  score: number | null
  components: AssessmentComponent[]
  assessedComponents: string[]
  pendingComponents: string[]
  feedback: {
    id: string
    correct: boolean
    answer: string
    explanation: string
    reviewTopic: string
  }[]
  recommendedTopics: string[]
  note: string
}

const pct = (score: number | null) => (score === null ? '—' : `${Math.round(score * 100)}%`)

/**
 * The week assessment: concepts are asked, the other two components are read
 * from what the learner recorded rather than self-reported.
 */
function WeekAssessmentPanel() {
  const { me } = useSession()
  const week = me?.currentWeek ?? 1
  const [state, setState] = useState<WeekAssessment | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [result, setResult] = useState<WeekResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    void get<WeekAssessment>('/api/program/assessment', { week })
      .then(setState)
      .catch((e) => setError(messageOf(e)))
  }, [week])

  async function submit() {
    setBusy(true)
    setError('')
    try {
      setResult(await post<WeekResult>('/api/program/assessment', { week, responses: answers }))
    } catch (e) {
      setError(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  if (error) return <ErrorNote message={error} />
  if (!state) return null

  const answered = state.questions.filter((q) => answers[q.id]).length
  const shown = result ? result.components : state.components

  return (
    <>
      <SectionHead
        title={`Week ${state.week} assessment`}
        sub="Three components. The concept questions are asked; your analytical decisions and interpretation quality are measured from the work you recorded, not self-reported."
      />

      <div className="grid">
        {shown.map((component) => (
          <div className="card" key={component.key}>
            <div className="spread">
              <h3>{component.label}</h3>
              <span className={`tag${component.assessable ? '' : ' neutral'}`}>
                {component.assessable ? pct(component.score) : 'Not yet'}
              </span>
            </div>
            <p className="hint">{component.measures}</p>
            {component.assessable ? (
              <p className="small mono">
                {component.counted} of {component.total}
              </p>
            ) : null}
            {component.notes.map((note) => (
              <p className="hint" key={note}>
                {note}
              </p>
            ))}
          </div>
        ))}
      </div>

      {result ? (
        <div className="card mt-5">
          <div className="spread">
            <h3>Week {state.week} result</h3>
            <span className="tag">{pct(result.score)}</span>
          </div>
          <p className="hint">{result.note}</p>
          {result.recommendedTopics.length ? (
            <>
              <h4 className="mt-4">Review these</h4>
              <ul>
                {[...new Set(result.recommendedTopics)].map((topic) => (
                  <li key={topic}>{topic}</li>
                ))}
              </ul>
            </>
          ) : null}
          <div className="scroll mt-4">
            <table>
              <thead>
                <tr>
                  <th>Question</th>
                  <th>Result</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {result.feedback.map((row) => {
                  const question = state.questions.find((q) => q.id === row.id)
                  return (
                    <tr key={row.id}>
                      <td>{question?.prompt ?? row.id}</td>
                      <td>
                        <span className={`tag${row.correct ? '' : ' neutral'}`}>
                          {row.correct ? 'Correct' : row.answer}
                        </span>
                      </td>
                      <td>{row.explanation}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="card mt-5">
          <h3>Concept questions</h3>
          <p className="hint">
            {state.previousScore !== null
              ? `You last scored ${pct(state.previousScore)} on this week.`
              : 'Not taken yet for this week.'}
          </p>
          <div className="stack mt-4">
            {state.questions.map((question) => (
              <fieldset key={question.id}>
                <legend>{question.prompt}</legend>
                {question.options.map((option) => (
                  <label className="row" key={option} style={{ fontWeight: 400 }}>
                    <input
                      type="radio"
                      name={question.id}
                      checked={answers[question.id] === option}
                      onChange={() => setAnswers({ ...answers, [question.id]: option })}
                    />
                    {option}
                  </label>
                ))}
              </fieldset>
            ))}
          </div>
          <button
            className="mt-4"
            disabled={busy || answered < state.questions.length}
            onClick={submit}
          >
            {busy ? 'Scoring…' : `Submit ${answered}/${state.questions.length} answers`}
          </button>
        </div>
      )}
    </>
  )
}

interface InteractionRow {
  id: string
  function: string
  step: string
  label: InterpretationLabel | null
  labelRationale: string
  audit: { action: string; learnerRationale: string } | null
}

/**
 * Assessment (spec 9.11): concept answers, the analytical decisions actually
 * taken, and the quality of the interpretation recorded against them.
 */
export function Assessment() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [runId, setRunId] = useState('')
  const [interactions, setInteractions] = useState<InteractionRow[]>([])
  const [interpretations, setInterpretations] = useState<any[]>([])

  useEffect(() => {
    void get<RunSummary[]>('/api/runs').then((rows) => {
      setRuns(rows)
      setRunId(rows[0]?.id ?? '')
    })
  }, [])

  useEffect(() => {
    if (!runId) return
    void get<InteractionRow[]>('/api/copilot/interactions', { run_id: runId }).then(setInteractions)
    void get<any[]>(`/api/runs/${runId}/interpretation`).then(setInterpretations)
  }, [runId])

  const reviewed = interactions.filter((row) => row.audit).length

  return (
    <>
      <PageHeader
        title="Assessment"
        lede="Concept understanding, the analytical decisions you took, and the quality of the interpretation you recorded against them."
      />

      <WeekAssessmentPanel />

      <SectionHead
        title="The record behind it"
        sub="The decisions and interpretations the measured components read."
      />

      <div className="card measure">
        <label htmlFor="run">Run</label>
        <select id="run" value={runId} onChange={(e) => setRunId(e.target.value)}>
          {runs.map((run) => (
            <option key={run.id} value={run.id}>
              {run.id.slice(0, 8)} · {run.track} · {run.status}
            </option>
          ))}
        </select>
      </div>

      <div className="card">
        <h3>AI Research Audit</h3>
        <p className="hint">
          {reviewed} of {interactions.length} Copilot outputs adjudicated.
        </p>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Step</th>
                <th>Copilot function</th>
                <th>Label</th>
                <th>Your decision</th>
              </tr>
            </thead>
            <tbody>
              {interactions.map((row) => (
                <tr key={row.id}>
                  <td>{row.step}</td>
                  <td>{row.function}</td>
                  <td>{row.label ? <LabelPill label={row.label} /> : '—'}</td>
                  <td>{row.audit?.action ?? 'Not reviewed'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Interpretation quality</h3>
        {interpretations.length === 0 ? (
          <p className="hint">No interpretations recorded for this run yet.</p>
        ) : (
          <div className="stack">
            {interpretations.map((entry) => (
              <div key={entry.id}>
                <h4>{entry.step}</h4>
                <p>
                  <strong>Observation:</strong> {entry.observation || '—'}
                </p>
                <p>
                  <strong>Statistical evidence:</strong> {entry.statisticalEvidence || '—'}
                </p>
                <p>
                  <strong>Biological interpretation:</strong> {entry.biologicalInterpretation || '—'}
                </p>
                <p>
                  <strong>Hypothesis:</strong> {entry.hypothesis || '—'}
                </p>
                {!entry.observation || !entry.statisticalEvidence ? (
                  <p className="caveat">
                    An interpretation is only assessable when the observation and the
                    statistical evidence are stated separately from the biological reading.
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
