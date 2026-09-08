import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, get, messageOf, post, requestIdOf } from '../lib/api'
import { isInFlight, usePolledRun } from '../lib/usePolledRun'
import { ErrorNote, PageHeader, Skeleton, Spinner, StatusPill } from '../components/ui'
import { Caveats, EvidenceList, LabelPill } from '../components/Evidence'
import { PerturbationDialog } from '../components/PerturbationDialog'
import { useSession } from '../components/Session'
import type {
  EvidenceRef,
  InterpretationLabel,
  PerturbationOffer,
  RunSummary,
} from '../lib/types'

interface Explanation {
  title: string
  purpose: string
  text: string
  whatToObserve: string
  caveats: string[]
  evidence: EvidenceRef[]
  interactionId: string
}

interface Interpretation {
  observation: string
  statisticalEvidence: string
  biologicalInterpretation: string
  hypothesis: string
  label: InterpretationLabel
  labelRationale: string
  caveats: string[]
  evidence: EvidenceRef[]
  interactionId: string
}

interface StepInfo {
  step: string
  title: string
}

const EMPTY_FIELDS = {
  observation: '',
  statistical_evidence: '',
  biological_interpretation: '',
  hypothesis: '',
}

export function Workspace() {
  const { runId } = useParams()
  const { can } = useSession()
  const [run, setRun] = useState<RunSummary | null>(null)
  const [steps, setSteps] = useState<StepInfo[]>([])
  const [step, setStep] = useState('')
  const [explanation, setExplanation] = useState<Explanation | null>(null)
  const [interpretation, setInterpretation] = useState<Interpretation | null>(null)
  const [challenge, setChallenge] = useState<{ warnings: { message: string }[]; note: string } | null>(null)
  const [offers, setOffers] = useState<PerturbationOffer[]>([])
  const [activeOffer, setActiveOffer] = useState<PerturbationOffer | null>(null)
  const [perturbationResult, setPerturbationResult] = useState<any>(null)
  const [fields, setFields] = useState(EMPTY_FIELDS)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [errorRef, setErrorRef] = useState<string | null>(null)

  const loadRun = useCallback(async () => {
    const loaded = await get<RunSummary>(`/api/runs/${runId}`)
    setRun(loaded)
    const trackSteps = await get<StepInfo[]>(`/api/copilot/steps/${loaded.track}`)
    setSteps(trackSteps)
    setStep((current) => current || loaded.lastValidStep || trackSteps[0]?.step || '')
  }, [runId])

  useEffect(() => {
    void loadRun()
  }, [loadRun])

  //: The pipeline runs on the API's worker pool, so a run arrives queued and
  //: reaches its result later. Poll until it is terminal, then stop.
  const polling = usePolledRun(run, setRun)

  //: A perturbation runs a second pipeline, and its expected-versus-actual
  //: table only exists once that alternate run finishes. Poll the record until
  //: the reconciliation the server computes on completion appears.
  const pendingPerturbationId: string | undefined =
    perturbationResult?.perturbation?.decision !== 'skip' &&
    perturbationResult?.perturbation &&
    !perturbationResult.perturbation.actualOutcome
      ? perturbationResult.perturbation.id
      : undefined

  useEffect(() => {
    if (!run || !pendingPerturbationId) return
    let cancelled = false
    let delay = 2000

    const tick = async () => {
      try {
        const records = await get<any[]>(`/api/runs/${run.id}/perturbation-records`)
        if (cancelled) return
        const latest = records.find((record) => record.id === pendingPerturbationId)
        if (latest?.actualOutcome) {
          setPerturbationResult((current: any) => ({ ...current, perturbation: latest }))
          return
        }
      } catch {
        //: Transient; the next poll either recovers or the run reports failure.
      }
      if (cancelled) return
      delay = Math.min(delay * 1.3, 8000)
      window.setTimeout(tick, delay)
    }

    const timer = window.setTimeout(tick, delay)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [run, pendingPerturbationId])

  useEffect(() => {
    if (!run || !step || run.status !== 'completed') return
    setError('')
    setErrorRef(null)
    setExplanation(null)
    setInterpretation(null)
    setOffers([])
    setPerturbationResult(null)
    setFields(EMPTY_FIELDS)

    void get<Explanation>('/api/copilot/explain', { run_id: run.id, step })
      .then(setExplanation)
      .catch((e: ApiError) => {
        setError(messageOf(e))
        setErrorRef(requestIdOf(e))
      })
    void get<Interpretation>('/api/copilot/interpret', { run_id: run.id, step })
      .then(setInterpretation)
      .catch(() => undefined)
    void get<any>('/api/copilot/challenge', { run_id: run.id, step })
      .then(setChallenge)
      .catch(() => undefined)
    if (can('perturbation_guided')) {
      void get<{ offers: PerturbationOffer[] }>(`/api/runs/${run.id}/perturbations`, { step })
        .then((d) => setOffers(d.offers))
        .catch(() => undefined)
    }
  }, [run, step, can])

  async function decide(decision: 'test' | 'skip') {
    if (!activeOffer || !run) return
    setBusy(true)
    try {
      const result = await post<any>(`/api/runs/${run.id}/perturbations`, {
        offer_key: activeOffer.key,
        decision,
      })
      setPerturbationResult(result)
      setActiveOffer(null)
      await loadRun()
    } catch (e) {
      setError(messageOf(e))
      setErrorRef(requestIdOf(e))
    } finally {
      setBusy(false)
    }
  }

  async function saveInterpretation() {
    if (!run) return
    await post(`/api/runs/${run.id}/interpretation`, { step, ...fields })
  }

  async function audit(action: string) {
    if (!interpretation) return
    await post('/api/copilot/audit', {
      interaction_id: interpretation.interactionId,
      action,
      final_interpretation: fields.biological_interpretation,
    })
  }

  if (!run) {
    return (
      <>
        <PageHeader title="Analysis Workspace" />
        <Skeleton lines={4} />
        <span className="visually-hidden" role="status">Loading the run</span>
      </>
    )
  }

  const outputs = run.outputs ?? {}
  const working = isInFlight(run.status)

  return (
    <>
      <PageHeader
        title="Analysis Workspace"
        lede={
          <>
            {run.track}
            {run.module ? ` · ${run.module}` : ''} · {run.pipelineVersion}
            {run.isOriginal ? '' : ' · alternate settings'}
          </>
        }
        actions={<StatusPill status={run.status} />}
      />

      {working ? (
        <div className="note" role="status" aria-live="polite">
          <div className="note-body">
            <strong>This analysis is still running</strong>
            Each step is computed on the server and the results appear here as soon as
            it finishes. You can leave this page and come back — the run continues
            without the browser.
            {run.lastValidStep ? (
              <div className="small mt-4">Completed so far: {run.lastValidStep}</div>
            ) : null}
          </div>
          {polling ? <Spinner /> : null}
        </div>
      ) : null}

      <ScopeNotices outputs={run.outputs} />

      {run.status === 'failed' ? (
        <div className="card">
          <p className="warning">{run.errorMessage}</p>
          <p className="hint">
            The analysis stopped at this point. Results from the steps that completed are
            preserved below, and the last valid step was{' '}
            <strong>{run.lastValidStep ?? 'none'}</strong>.
          </p>
        </div>
      ) : null}

      <div className="steps">
        {steps.map((info) => (
          <button
            key={info.step}
            className={
              info.step === step
                ? 'active'
                : outputs[info.step] || run.lastValidStep === info.step
                  ? 'done'
                  : ''
            }
            onClick={() => setStep(info.step)}
          >
            {info.title}
          </button>
        ))}
      </div>

      {error ? <ErrorNote message={error} requestId={errorRef} /> : null}

      {explanation ? (
        <div className="card">
          <span className="badge">Copilot explanation</span>
          <h3>{explanation.title}</h3>
          <p>{explanation.purpose}</p>
          <p>
            <strong>{explanation.text}</strong>
          </p>
          <p>
            <strong>What to observe:</strong> {explanation.whatToObserve}
          </p>
          <Caveats items={explanation.caveats} />
          <EvidenceList sources={explanation.evidence} />
          <p className="hint">
            Every value above was computed by the pipeline for this run. The Copilot does
            not calculate results.
          </p>
        </div>
      ) : null}

      <div className="card">
        <h3>Computed output</h3>
        <div className="scroll">
          <pre style={{ fontSize: 12.5 }}>
            {JSON.stringify(pickStepOutputs(outputs, step), null, 2)}
          </pre>
        </div>
      </div>

      {challenge?.warnings?.length ? (
        <div className="card">
          <span className="badge">Copilot challenge</span>
          {challenge.warnings.map((warning) => (
            <p className="warning" key={warning.message}>
              {warning.message}
            </p>
          ))}
        </div>
      ) : null}

      {can('perturbation_extended') ? (
        <CustomPerturbation
          runId={run.id}
          parameters={run.parameters}
          onDone={(result) => {
            setPerturbationResult(result)
            void loadRun()
          }}
        />
      ) : null}

      {offers.length ? (
        <div className="card">
          <span className="badge">What-if</span>
          <h3>Test an analysis decision</h3>
          <div className="stack">
            {offers.map((offer) => (
              <div key={offer.key}>
                <p>
                  <strong>{offer.label}</strong>
                </p>
                <button className="secondary" onClick={() => setActiveOffer(offer)}>
                  Review this change
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {activeOffer ? (
        <PerturbationDialog offer={activeOffer} busy={busy} onDecide={decide} />
      ) : null}

      {perturbationResult?.perturbation ? (
        <div className="card">
          <h3>Expected versus actual</h3>
          {perturbationResult.perturbation.decision === 'skip' ? (
            <p>
              You skipped this change. The decision is recorded in your reproducibility
              log.
            </p>
          ) : !perturbationResult.perturbation.actualOutcome ? (
            <div className="note" role="status" aria-live="polite">
              <div className="note-body">
                <strong>Running the alternate settings</strong>
                The comparison appears here once the second run finishes. Your original
                run is untouched.
              </div>
              <Spinner />
            </div>
          ) : (
            <>
              <div className="scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Metric</th>
                      <th>Expected</th>
                      <th>Observed</th>
                      <th>Before</th>
                      <th>After</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perturbationResult.perturbation.actualOutcome?.comparisons?.map((row: any) => (
                      <tr key={row.metric}>
                        <td>{row.metricLabel}</td>
                        <td>{row.expected}</td>
                        <td>{row.observed}</td>
                        <td>{String(row.before)}</td>
                        <td>{String(row.after)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="hint">
                {perturbationResult.perturbation.divergenceExplanation}
              </p>
              <p className="hint">
                Your original run is unchanged.{' '}
                <Link to={`/compare?original=${run.id}&alternate=${perturbationResult.alternateRun?.id}`}>
                  Compare the two runs
                </Link>
              </p>
            </>
          )}
        </div>
      ) : null}

      {interpretation ? (
        <div className="card">
          <span className="badge">Interpretation</span>
          <LabelPill label={interpretation.label} rationale={interpretation.labelRationale} />
          <div className="fields mt-4">
            <div>
              <label htmlFor="obs">Observation</label>
              <p className="hint">Copilot: {interpretation.observation}</p>
              <textarea
                id="obs"
                value={fields.observation}
                onChange={(e) => setFields({ ...fields, observation: e.target.value })}
              />
            </div>
            <div>
              <label htmlFor="stat">Statistical evidence</label>
              <p className="hint">Copilot: {interpretation.statisticalEvidence}</p>
              <textarea
                id="stat"
                value={fields.statistical_evidence}
                onChange={(e) => setFields({ ...fields, statistical_evidence: e.target.value })}
              />
            </div>
            <div>
              <label htmlFor="bio">Biological interpretation</label>
              <p className="hint">Copilot: {interpretation.biologicalInterpretation}</p>
              <textarea
                id="bio"
                value={fields.biological_interpretation}
                onChange={(e) =>
                  setFields({ ...fields, biological_interpretation: e.target.value })
                }
              />
            </div>
            <div>
              <label htmlFor="hyp">Hypothesis to test next</label>
              <p className="hint">Copilot: {interpretation.hypothesis}</p>
              <textarea
                id="hyp"
                value={fields.hypothesis}
                onChange={(e) => setFields({ ...fields, hypothesis: e.target.value })}
              />
            </div>
          </div>
          <Caveats items={interpretation.caveats} />
          <EvidenceList sources={interpretation.evidence} />

          <div className="row mt-4">
            <button onClick={saveInterpretation}>Save my interpretation</button>
            <button className="secondary" onClick={() => audit('accept')}>
              Accept the Copilot output
            </button>
            <button className="secondary" onClick={() => audit('modify')}>
              Modify
            </button>
            <button className="secondary" onClick={() => audit('reject')}>
              Reject
            </button>
            <button className="secondary" onClick={() => audit('needs_validation')}>
              Needs validation
            </button>
          </div>
          <p className="hint">
            Your decision is stored alongside the original Copilot output and its evidence.
            The Copilot's record is never rewritten.
          </p>
        </div>
      ) : null}
    </>
  )
}

/**
 * Scope and estimate-kind notices the pipeline stamped on its own outputs.
 * They are read from the run rather than decided by the interface, so a result
 * cannot be displayed without the limitation that travels with it.
 */
function ScopeNotices({ outputs }: { outputs: Record<string, any> }) {
  const notices: string[] = []
  if (outputs?.validate?.inference_scope === 'descriptive_single_specimen') {
    notices.push(
      'This package holds a single specimen. Every region comparison below is ' +
        'descriptive and hypothesis-generating; it does not support a claim about ' +
        'a population.',
    )
  }
  if (outputs?.mapping?.estimate_kind === 'compositional') {
    notices.push(
      'Cell type estimates per spot are probabilistic and compositional. They ' +
        'describe the mixture captured under a spot and are never the identity of ' +
        'a single cell.',
    )
  }
  if (outputs?.interactions?.evidenceKind === 'inferred_candidate_communication') {
    notices.push(
      'Interactions below are inferred candidates based on co-expression. They ' +
        'are not demonstrated physical signalling.',
    )
  }
  if (outputs?.de?.replicate_unit === 'sample') {
    notices.push(
      'Condition testing aggregated to the sample level, so the replication unit ' +
        'is the donor rather than the cell.',
    )
  }
  if (!notices.length) return null
  return (
    <>
      {notices.map((notice) => (
        <p className="caveat" key={notice}>
          {notice}
        </p>
      ))}
    </>
  )
}

/**
 * A learner-authored what-if (Expert). The platform validates the change and
 * preserves the original run, but offers no expectation of its own: the learner
 * states what they expect before running it.
 */
function CustomPerturbation({
  runId,
  parameters,
  onDone,
}: {
  runId: string
  parameters: Record<string, unknown>
  onDone: (result: any) => void
}) {
  const [parameterKey, setParameterKey] = useState('')
  const [value, setValue] = useState('')
  const [rationale, setRationale] = useState('')
  const [direction, setDirection] = useState('uncertain')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [errorRef, setErrorRef] = useState<string | null>(null)

  async function submit() {
    setBusy(true)
    setError('')
    try {
      const parsed = Number(value)
      const result = await post<any>(`/api/runs/${runId}/perturbations/custom`, {
        parameter_key: parameterKey,
        value: Number.isNaN(parsed) ? value : parsed,
        rationale,
        expected_direction: direction,
      })
      onDone(result)
    } catch (e) {
      setError(messageOf(e))
      setErrorRef(requestIdOf(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <span className="badge">Your own what-if</span>
      <h3>Author a change</h3>
      <label htmlFor="param">Setting</label>
      <select id="param" value={parameterKey} onChange={(e) => setParameterKey(e.target.value)}>
        <option value="">Select…</option>
        {Object.keys(parameters)
          .sort()
          .map((key) => (
            <option key={key} value={key}>
              {key} (currently {String(parameters[key])})
            </option>
          ))}
      </select>
      <label htmlFor="value">New value</label>
      <input id="value" value={value} onChange={(e) => setValue(e.target.value)} />
      <label htmlFor="direction">What do you expect to happen?</label>
      <select id="direction" value={direction} onChange={(e) => setDirection(e.target.value)}>
        <option value="increase">A key result will increase</option>
        <option value="decrease">A key result will decrease</option>
        <option value="unchanged">Nothing meaningful will change</option>
        <option value="uncertain">I am not sure — that is why I am testing it</option>
      </select>
      <label htmlFor="rationale">Why are you testing this?</label>
      <textarea id="rationale" value={rationale} onChange={(e) => setRationale(e.target.value)} />
      <p className="hint">
        Write your expectation before you run it. The platform will not invent one
        for a change it did not propose, and your original run is kept unchanged.
      </p>
      {error ? <ErrorNote message={error} requestId={errorRef} /> : null}
      <button disabled={!parameterKey || !value || busy} onClick={submit}>
        {busy ? 'Running…' : 'Run this alternate analysis'}
      </button>
    </div>
  )
}

/** Show the outputs published by the selected step, not the whole run. */
function pickStepOutputs(outputs: Record<string, unknown>, step: string) {
  const namespaces: Record<string, string> = {
    validate: 'validate',
    cell_qc: 'qc',
    qc: 'qc',
    filter: 'filter',
    exploratory: 'exploratory',
    feature_selection: 'hvg',
    dimensionality_reduction: 'pca',
    clustering: 'cluster',
    marker_genes: 'markers',
    composition: 'composition',
    differential_expression: 'de',
    pathway_analysis: 'pathway',
    // Advanced (spatial)
    spatial_qc: 'qc',
    neighborhood_graph: 'graph',
    spatially_variable_genes: 'svg',
    spatial_domains: 'domains',
    reference_mapping: 'mapping',
    neighborhood_analysis: 'neighborhood',
    region_comparison: 'region',
    // Cell-cell communication
    communication: 'expression',
    candidate_pairs: 'interactions',
    condition_comparison: 'comm_condition',
    candidate_mechanism: 'mechanism',
  }
  const key = namespaces[step] ?? step
  return outputs[key] ?? {}
}
