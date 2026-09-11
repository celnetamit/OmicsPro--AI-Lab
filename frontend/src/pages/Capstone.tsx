import { useCallback, useEffect, useState } from 'react'
import { LabelPill } from '../components/Evidence'
import { ApiError, get, post, api } from '../lib/api'
import { PageHeader, Skeleton } from '../components/ui'
import { Gated } from '../components/Locked'
import type { RunSummary } from '../lib/types'
import { TRACK_NAME, named } from '../lib/labels'

interface CapstoneState {
  id: string
  title: string
  researchQuestion: string
  approach: string
  runIds: string[]
  figures: { figureId: string; runId: string; caption?: string }[]
  findings: { claim: string; evidence: string }[]
  limitations: string[]
  futureWork: string
  submittedAt: string | null
  defenceScore?: number | null
  defenceBreakdown?: { parts: any[]; note: string; pending: string[] }
}

interface FigureOption {
  id: string
  label: string
  caption: string
  runId: string
  track: string
  kind: string
}

interface Readiness {
  ready: boolean
  gaps: string[]
  note: string
}

export function Capstone() {
  return (
    <>
      <PageHeader
        title="Capstone Workspace"
        lede="Week 8. Assemble the work you have already done into a defensible account: runs, figures, your interpretations, the robustness checks and the AI audit."
      />
      <Gated feature="capstone_workspace">
        <Workspace />
      </Gated>
    </>
  )
}

function Workspace() {
  const [state, setState] = useState<CapstoneState | null>(null)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [figureOptions, setFigureOptions] = useState<FigureOption[]>([])
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [deck, setDeck] = useState<any>(null)
  const [memo, setMemo] = useState<any>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setState(await get<CapstoneState>('/api/capstone'))
    setRuns(await get<RunSummary[]>('/api/runs'))
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!state) return
    void get<FigureOption[]>('/api/capstone/available-figures').then(setFigureOptions)
  }, [state])

  async function save(next: Partial<CapstoneState>) {
    if (!state) return
    const merged = { ...state, ...next }
    setState(merged)
    setError('')
    try {
      const saved = await api<CapstoneState>('/api/capstone', {
        method: 'PUT',
        body: JSON.stringify({
          title: merged.title,
          research_question: merged.researchQuestion,
          approach: merged.approach,
          run_ids: merged.runIds,
          figures: merged.figures,
          findings: merged.findings,
          limitations: merged.limitations,
          future_work: merged.futureWork,
        }),
      })
      setState(saved)
    } catch (e) {
      setError((e as ApiError).message)
    }
  }

  async function buildMemo() {
    setMemo(await get<any>('/api/capstone/memo'))
  }

  async function buildDeck() {
    const result = await get<any>('/api/capstone/deck')
    setDeck(result)
    setReadiness(result.readiness)
  }

  async function submit() {
    setError('')
    try {
      setState(await post<CapstoneState>('/api/capstone/submit', {}))
    } catch (e) {
      const detail = (e as ApiError).detail as Readiness | undefined
      if (detail?.gaps) setReadiness(detail)
      setError((e as ApiError).message)
    }
  }

  if (!state) {
    return (
      <>
        <Skeleton lines={4} />
        <span className="visually-hidden" role="status">
          Loading
        </span>
      </>
    )
  }

  const completed = runs.filter((run) => run.status === 'completed')
  const locked = Boolean(state.submittedAt)

  return (
    <>
      {locked ? (
        <p className="caveat">
          Submitted on {new Date(state.submittedAt!).toLocaleString()}. The capstone is no
          longer editable.
        </p>
      ) : null}

      <div className="card">
        <h3>The question</h3>
        <label htmlFor="title">Title</label>
        <input
          id="title"
          disabled={locked}
          value={state.title}
          onChange={(e) => setState({ ...state, title: e.target.value })}
          onBlur={() => save({})}
        />
        <div className="grid-2">
          <div className="field">
            <label htmlFor="question">Research question</label>
            <textarea
              id="question"
              disabled={locked}
              value={state.researchQuestion}
              onChange={(e) => setState({ ...state, researchQuestion: e.target.value })}
              onBlur={() => save({})}
            />
          </div>
          <div className="field">
            <label htmlFor="approach">Approach and why it fits the question</label>
            <textarea
              id="approach"
              disabled={locked}
              value={state.approach}
              onChange={(e) => setState({ ...state, approach: e.target.value })}
              onBlur={() => save({})}
            />
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h3>Runs this rests on</h3>
          <p className="hint">
            Only completed runs can support a claim. Each one brings its own dataset
            provenance, method versions and parameters with it.
          </p>
          {completed.map((run) => (
            <label key={run.id} style={{ fontWeight: 400, display: 'flex', gap: 8 }}>
              <input
                type="checkbox"
                style={{ width: 'auto' }}
                disabled={locked}
                checked={state.runIds.includes(run.id)}
                onChange={(event) =>
                  save({
                    runIds: event.target.checked
                      ? [...state.runIds, run.id]
                      : state.runIds.filter((id) => id !== run.id),
                  })
                }
              />
              {run.id.slice(0, 8)} · {named(TRACK_NAME, run.track)}
              {run.module ? ` · ${run.module}` : ''} ·{' '}
              {run.isOriginal ? 'original' : 'alternate settings'}
            </label>
          ))}
        </div>

        <div className="card">
          <h3>Figure pack</h3>
          {figureOptions.length === 0 ? (
            <p className="hint">
              Attach a completed run to see the figures its outputs can support.
            </p>
          ) : (
            figureOptions.map((option) => {
              const selected = state.figures.some(
                (f) => f.figureId === option.id && f.runId === option.runId,
              )
              return (
                <label
                  key={`${option.runId}:${option.id}`}
                  style={{ fontWeight: 400, display: 'flex', gap: 8, alignItems: 'flex-start' }}
                >
                  <input
                    type="checkbox"
                    style={{ width: 'auto', marginTop: 4 }}
                    disabled={locked}
                    checked={selected}
                    onChange={(event) =>
                      save({
                        figures: event.target.checked
                          ? [...state.figures, { figureId: option.id, runId: option.runId }]
                          : state.figures.filter(
                              (f) => !(f.figureId === option.id && f.runId === option.runId),
                            ),
                      })
                    }
                  />
                  <span>
                    <strong>{option.label}</strong> · {option.runId.slice(0, 8)}
                    <div className="hint">{option.caption}</div>
                  </span>
                </label>
              )
            })
          )}
        </div>
      </div>

      <div className="card">
        <h3>Limitations, in your own words</h3>
        <p className="hint">
          The deck collects the limitations the pipelines stamped on their outputs. These
          are the ones you judge to matter for your question.
        </p>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="limitations">Limitations that matter for your question</label>
            <textarea
              id="limitations"
              disabled={locked}
              value={state.limitations.join('\n')}
              onChange={(e) =>
                setState({ ...state, limitations: e.target.value.split('\n').filter(Boolean) })
              }
              onBlur={() => save({})}
            />
            <p className="hint">One per line.</p>
          </div>
          <div className="field">
            <label htmlFor="future">What you would do next</label>
            <textarea
              id="future"
              disabled={locked}
              value={state.futureWork}
              onChange={(e) => setState({ ...state, futureWork: e.target.value })}
              onBlur={() => save({})}
            />
          </div>
        </div>
      </div>

      {error ? <p className="warning">{error}</p> : null}

      <div className="row">
        <button className="secondary" onClick={buildDeck}>
          Build the defence deck
        </button>
        <button className="secondary" onClick={buildMemo}>
          Build the research memo
        </button>
        <button disabled={locked} onClick={submit}>
          Submit the capstone
        </button>
      </div>

      {state.defenceScore !== null && state.defenceScore !== undefined ? (
        <div className="card">
          <div className="spread">
            <h3>Final defence score</h3>
            <span className="tag">{Math.round(state.defenceScore * 100)}%</span>
          </div>
          <div className="scroll mt-4">
            <table>
              <thead>
                <tr>
                  <th>Measured</th>
                  <th className="num">Score</th>
                  <th>What it counted</th>
                </tr>
              </thead>
              <tbody>
                {(state.defenceBreakdown?.parts ?? []).map((part: any) => (
                  <tr key={part.key}>
                    <td>{part.label}</td>
                    <td className="num">
                      {part.score === null ? '—' : `${Math.round(part.score * 100)}%`}
                    </td>
                    <td>
                      {part.measures} ({part.counted}/{part.total})
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint">{state.defenceBreakdown?.note}</p>
        </div>
      ) : null}

      {memo ? (
        <div className="card">
          <div className="spread">
            <h3>{memo.title}</h3>
            <span className={`tag${memo.withinTwoPages ? '' : ' neutral'}`}>
              {memo.estimatedPages} page{memo.estimatedPages === 1 ? '' : 's'} · {memo.estimatedWords} words
            </span>
          </div>
          {memo.missing.length ? (
            <p className="caveat">Still to add: {memo.missing.join(', ')}.</p>
          ) : null}

          <h4 className="mt-4">Question</h4>
          <p>{memo.sections.question || '—'}</p>

          <h4>Approach</h4>
          <p className="hint">
            {memo.sections.approach.chosenAssay ?? 'No assay recorded'} ·{' '}
            {memo.sections.approach.justification}
          </p>
          {memo.sections.approach.datasets.map((d: any) => (
            <p className="small" key={d.accession}>
              {d.name} — {d.accession} ({d.license})
            </p>
          ))}

          <h4 className="mt-4">Findings</h4>
          {memo.sections.findings.length === 0 ? (
            <p className="hint">No biological interpretation recorded yet.</p>
          ) : (
            memo.sections.findings.map((f: any) => (
              <div key={f.step} className="mt-4">
                <LabelPill label={f.label} />
                <p>{f.claim}</p>
                <p className="hint">
                  {f.observation} — {f.statisticalEvidence}
                </p>
              </div>
            ))
          )}

          <h4 className="mt-4">Limitations</h4>
          <ul>
            {memo.sections.limitations.map((l: string) => (
              <li key={l}>{l}</li>
            ))}
          </ul>

          <h4>Next steps</h4>
          <p>{memo.sections.nextSteps || '—'}</p>

          <p className="hint mt-4">{memo.note}</p>
        </div>
      ) : null}

      {readiness ? (
        <div className="card">
          <h3>{readiness.ready ? 'The record is complete' : 'Still missing'}</h3>
          {readiness.gaps.map((gap) => (
            <p className="caveat" key={gap}>
              {gap}
            </p>
          ))}
          <p className="hint">{readiness.note}</p>
        </div>
      ) : null}

      {deck ? (
        <div className="card">
          <h3>Defence deck</h3>
          {deck.slides.map((slide: any) => (
            <div key={slide.slide} style={{ marginBottom: 16 }}>
              <h4>
                {slide.slide}. {slide.title}
              </h4>
              <div className="scroll">
                <pre style={{ fontSize: 12 }}>{JSON.stringify(slide.body, null, 2)}</pre>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </>
  )
}
