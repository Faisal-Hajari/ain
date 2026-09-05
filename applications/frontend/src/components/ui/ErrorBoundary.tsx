import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  /** Rendered in place of the children when they throw. */
  fallback: (reset: () => void) => ReactNode
  /** Changing this resets the boundary - use it to retry on new inputs. */
  resetKey?: string
  children: ReactNode
}

interface State {
  failed: boolean
}

/**
 * Contains a render-time throw so one bad payload takes out one card instead of
 * the dashboard. Class syntax because React exposes no hook equivalent.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidUpdate(previous: Props) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false })
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Render failed inside an error boundary', error, info.componentStack)
  }

  render() {
    if (this.state.failed) return this.props.fallback(() => this.setState({ failed: false }))
    return this.props.children
  }
}
