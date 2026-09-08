import { useState } from 'react'
import { ApiError, post, setToken } from '../lib/api'
import { useSession } from '../components/Session'

/** Mirrors app.core.security.validate_password; the server decides, this only
 *  spares the learner a round trip to be told the obvious. */
const MIN_PASSWORD_LENGTH = 10

export function Login() {
  const { refresh } = useSession()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const registering = mode === 'register'
  const passwordTooShort = registering && password.length > 0 && password.length < MIN_PASSWORD_LENGTH

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const body = registering ? { email, password, full_name: fullName } : { email, password }
      const result = await post<{ access_token: string }>(`/api/auth/${mode}`, body)
      setToken(result.access_token)
      await refresh()
    } catch (err) {
      const apiError = err as ApiError
      setError(apiError.fieldErrors?.password ?? apiError.message)
    } finally {
      setBusy(false)
    }
  }

  function switchMode() {
    setMode(registering ? 'login' : 'register')
    setError('')
  }

  return (
    <div className="auth-shell">
      <div className="auth">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">OL</span>
          <span className="brand-text">
            <span className="brand-name">OmicsLab Pro</span>
            <span className="brand-sub">NanoSchool Live Lab</span>
          </span>
        </div>

        <h2>{registering ? 'Create your account' : 'Sign in'}</h2>
        <p className="lede">
          The Live Lab for the eight-week single-cell and spatial transcriptomics program.
        </p>

        <form className="card" onSubmit={submit} noValidate>
          {registering ? (
            <div className="field">
              <label htmlFor="name">Full name</label>
              <input
                id="name"
                autoComplete="name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              required
              autoComplete={registering ? 'new-password' : 'current-password'}
              aria-invalid={passwordTooShort || undefined}
              aria-describedby={registering ? 'password-help' : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {registering ? (
              <p className="hint" id="password-help">
                At least {MIN_PASSWORD_LENGTH} characters, mixing letters with a number
                or symbol. Length matters more than punctuation.
              </p>
            ) : null}
          </div>

          {error ? (
            <div className="note warning" role="alert">
              <div className="note-body">{error}</div>
            </div>
          ) : null}

          <button className="block mt-4" disabled={busy || (registering && passwordTooShort)}>
            {busy ? <span className="spinner" aria-hidden="true" /> : null}
            {registering ? 'Create account' : 'Sign in'}
          </button>

          {registering ? (
            <p className="hint mt-4">
              Enrolling in the flagship program grants Basic access automatically — it
              is never sold.
            </p>
          ) : null}
        </form>

        <p className="auth-switch">
          {registering ? 'Already enrolled?' : 'New here?'}{' '}
          <button type="button" className="ghost small" onClick={switchMode}>
            {registering ? 'Sign in instead' : 'Create an account'}
          </button>
        </p>
      </div>
    </div>
  )
}
