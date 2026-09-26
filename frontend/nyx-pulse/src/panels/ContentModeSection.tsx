/** Settings → Content: adult mode (owner request, 2026-09-15).
 *
 * One switch, and a plain list of what it does and does not change. The four hard limits are stated
 * on screen rather than discovered by hitting them.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

export function ContentModeSection() {
  const [on, setOn] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const result = await api.get<{ adult_mode: boolean }>("/api/content-mode");
    if (result.ok) setOn(result.data.adult_mode); else setError(result.error);
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function toggle(next: boolean) {
    setBusy(true);
    const result = await api.put<{ adult_mode: boolean }>("/api/content-mode", { adult_mode: next });
    setBusy(false);
    if (!result.ok) { setError(result.error); return; }
    setOn(result.data.adult_mode);
    setError("");
  }

  return (
    <div className="content-mode">
      <label className="content-mode__switch">
        <input type="checkbox" role="switch" checked={Boolean(on)} disabled={on === null || busy}
          onChange={(e) => void toggle(e.target.checked)} />
        <span>
          <b>Adult mode</b>
          <span className="muted">{on ? "On — mature themes, language and images are allowed when you ask." : "Off — Nyx keeps everything work-safe."}</span>
        </span>
      </label>
      <ul className="content-mode__limits">
        <li>Always refused, in both modes: anything sexual involving minors; sexual or intimate images of a real person; sexualised force or anyone who cannot consent; anything illegal.</li>
        <li>The model providers apply their own rules too. If one refuses, Nyx names it instead of pretending it was its own choice.</li>
      </ul>
      {error && <p className="content-mode__error" role="alert">{error}</p>}
    </div>
  );
}
