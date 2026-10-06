/** One tab's crash stays in that tab (Update 1, found by the tab sweep).
 *
 * Without a boundary, an error thrown while rendering any panel unmounted the whole app: the tab bar, the chat and
 * every other tab went blank together. Now the broken tab says what went wrong and offers to try again, and the rest
 * of Nyx keeps working. It is keyed by tab in App, so moving to another tab and back starts it fresh.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

interface State { error: Error | null }

export class TabBoundary extends Component<{ name: string; children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`The ${this.props.name} tab crashed`, error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div role="alert" style={{ display: "grid", gap: 10, placeContent: "center", height: "100%", padding: 24, textAlign: "center" }}>
        <b style={{ fontSize: 15 }}>The {this.props.name} tab hit a problem.</b>
        <span style={{ fontSize: 13, color: "var(--color-neutral-400)", maxWidth: 520 }}>{error.message || String(error)}</span>
        <span style={{ fontSize: 12.5, color: "var(--color-neutral-500)" }}>The rest of Nyx is fine — other tabs keep working.</span>
        <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
          <button className="btn btn-primary" onClick={() => this.setState({ error: null })}>Try again</button>
          <button className="btn btn-secondary" onClick={() => window.location.reload()}>Reload Nyx</button>
        </div>
      </div>
    );
  }
}
