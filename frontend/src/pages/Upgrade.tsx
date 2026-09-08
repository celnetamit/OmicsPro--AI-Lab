import { useEffect, useState } from 'react'
import { ApiError, get, post } from '../lib/api'
import { PageHeader, Skeleton } from '../components/ui'

interface Column {
  tier: string
  label: string
  current: boolean
  purchasable: boolean
  features: string[]
  runsPerModulePerWeek: number | null
  perturbationsPerRun: number
  parameterScope: string
  exportFormats: string[]
}

interface CatalogueOption {
  tier: string
  label: string
  termDays: number
  amountMinorUnits: number
  currency: string
  purchasable: boolean
}

interface Purchase {
  id: string
  tier: string
  status: string
  createdAt: string
  activatedAt: string | null
}

function price(option: CatalogueOption): string {
  return `${option.currency} ${(option.amountMinorUnits / 100).toLocaleString()}`
}

export function Upgrade() {
  const [data, setData] = useState<{ columns: Column[]; note: string } | null>(null)
  const [catalogue, setCatalogue] = useState<CatalogueOption[]>([])
  const [purchases, setPurchases] = useState<Purchase[]>([])
  const [expiry, setExpiry] = useState<any>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function refresh() {
    setPurchases(await get<Purchase[]>('/api/billing/purchases'))
    setExpiry(await get<any>('/api/billing/expiry'))
  }

  useEffect(() => {
    void get<{ columns: Column[]; note: string }>('/api/entitlements/upgrade-options').then(setData)
    void get<{ options: CatalogueOption[] }>('/api/billing/catalogue').then((d) =>
      setCatalogue(d.options),
    )
    void refresh()
  }, [])

  async function order(tier: string) {
    setError('')
    setMessage('')
    try {
      const result = await post<any>('/api/billing/checkout', { tier })
      setMessage(result.note)
      await refresh()
    } catch (e) {
      setError((e as ApiError).message)
    }
  }

  if (!data) {
    return (
      <>
        <PageHeader title="Access Options" />
        <Skeleton lines={4} />
        <span className="visually-hidden" role="status">
          Loading
        </span>
      </>
    )
  }

  return (
    <>
      <PageHeader title="Access Options" lede={data.note} />

      <div className="grid">
        {data.columns.map((column) => (
          <article className="card" key={column.tier}>
            <span className="badge">{column.current ? 'Your access' : column.label}</span>
            <h3>{column.label}</h3>
            <p className="hint">
              {column.runsPerModulePerWeek === null
                ? 'Unmetered runs'
                : `${column.runsPerModulePerWeek} runs per module per week`}{' '}
              · {column.perturbationsPerRun} what-if tests per run · {column.parameterScope}{' '}
              parameter ranges
            </p>
            <p>
              <strong>Adds</strong>
            </p>
            <ul>
              {column.features.map((feature) => (
                <li key={feature}>{feature}</li>
              ))}
            </ul>
            <p className="hint">Exports: {column.exportFormats.join(', ')}</p>
            {column.purchasable ? (
              <PurchaseButton
                option={catalogue.find((o) => o.tier === column.tier)}
                onOrder={() => order(column.tier)}
              />
            ) : null}
          </article>
        ))}
      </div>

      {message ? <p className="hint">{message}</p> : null}
      {error ? <p className="warning">{error}</p> : null}

      {purchases.length ? (
        <div className="card">
          <h3>Your orders</h3>
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Tier</th>
                  <th>Status</th>
                  <th>Placed</th>
                </tr>
              </thead>
              <tbody>
                {purchases.map((purchase) => (
                  <tr key={purchase.id}>
                    <td>{purchase.id.slice(0, 8)}</td>
                    <td>{purchase.tier}</td>
                    <td>{purchase.status.replace(/_/g, ' ')}</td>
                    <td>{new Date(purchase.createdAt).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {expiry ? (
        <div className="card">
          <h3>When paid access ends</h3>
          {expiry.paidGrants.length ? (
            <ul>
              {expiry.paidGrants.map((grant: any) => (
                <li key={grant.tier}>
                  {grant.tier} access runs until{' '}
                  {new Date(grant.expiresAt).toLocaleDateString()}
                </li>
              ))}
            </ul>
          ) : (
            <p className="hint">No paid access is currently active on this account.</p>
          )}
          <p className="hint">{expiry.note}</p>
          <p className="hint">
            {expiry.reportsRetained} report(s) are retained on this account.
          </p>
        </div>
      ) : null}

      <p className="caveat">
        The teaching content of every week is included at every access level. Paid tiers add
        depth, repetition, independence and richer outputs.
      </p>
    </>
  )
}

function PurchaseButton({
  option,
  onOrder,
}: {
  option?: CatalogueOption
  onOrder: () => void
}) {
  if (!option) return null
  return (
    <>
      <button onClick={onOrder}>
        Order — {price(option)} for {option.termDays} days
      </button>
      <p className="hint">
        Payment is confirmed separately; access activates once it clears.
      </p>
    </>
  )
}
