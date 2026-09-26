/** Toasts: transient notices from the workspace (tab created, skill kept, errors).
 *
 * Rendered as an aria-live list so screen readers hear them; level is carried
 * by a border *and* a text glyph, never colour alone. Auto-dismiss lives in
 * the store; these buttons only remove.
 */

import type { ToastsProps } from "./types";

const GLYPH: Record<string, string> = { info: "•", ok: "✓", warn: "⚠", error: "✕" };

const BORDER: Record<string, string> = {
  info: "var(--color-divider)",
  ok: "var(--color-ok)",
  warn: "var(--color-warn)",
  error: "var(--color-danger)",
};

export function Toasts({ items, onDismiss }: ToastsProps) {
  if (items.length === 0) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "fixed", bottom: 16, right: 16, zIndex: 60,
        display: "flex", flexDirection: "column", gap: 8, maxWidth: 340,
      }}
    >
      {items.map((toast) => (
        <div
          key={toast.id}
          style={{
            display: "flex", alignItems: "flex-start", gap: 8,
            background: "var(--color-surface)", borderRadius: "var(--radius)",
            boxShadow: `inset 0 0 0 1px ${BORDER[toast.level]}, 0 4px 16px rgba(0,0,0,.35)`,
            padding: "9px 12px", fontSize: 12, lineHeight: 1.5,
          }}
        >
          <span aria-hidden="true" style={{ color: BORDER[toast.level] }}>{GLYPH[toast.level]}</span>
          <span style={{ flex: 1, minWidth: 0 }}>
            {toast.text}
            {toast.action && (
              <button
                onClick={toast.action.onClick}
                style={{
                  display: "block", background: "none", border: "none", padding: 0,
                  cursor: "pointer", font: "inherit", fontSize: 11, marginTop: 3,
                  color: "var(--color-accent)", textDecoration: "underline",
                }}
              >
                {toast.action.label}
              </button>
            )}
          </span>
          <button
            onClick={() => onDismiss(toast.id)}
            aria-label="Dismiss"
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-neutral-600)", font: "inherit", fontSize: 11, padding: 0 }}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
