import { useEffect, useState } from 'react'
import { ApiError, get, post } from '../lib/api'

export function Admin() {
  const [usage, setUsage] = useState<any>(null)
  const [datasets, setDatasets] = useState<any[]>([])
  const [failures, setFailures] = useState<any[]>([])
  const [lock, setLock] = useState<any>(null)
  const [purchases, setPurchases] = useState<any[]>([])
  const [reference, setReference] = useState('')
  const [error, setError] = useState('')

  async function refreshPurchases() {
    setPurchases(await get<any[]>('/api/admin/purchases'))
  }

  useEffect(() => {
    void get<any>('/api/admin/usage').then(setUsage)
    void get<any[]>('/api/admin/datasets').then(setDatasets)
    void get<any[]>('/api/admin/runs/failures').then(setFailures)
    void get<any>('/api/admin/method-lock').then(setLock)
    void refreshPurchases()
  }, [])

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

  return (
    <>
      <h2>Admin and SME Console</h2>
      <p className="lede">
        Entitlements, datasets, module availability and runtime settings are configurable
        here. Scientific methods are versioned code changes, not runtime settings.
      </p>

      <div className="card">
        <h3>Usage</h3>
        <pre style={{ fontSize: 12.5 }}>{JSON.stringify(usage, null, 2)}</pre>
      </div>

      <div className="card">
        <h3>Method lock</h3>
        {lock?.unsignedOff?.length ? (
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
                  <td>{purchase.tier}</td>
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
                  <td>{dataset.track}</td>
                  <td>{dataset.kind}</td>
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
        )}
      </div>
    </>
  )
}
