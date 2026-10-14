/** Toasts: transient notices from the workspace (tab created, skill kept, errors).
 *
 * Rendered as an aria-live list so screen readers hear them; level is carried
 * by a border *and* a text glyph, never colour alone. Auto-dismiss lives in
 * the store; these buttons only remove.
 */

import { useEffect, type CSSProperties } from "react";
import { loadToastPosition, useToastPosition, type ToastPosition } from "../../state/toastStore";
import type { ToastsProps } from "./types";

/** Where each corner puts the stack. The middle ones centre it; the top ones grow downwards. */
const PLACE: Record<ToastPosition, CSSProperties> = {
  "top-left": { top: 16, left: 16 },
  "top-center": { top: 16, left: "50%", transform: "translateX(-50%)" },
  "top-right": { top: 16, right: 16 },
  "bottom-left": { bottom: 16, left: 16 },
  "bottom-center": { bottom: 16, left: "50%", transform: "translateX(-50%)" },
  "bottom-right": { bottom: 16, right: 16 },
};

const GLYPH: Record<string, string> = { info: "•", ok: "✓", warn: "⚠", error: "✕" };

const BORDER: Record<string, string> = {
  info: "var(--color-divider)",
  ok: "var(--color-ok)",
  warn: "var(--color-warn)",
  error: "var(--color-danger)",
};

export function Toasts({ items, onDismiss }: ToastsProps) {
  const position = useToastPosition();
  useEffect(() => { loadToastPosition(); }, []);
  if (items.length === 0) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "fixed", ...PLACE[position], zIndex: 60,
        display: "flex", flexDirection: position.startsWith("top") ? "column-reverse" : "column", gap: 8, maxWidth: 340,
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
            {toast.title && <strong style={{ display: "block", marginBottom: 1 }}>{toast.title}</strong>}
            {toast.text}
            {toast.action && (
              <button
                onClick={toast.action.onClick}
                style={{
                  display: "block", background: "none", border: "none", padding: 0,
                  cursor: "pointer", font: "inherit", fontSize: 12, marginTop: 3,
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
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-neutral-600)", font: "inherit", fontSize: 12, padding: 0 }}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
