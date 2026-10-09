/** The World tab — the AI Environment planet (UPDATE_IDEAS U34–U40).
 *
 * Opens the world that is running, or the one Office Space's Upscale button just made (it leaves the id in
 * ``sessionStorage["nyx.world.open"]`` and fires ``nyx:world-open``), otherwise the lobby. Design and decisions:
 * ``docs/WORLD.md``.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { WorldLobby } from "./WorldLobby";
import { WorldView } from "./WorldView";
import type { WorldOverview } from "./types";
import { worldApi } from "./worldApi";
import "../office/office.css";
import "./world.css";

export const OPEN_KEY = "nyx.world.open";

function takeRequested(): string {
  try {
    const id = sessionStorage.getItem(OPEN_KEY) ?? "";
    if (id) sessionStorage.removeItem(OPEN_KEY);
    return id;
  } catch {
    return "";
  }
}

export function WorldPanel() {
  const [overview, setOverview] = useState<WorldOverview | null>(null);
  const [worldId, setWorldId] = useState("");
  const [error, setError] = useState("");
  const started = useRef(false);

  const load = useCallback(async () => {
    const result = await worldApi.overview();
    if (!result.ok) {
      setError(result.error);
      return null;
    }
    setOverview(result.data);
    return result.data;
  }, []);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      const data = await load();
      const requested = takeRequested();
      if (requested) setWorldId(requested);
      else if (data?.running) setWorldId(data.running);
    })();
  }, [load]);

  useEffect(() => {
    const onOpen = (event: Event) => {
      const id = String((event as CustomEvent<{ id?: string }>).detail?.id ?? takeRequested());
      if (id) {
        setWorldId(id);
        void load();
      }
    };
    window.addEventListener("nyx:world-open", onOpen);
    return () => window.removeEventListener("nyx:world-open", onOpen);
  }, [load]);

  if (error && !overview) {
    return (
      <div className="wld wld-message">
        <h1>World</h1>
        <p className="ofc-error">{error}</p>
        <button type="button" className="ofc-btn" onClick={() => { setError(""); void load(); }}>Try again</button>
      </div>
    );
  }
  if (!overview) return <div className="wld wld-message"><p className="ofc-muted">Opening the worlds…</p></div>;

  return (
    <div className="wld ofc">
      {error && (
        <p className="ofc-error ofc-error--bar" role="status">
          {error} <button type="button" className="ofc-link" onClick={() => setError("")}>dismiss</button>
        </p>
      )}
      {worldId ? (
        <WorldView key={worldId} worldId={worldId} onError={setError}
                   onLobby={() => { setWorldId(""); void load(); }} />
      ) : (
        <WorldLobby overview={overview} onOpen={setWorldId} onChanged={() => void load()} onError={setError} />
      )}
    </div>
  );
}
