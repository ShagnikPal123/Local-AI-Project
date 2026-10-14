/** Settings › Storage › Old chats: the opt-in auto clean-up (Fixer Upper S25).
 *
 * Off by default. When on, empty chats and (optionally) long-idle chats move to Recently deleted, where Restore works for
 * 30 days. The count shown is what a sweep would take right now, so the owner sees the effect before trusting it.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";

interface CleanState { enabled: boolean; empty_hours: number; old_days: number; would_delete: number }

const OLD_CHOICES = [{ days: 0, label: "Never" }, { days: 30, label: "30 days" }, { days: 90, label: "90 days" }, { days: 180, label: "180 days" }];

export function ChatCleanupSection() {
  const [state, setState] = useState<CleanState | null>(null);
  const [note, setNote] = useState("");
  const load = useCallback(async () => {
    const result = await api.get<CleanState>("/api/chat-auto-clean");
    if (result.ok) setState(result.data);
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function change(patch: Partial<Pick<CleanState, "enabled" | "empty_hours" | "old_days">>) {
    const result = await api.put<CleanState>("/api/chat-auto-clean", patch);
    if (result.ok) setState(result.data);
  }
  async function runNow() {
    const result = await api.post<{ removed: number }>("/api/chat-auto-clean/run", {});
    setNote(result.ok ? (result.data.removed ? `Moved ${result.data.removed} to Recently deleted.` : "Nothing to clean up.") : "That did not work.");
    void load();
  }

  if (!state) return <p className="appearance__hint">Loading…</p>;
  return (
    <div className="appearance">
      <div className="appearance__row">
        <span className="appearance__label">Clean up chats automatically</span>
        <label className="appearance__custom">
          <input type="checkbox" role="switch" checked={state.enabled} onChange={(e) => void change({ enabled: e.target.checked })} aria-label="Clean up chats automatically" />
          {state.enabled ? "On" : "Off"}
        </label>
        <span className="appearance__hint">Deleted chats can be restored from Recently deleted for 30 days. The chat you have open and chats you renamed or branched are never touched.</span>
      </div>
      <div className="appearance__row">
        <span className="appearance__label">Empty chats after</span>
        <select value={state.empty_hours} onChange={(e) => void change({ empty_hours: Number(e.target.value) })} disabled={!state.enabled} aria-label="Delete empty chats after">
          {[1, 6, 24, 72, 168].map((h) => <option key={h} value={h}>{h < 24 ? `${h} hour${h > 1 ? "s" : ""}` : `${h / 24} day${h > 24 ? "s" : ""}`}</option>)}
        </select>
      </div>
      <div className="appearance__row">
        <span className="appearance__label">Chats not touched for</span>
        <select value={state.old_days} onChange={(e) => void change({ old_days: Number(e.target.value) })} disabled={!state.enabled} aria-label="Delete chats not touched for">
          {OLD_CHOICES.map((c) => <option key={c.days} value={c.days}>{c.label}</option>)}
        </select>
      </div>
      <div className="appearance__row">
        <button type="button" className="btn" onClick={() => void runNow()} disabled={!state.enabled}>Clean up now</button>
        <span className="appearance__hint">{note || (state.enabled ? `${state.would_delete} chat${state.would_delete === 1 ? "" : "s"} would be moved right now.` : "Turn it on to use it.")}</span>
      </div>
    </div>
  );
}
