/** Office Space (Project Null N8) — the tab.
 *
 * First time ever: it makes an office file and opens its chat straight away, because *"For the first project it
 * creates a file and opens the chat instantly."* Every time after that it opens the lobby of past offices —
 * unless one is still working, in which case it opens that one, since that is plainly what you came for.
 *
 * Before any work starts it asks the one question the owner asked for: shut everything else down and run only
 * this? The answer can be remembered, and whatever it pauses resumes by itself when the office finishes.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { officeApi } from "./officeApi";
import { useOffice } from "./useOffice";
import { Lobby } from "./Lobby";
import { OfficeView } from "./OfficeView";
import { FocusSheet } from "./Pieces";
import type { OfficeOverview } from "./types";
import "./office.css";

export function OfficePanel() {
  const [overview, setOverview] = useState<OfficeOverview | null>(null);
  const [officeId, setOfficeId] = useState("");
  const [error, setError] = useState("");
  const [asking, setAsking] = useState(false);
  const started = useRef(false);
  const live = useOffice(officeId);

  const load = useCallback(async () => {
    const result = await officeApi.overview();
    if (!result.ok) {
      setError(result.error);
      return null;
    }
    setOverview(result.data);
    setError("");
    return result.data;
  }, []);

  // First open: make the first office and go straight into its chat; otherwise show the lobby (or the office
  // that is working right now).
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      const data = await load();
      if (!data) return;
      if (data.running_office) {
        setOfficeId(data.running_office);
        return;
      }
      if (data.first_run) {
        const made = await officeApi.newOffice("My first office", "");
        if (made.ok) {
          setOfficeId(made.data.office.id);
          await load();
        } else {
          setError(made.error);
        }
      }
    })();
  }, [load]);

  // The focus question, asked once per open office when the setting says "ask".
  useEffect(() => {
    if (!officeId || !overview) return;
    if (overview.settings.focus_mode === "ask" && !overview.focus.held) setAsking(true);
    if (overview.settings.focus_mode === "always" && !overview.focus.held) {
      void officeApi.focus("enter", officeId).then(() => load());
    }
  }, [officeId, overview, load]);

  const answerFocus = async (pause: boolean, remember: boolean) => {
    setAsking(false);
    const rememberAs = remember ? (pause ? "always" : "never") : "";
    if (pause) await officeApi.focus("enter", officeId, rememberAs);
    else if (rememberAs) await officeApi.saveSettings({ focus_mode: rememberAs });
    await load();
    void live.reload();
  };

  const openOffice = async (id: string) => {
    setOfficeId(id);
    await load();
  };

  const newOffice = async (parent: string) => {
    const made = await officeApi.newOffice("", parent);
    if (!made.ok) {
      setError(made.error);
      return;
    }
    await load();
    setOfficeId(made.data.office.id);
  };

  if (error && !overview) {
    return (
      <div className="ofc ofc--message">
        <h1>Office Space</h1>
        <p className="ofc-error">{error}</p>
        <button className="ofc-btn" onClick={() => void load()}>Try again</button>
      </div>
    );
  }

  if (!overview) {
    return <div className="ofc ofc--message"><p className="ofc-muted">Opening the office…</p></div>;
  }

  return (
    <div className="ofc">
      {error && (
        <p className="ofc-error ofc-error--bar" role="status">
          {error} <button className="ofc-link" onClick={() => setError("")}>dismiss</button>
        </p>
      )}

      {officeId && live.snapshot ? (
        <OfficeView live={live} snapshot={live.snapshot} tree={overview.library}
                    onLobby={() => setOfficeId("")} onOpenOffice={(id) => void openOffice(id)}
                    onNewOffice={(parent) => void newOffice(parent)} onError={setError} />
      ) : officeId ? (
        <div className="ofc--message"><p className="ofc-muted">Opening that office…</p></div>
      ) : (
        <Lobby tree={overview.library} onOpen={(id) => void openOffice(id)}
               onChanged={async () => { await load(); }}
               onError={setError} runningOffice={overview.running_office} />
      )}

      {asking && officeId && (
        <FocusSheet focus={overview.focus} officeName={live.snapshot?.office.name ?? "This office"}
                    onAnswer={(pause, remember) => void answerFocus(pause, remember)} />
      )}
    </div>
  );
}
