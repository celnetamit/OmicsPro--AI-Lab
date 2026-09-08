/**
 * Last line of defence for the client.
 *
 * A render error in one screen would otherwise blank the whole application and
 * leave the learner staring at white. This keeps the failure legible, offers a
 * way back, and logs the detail to the console for a support conversation.
 */
import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('OmicsLab: unhandled render error', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="auth-shell">
        <div className="auth">
          <div className="card">
            <h2>This screen could not be displayed</h2>
            <p className="lede">
              Something went wrong drawing this page. Your work is stored on the
              server, so nothing you saved has been lost.
            </p>
            <div className="row mt-4">
              <button type="button" onClick={() => window.location.assign('/')}>
                Back to Lab Home
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => window.location.reload()}
              >
                Reload the page
              </button>
            </div>
            <p className="hint mt-4 mono">{this.state.error.message}</p>
          </div>
        </div>
      </div>
    )
  }
}
