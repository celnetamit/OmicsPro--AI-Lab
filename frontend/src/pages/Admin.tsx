import { useEffect, useState } from 'react'
import { ApiError, api, get, messageOf, post } from '../lib/api'
import { PageHeader, Skeleton } from '../components/ui'
import { KIND_LABEL, TIER_LABEL, TRACK_NAME, named, plural } from '../lib/labels'

const TIERS = ['basic', 'moderate', 'expert'] as const
const PAID = ['moderate', 'expert'] as const
const ISSUE_STATES = ['open', 'acknowledged', 'resolved'] as const

function when(iso?: string | null): string {
  return iso
    ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
    : '—'
}

function listed(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—'
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}

/** Digits after the decimal point for a currency, from the platform's own tables. */
function fractionDigits(currency: string): number {
  try {
    return new Intl.NumberFormat('en', { style: 'currency', currency }).resolvedOptions()
      .maximumFractionDigits ?? 2
  } catch {
    return 2
  }
}

function money(minor: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(
      minor / 10 ** fractionDigits(currency),
    )
  } catch {
    return `${minor} ${currency}`
  }
}

function allowanceText(allowance: any): string {
  const runs = allowance.runs_per_module_per_week
  return `${runs == null ? 'no weekly limit' : plural(runs, 'run')} · ${plural(allowance.perturbations_per_run, 'what-if')}`
}

function CountTable({ title, counts }: { title: string; counts?: Record<string, number> }) {
  const rows = Object.entries(counts ?? {})
  return (
    <div>
      <h4>{title}</h4>
      {rows.length ? (
        <table>
          <tbody>
            {rows.map(([key, value]) => (
              <tr key={key}>
                <th>{key.replace(/_/g, ' ')}</th>
                <td className="num">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="hint">None yet.</p>
      )}
    </div>
  )
}

/* ------------------------------------------------------ commercial terms -- */
type PriceDraft = { price: string; currency: string; termDays: string }
type AllowanceDraft = { runs: string; whatIfs: string }

function CommercialTerms() {
  const [terms, setTerms] = useState<any>(null)
  const [prices, setPrices] = useState<Record<string, PriceDraft>>({})
  const [allowance, setAllowance] = useState<Record<string, AllowanceDraft>>({})
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  function adopt(next: any) {
    setTerms(next)
    const p: Record<string, PriceDraft> = {}
    for (const tier of PAID) {
      const t = next.catalogue?.[tier]
      if (!t) continue
      p[tier] = {
        price: String(t.amount_minor_units / 10 ** fractionDigits(t.currency)),
        currency: t.currency,
        termDays: String(t.term_days),
      }
    }
    setPrices(p)
    const a: Record<string, AllowanceDraft> = {}
    for (const tier of TIERS) {
      const t = next.allowance?.[tier]
      a[tier] = {
        runs: t?.runs_per_module_per_week == null ? '' : String(t.runs_per_module_per_week),
        whatIfs: String(t?.perturbations_per_run ?? ''),
      }
    }
    setAllowance(a)
  }

  useEffect(() => {
    void get<any>('/api/admin/commercial').then(adopt).catch((e) => setError(messageOf(e)))
  }, [])

  async function savePrices() {
    setError('')
    setNotice('')
    const value: Record<string, unknown> = {}
    for (const tier of PAID) {
      const draft = prices[tier]
      if (!draft) continue
      const currency = draft.currency.trim().toUpperCase()
      const amount = Number(draft.price)
      const days = Number(draft.termDays)
      if (!Number.isFinite(amount) || amount <= 0) {
        setError(`Enter a price above zero for ${TIER_LABEL[tier]}.`)
        return
      }
      if (!Number.isInteger(days)) {
        setError(`Enter the ${TIER_LABEL[tier]} term as a whole number of days.`)
        return
      }
      value[tier] = {
        amount_minor_units: Math.round(amount * 10 ** fractionDigits(currency)),
        currency,
        term_days: days,
      }
    }
    try {
      adopt(await api<any>('/api/admin/commercial/catalogue', { method: 'PUT', body: JSON.stringify({ value }) }))
      setNotice('Prices and terms saved. They apply to new orders only.')
    } catch (e) {
      setError(messageOf(e))
    }
  }

  async function saveAllowance() {
    setError('')
    setNotice('')
    const value: Record<string, unknown> = {}
    for (const tier of TIERS) {
      const draft = allowance[tier]
      value[tier] = {
        runs_per_module_per_week: draft.runs.trim() === '' ? null : Number(draft.runs),
        perturbations_per_run: Number(draft.whatIfs),
      }
    }
    try {
      adopt(await api<any>('/api/admin/commercial/allowance', { method: 'PUT', body: JSON.stringify({ value }) }))
      setNotice('Run allowance saved. It applies from the next run a learner starts.')
    } catch (e) {
      setError(messageOf(e))
    }
  }

  if (!terms) return error ? <p className="warning">{error}</p> : <p className="hint">Loading commercial terms…</p>

  return (
    <>
      <p className="hint">{terms.note}</p>
      <h4>Price and term</h4>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th>Tier</th>
              <th>Price</th>
              <th>Currency</th>
              <th>Term (days)</th>
              <th>Default</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Basic</td>
              <td colSpan={4} className="muted">Included with the programme. Never sold.</td>
            </tr>
            {PAID.map((tier) => {
              const draft = prices[tier]
              const fallback = terms.defaults?.catalogue?.[tier]
              if (!draft) return null
              return (
                <tr key={tier}>
                  <td>{TIER_LABEL[tier]}</td>
                  <td>
                    <input
                      aria-label={`${TIER_LABEL[tier]} price`}
                      inputMode="decimal"
                      value={draft.price}
                      onChange={(e) => setPrices({ ...prices, [tier]: { ...draft, price: e.target.value } })}
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`${TIER_LABEL[tier]} currency`}
                      maxLength={3}
                      value={draft.currency}
                      onChange={(e) => setPrices({ ...prices, [tier]: { ...draft, currency: e.target.value } })}
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`${TIER_LABEL[tier]} term in days`}
                      inputMode="numeric"
                      value={draft.termDays}
                      onChange={(e) => setPrices({ ...prices, [tier]: { ...draft, termDays: e.target.value } })}
                    />
                  </td>
                  <td className="muted">
                    {fallback ? `${money(fallback.amount_minor_units, fallback.currency)} · ${fallback.term_days} days` : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="admin-save">
        <button type="button" onClick={savePrices}>Save prices and terms</button>
      </div>

      <h4>Run allowance</h4>
      <p className="hint">
        Runs per module per week (leave blank for no weekly limit) and what-if tests per run.
        Basic always keeps at least one of each, and a higher tier never gets less than a lower one.
      </p>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th>Tier</th>
              <th>Runs per module per week</th>
              <th>What-if tests per run</th>
              <th>Default</th>
            </tr>
          </thead>
          <tbody>
            {TIERS.map((tier) => {
              const draft = allowance[tier]
              const fallback = terms.defaults?.allowance?.[tier]
              if (!draft) return null
              return (
                <tr key={tier}>
                  <td>{TIER_LABEL[tier]}</td>
                  <td>
                    <input
                      aria-label={`${TIER_LABEL[tier]} runs per module per week`}
                      inputMode="numeric"
                      placeholder="No limit"
                      value={draft.runs}
                      onChange={(e) => setAllowance({ ...allowance, [tier]: { ...draft, runs: e.target.value } })}
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`${TIER_LABEL[tier]} what-if tests per run`}
                      inputMode="numeric"
                      value={draft.whatIfs}
                      onChange={(e) => setAllowance({ ...allowance, [tier]: { ...draft, whatIfs: e.target.value } })}
                    />
                  </td>
                  <td className="muted">
                    {fallback ? allowanceText(fallback) : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="admin-save">
        <button type="button" onClick={saveAllowance}>Save run allowance</button>
      </div>
      {error ? <p className="warning" role="alert">{error}</p> : null}
      {notice ? <p className="success" role="status">{notice}</p> : null}
    </>
  )
}

/* ------------------------------------------------------ cohorts and weeks -- */
function Cohorts({ onChanged }: { onChanged: () => void }) {
  const [cohorts, setCohorts] = useState<any[]>([])
  const [draft, setDraft] = useState<Record<string, number>>({})
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  async function refresh() {
    const rows = await get<any[]>('/api/admin/cohorts')
    setCohorts(rows)
    setDraft(
      Object.fromEntries(
        rows.map((row) => [row.cohort, Math.max(...Object.keys(row.currentWeeks).map(Number), 1)]),
      ),
    )
  }

  useEffect(() => {
    void refresh().catch((e) => setError(messageOf(e)))
  }, [])

  async function open(cohort: string) {
    setError('')
    setNotice('')
    try {
      const moved = await post<any>('/api/admin/cohorts/week', { cohort, week: draft[cohort] })
      setNotice(`${cohort || 'Default cohort'} is on week ${moved.week}; ${moved.learnersMoved} learners moved.`)
      await refresh()
      onChanged()
    } catch (e) {
      setError(messageOf(e))
    }
  }

  return (
    <>
      <p className="hint">
        The eight weeks open progressively. Moving a cohort back never deletes work; it only
        changes which week is presented as current.
      </p>
      {cohorts.length === 0 ? (
        <p className="hint">No active learners yet.</p>
      ) : (
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Cohort</th>
                <th>Learners</th>
                <th>Current week</th>
                <th>Move to week</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {cohorts.map((row) => (
                <tr key={row.cohort}>
                  <td>{row.cohort || 'Default cohort'}</td>
                  <td className="num">{row.learners}</td>
                  <td>
                    {Object.entries(row.currentWeeks)
                      .map(([week, count]) => `Week ${week} (${count})`)
                      .join(', ')}
                    {Object.keys(row.currentWeeks).length > 1 ? (
                      <div className="hint">Learners are on different weeks.</div>
                    ) : null}
                  </td>
                  <td>
                    <select
                      aria-label={`Week for ${row.cohort || 'the default cohort'}`}
                      value={draft[row.cohort] ?? 1}
                      onChange={(e) => setDraft({ ...draft, [row.cohort]: Number(e.target.value) })}
                    >
                      {Array.from({ length: 8 }, (_, i) => i + 1).map((week) => (
                        <option key={week} value={week}>
                          Week {week}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button type="button" className="secondary" onClick={() => open(row.cohort)}>
                      Apply
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {error ? <p className="warning" role="alert">{error}</p> : null}
      {notice ? <p className="success" role="status">{notice}</p> : null}
    </>
  )
}

/* ----------------------------------------------------------- issue queue -- */
function IssueQueue() {
  const [filter, setFilter] = useState<string>('open')
  const [issues, setIssues] = useState<any[]>([])
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  async function refresh(status = filter) {
    const rows = await get<any[]>('/api/admin/issues', status === 'all' ? undefined : { status })
    setIssues(rows)
    setNotes(Object.fromEntries(rows.map((row) => [row.id, row.adminNote ?? ''])))
  }

  useEffect(() => {
    void refresh(filter).catch((e) => setError(messageOf(e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

  async function update(id: string, status: string) {
    setError('')
    try {
      await api(`/api/admin/issues/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status, admin_note: notes[id] ?? '' }),
      })
      await refresh()
    } catch (e) {
      setError(messageOf(e))
    }
  }

  return (
    <>
      <div className="segmented" role="group" aria-label="Show issues">
        {(['open', 'acknowledged', 'resolved', 'all'] as const).map((state) => (
          <button key={state} type="button" aria-pressed={filter === state} onClick={() => setFilter(state)}>
            {state[0].toUpperCase() + state.slice(1)}
          </button>
        ))}
      </div>
      {error ? <p className="warning" role="alert">{error}</p> : null}
      {issues.length === 0 ? (
        <p className="hint">No {filter === 'all' ? '' : `${filter} `}reports.</p>
      ) : (
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Reported</th>
                <th>Learner</th>
                <th>Kind</th>
                <th>Where</th>
                <th>Report</th>
                <th>Note to the record</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((issue) => (
                <tr key={issue.id}>
                  <td>{when(issue.createdAt)}</td>
                  <td>{issue.email ?? issue.userId.slice(0, 8)}</td>
                  <td>{issue.category}</td>
                  <td>
                    <code>{issue.screen || '—'}</code>
                    {issue.runId ? <div className="hint">Run {issue.runId.slice(0, 8)}</div> : null}
                  </td>
                  <td className="issue-message">{issue.message}</td>
                  <td>
                    <input
                      aria-label="Note to the record"
                      value={notes[issue.id] ?? ''}
                      onChange={(e) => setNotes({ ...notes, [issue.id]: e.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      aria-label="Status"
                      value={issue.status}
                      onChange={(e) => update(issue.id, e.target.value)}
                    >
                      {ISSUE_STATES.map((state) => (
                        <option key={state} value={state}>
                          {state}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

/* ----------------------------------------------------------------- page -- */
export function Admin() {
  const [usage, setUsage] = useState<any>(null)
  const [completion, setCompletion] = useState<any[]>([])
  const [datasets, setDatasets] = useState<any[]>([])
  const [failures, setFailures] = useState<any[]>([])
  const [lock, setLock] = useState<any>(null)
  const [purchases, setPurchases] = useState<any[]>([])
  const [reference, setReference] = useState('')
  const [error, setError] = useState('')
  //: One check decides whether this is an administrator, so a learner sees one
  //: clear answer rather than every section failing on its own.
  const [access, setAccess] = useState<'checking' | 'granted' | 'forbidden'>('checking')

  async function refreshPurchases() {
    setPurchases(await get<any[]>('/api/admin/purchases'))
  }

  function refreshCompletion() {
    void get<any[]>('/api/admin/completion').then(setCompletion).catch(() => undefined)
  }

  useEffect(() => {
    void get<any>('/api/admin/usage')
      .then((body) => {
        setUsage(body)
        setAccess('granted')
      })
      .catch((e: ApiError) => setAccess(e.status === 401 || e.status === 403 ? 'forbidden' : 'granted'))
  }, [])

  useEffect(() => {
    if (access !== 'granted') return
    void get<any[]>('/api/admin/datasets').then(setDatasets).catch(() => undefined)
    void get<any[]>('/api/admin/runs/failures').then(setFailures).catch(() => undefined)
    void get<any>('/api/admin/method-lock').then(setLock).catch(() => undefined)
    refreshCompletion()
    void refreshPurchases().catch(() => undefined)
  }, [access])

  async function activate(purchaseId: string) {
    setError('')
    try {
      await post(`/api/admin/purchases/${purchaseId}/activate`, {
        provider_reference: reference,
      })
      await refreshPurchases()
    } catch (e) {
      setError((e as ApiError).message)
    }
  }

  const header = (
    <PageHeader
      title="Admin and SME Console"
      lede="Entitlements, datasets, module availability and runtime settings are configurable here. Scientific methods are versioned code changes, not runtime settings."
    />
  )

  if (access === 'checking') {
    return (
      <>
        {header}
        <Skeleton lines={4} />
      </>
    )
  }

  if (access === 'forbidden') {
    return (
      <>
        {header}
        <div className="card">
          <h3>Administrators only</h3>
          <p>
            This console changes prices, run allowances, cohort weeks and learner records, so it
            opens only for administrator accounts. The session you are using is a learner account.
          </p>
        </div>
      </>
    )
  }

  return (
    <>
      {header}

      <div className="card">
        <h3>Usage</h3>
        {usage ? (
          <>
            <div className="stat-row">
              {([
                ['Runs', usage.totalRuns],
                ['Reports', usage.totalReports],
                ['Datasets', usage.totalDatasets],
              ] as [string, number][]).map(([label, value]) => (
                <div className="stat" key={label}>
                  <div className="stat-label">{label}</div>
                  <div className="stat-value">{value ?? 0}</div>
                </div>
              ))}
            </div>
            <div className="admin-counts">
              <CountTable title="Runs by status" counts={usage.byStatus} />
              <CountTable title="Runs by track" counts={usage.byTrack} />
              <CountTable title="Runs by access tier" counts={usage.byAccessTier} />
              <CountTable title="Exports by format" counts={usage.exportsByFormat} />
            </div>
            <h4>Dataset load</h4>
            <div className="scroll">
              <table>
                <thead>
                  <tr>
                    <th>Dataset</th>
                    <th>Validation</th>
                    <th>Runs</th>
                    <th>Last run</th>
                  </tr>
                </thead>
                <tbody>
                  {(usage.datasetLoad ?? []).map((row: any) => (
                    <tr key={row.slug}>
                      <td>{row.name}</td>
                      <td>{row.validationStatus}</td>
                      <td className="num">{row.runs}</td>
                      <td>{when(row.lastRunAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="hint">Loading usage…</p>
        )}
      </div>

      <div className="card">
        <h3>Learner completion</h3>
        {completion.length === 0 ? (
          <p className="hint">No enrolled learners yet.</p>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Learner</th>
                  <th>Cohort</th>
                  <th>Week</th>
                  <th>Runs completed</th>
                  <th>Weeks with a completed run</th>
                  <th>Interpretations</th>
                  <th>Pre-lab</th>
                  <th>Week assessments</th>
                  <th>Capstone</th>
                  <th>Defence score</th>
                </tr>
              </thead>
              <tbody>
                {completion.map((row) => (
                  <tr key={row.userId}>
                    <td>{row.email}</td>
                    <td>{row.cohort || 'Default'}</td>
                    <td className="num">{row.currentWeek}</td>
                    <td className="num">{row.runsCompleted}</td>
                    <td>{listed(row.weeksWithACompletedRun)}</td>
                    <td className="num">{row.interpretations}</td>
                    <td>{listed(row.preLabTaken)}</td>
                    <td>{listed(row.weekAssessments)}</td>
                    <td>{row.capstoneSubmitted ? 'submitted' : 'not yet'}</td>
                    <td className="num">{row.defenceScore == null ? '—' : row.defenceScore}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h3>Cohorts and week unlock</h3>
        <Cohorts onChanged={refreshCompletion} />
      </div>

      <div className="card">
        <h3>Learner-reported issues</h3>
        <IssueQueue />
      </div>

      <div className="card">
        <h3>Commercial terms</h3>
        <CommercialTerms />
      </div>

      <div className="card">
        <h3>Method lock</h3>
        {/* Sign-off is stated only from the lock record itself, never assumed. */}
        {!lock ? (
          <p className="hint">Loading the method lock…</p>
        ) : lock.unsignedOff?.length ? (
          <p className="warning">
            Awaiting SME sign-off before production release: {lock.unsignedOff.join(', ')}
          </p>
        ) : (
          <p>Every locked method has SME sign-off.</p>
        )}
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Area</th>
                <th>Method</th>
                <th>Version</th>
                <th>Signed off</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(lock?.methods ?? {}).map(([key, value]: [string, any]) => (
                <tr key={key}>
                  <td>{key}</td>
                  <td>{value.method}</td>
                  <td>{value.version}</td>
                  <td>{value.sme_signoff ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Paid orders</h3>
        <p className="hint">
          No payment provider is configured. Confirm payment out of band, then record
          its reference here to activate the entitlement.
        </p>
        <label htmlFor="ref">Provider reference</label>
        <input id="ref" value={reference} onChange={(e) => setReference(e.target.value)} />
        {error ? <p className="warning">{error}</p> : null}
        {purchases.length === 0 ? (
          <p className="hint">No orders placed.</p>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Order</th>
                  <th>User</th>
                  <th>Tier</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {purchases.map((purchase) => (
                  <tr key={purchase.id}>
                    <td>{purchase.id.slice(0, 8)}</td>
                    <td>{purchase.userId.slice(0, 8)}</td>
                    <td>{named(TIER_LABEL, purchase.tier)}</td>
                    <td>{purchase.status.replace(/_/g, ' ')}</td>
                    <td>
                      {purchase.status === 'activated' ? null : (
                        <button
                          className="secondary"
                          disabled={!reference}
                          onClick={() => activate(purchase.id)}
                        >
                          Activate
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h3>Datasets</h3>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Track</th>
                <th>Kind</th>
                <th>Accession</th>
                <th>Validation</th>
                <th>Enabled</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((dataset) => (
                <tr key={dataset.id}>
                  <td>{dataset.name}</td>
                  <td>{named(TRACK_NAME, dataset.track)}</td>
                  <td>{named(KIND_LABEL, dataset.kind)}</td>
                  <td>{dataset.accession}</td>
                  <td>{dataset.validationStatus}</td>
                  <td>{dataset.enabled ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Recent run failures</h3>
        {failures.length === 0 ? (
          <p className="hint">No failed runs.</p>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Last valid step</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {failures.map((failure) => (
                  <tr key={failure.id}>
                    <td>{failure.id.slice(0, 8)}</td>
                    <td>{failure.lastValidStep ?? '—'}</td>
                    <td>{failure.errorMessage}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
