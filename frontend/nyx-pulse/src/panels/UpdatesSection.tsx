/** Settings → Updates: the release channel, a verified download, install on restart, roll back (Request G2).
 *
 * The flow is `beta_channel.py`: a reviewed GitHub pre-release is the only thing a
 * tester's copy installs; the zip must match its published SHA-256; it is applied
 * the next time Nyx starts, with a backup of every file it replaces. This panel
 * only shows that and asks before the two actions that change files.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

interface Staged { version: string; sha256: string; notes: string; downloaded_at: number }
interface LastApply { ok: boolean; version: string; detail: string; files?: number; at: number }
interface Status {
  channel: "beta" | "stable"; repo: string; local_version: string; install_kind: "git" | "zip";
  staged: Staged | null; last_apply: LastApply | null; can_roll_back: boolean;
}
interface Check {
  ok: boolean; detail: string; available?: boolean;
  latest?: { version: string; notes: string; published_at?: string };
  staged?: Staged | null;
}

function shortHash(hash: string): string {
  return hash.length > 16 ? `${hash.slice(0, 8)}…${hash.slice(-8)}` : hash;
}

export function UpdatesSection() {
  const [status, setStatus] = useState<Status | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const [working, setWorking] = useState("");
  const [confirm, setConfirm] = useState<"" | "restart" | "rollback">("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    const result = await api.get<Status>("/api/updates/status");
    if (result.ok) setStatus(result.data);
    else setMessage(result.error);
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function setChannel(channel: "beta" | "stable") {
    if (!status || status.channel === channel) return;
    setStatus({ ...status, channel });
    const result = await api.put<{ channel: string }>("/api/updates/channel", { channel });
    if (!result.ok) setMessage(result.error);
    setCheck(null);
    void load();
  }

  async function checkRelease() {
    setWorking("Checking the release channel…");
    const result = await api.get<Check>("/api/updates", 60_000);
    setWorking("");
    if (!result.ok) { setMessage(result.error); return; }
    setCheck(result.data);
    setMessage("");
  }

  async function download() {
    setWorking("Downloading and checking the file…");
    const result = await api.post<Check & { installed?: boolean }>("/api/updates/install", {}, 330_000);
    setWorking("");
    if (!result.ok) { setMessage(result.error); return; }
    setCheck(result.data);
    setMessage(result.data.detail);
    void load();
  }

  async function restart() {
    setConfirm("");
    setWorking("Restarting Nyx to install…");
    await api.post("/api/engine/restart", {});
    setMessage("Nyx is restarting. This page reconnects when it is back.");
    setWorking("");
  }

  async function rollback() {
    setConfirm("");
    setWorking("Putting the previous files back…");
    const result = await api.post<{ detail: string }>("/api/updates/rollback", {});
    setWorking("");
    setMessage(result.ok ? result.data.detail : result.error);
    void load();
  }

  if (!status) return message ? <div className="field-row__hint">{message}</div> : null;
  const staged = status.staged;

  return (
    <div style={{ display: "grid", gap: 10, marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--color-divider)" }}>
      <div className="field-row">
        <div className="field-row__text">
          <div className="field-row__label">This copy</div>
          <div className="field-row__hint">
            Version {status.local_version} · {status.install_kind === "git"
              ? "a git checkout, so it updates with git (above)"
              : `installed from a release zip — updates come from reviewed releases on ${status.repo}`}
          </div>
        </div>
      </div>

      <div className="field-row">
        <div className="field-row__text">
          <div className="field-row__label">Release channel</div>
          <div className="field-row__hint">
            Beta gets each reviewed pre-release as soon as it is published; Stable waits for full releases.
          </div>
        </div>
        <div className="segmented" role="group" aria-label="Release channel">
          <button aria-pressed={status.channel === "beta"} onClick={() => void setChannel("beta")}>Beta</button>
          <button aria-pressed={status.channel === "stable"} onClick={() => void setChannel("stable")}>Stable</button>
        </div>
      </div>

      {status.install_kind === "zip" && (
        <>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <button className="btn btn-secondary" disabled={!!working} onClick={() => void checkRelease()}>Check for a release</button>
            {check?.available && !staged && (
              <button className="btn btn-primary" disabled={!!working} onClick={() => void download()}>
                Download {check.latest?.version}
              </button>
            )}
            {check && <span className="field-row__hint" aria-live="polite">{check.detail}</span>}
          </div>
          {check?.latest?.notes && !staged && (
            <details>
              <summary className="field-row__hint" style={{ cursor: "pointer" }}>What's new in {check.latest.version}</summary>
              <p className="field-row__hint" style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{check.latest.notes}</p>
            </details>
          )}
        </>
      )}

      {staged && (
        <div className="card" style={{ display: "grid", gap: 6, padding: 12 }}>
          <div className="field-row__label">✓ Version {staged.version} is downloaded and verified</div>
          <div className="field-row__hint">
            Its checksum matched the published one (SHA-256 {shortHash(staged.sha256)}). It installs the next time Nyx
            starts; your chats, keys, memory and notes are never touched.
          </div>
          {confirm === "restart" ? (
            <div role="alertdialog" aria-label="Restart to install" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <span className="field-row__hint">Nyx stops for about 20 seconds while it installs.</span>
              <button className="btn btn-secondary" autoFocus onClick={() => setConfirm("")}>Cancel</button>
              <button className="btn btn-primary" onClick={() => void restart()}>Restart and Install</button>
            </div>
          ) : (
            <button className="btn btn-primary" style={{ justifySelf: "start" }} disabled={!!working} onClick={() => setConfirm("restart")}>
              Restart to Install…
            </button>
          )}
        </div>
      )}

      {status.last_apply && (
        <div className="field-row__hint">
          {status.last_apply.ok ? "✓" : "⚠"} Last install: {status.last_apply.detail}
          {status.last_apply.at ? ` (${new Date(status.last_apply.at * 1000).toLocaleString()})` : ""}
        </div>
      )}

      {status.can_roll_back && (
        confirm === "rollback" ? (
          <div role="alertdialog" aria-label="Roll back the last update" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span className="field-row__hint">This puts back the files version {status.last_apply?.version} replaced. Restart Nyx afterwards.</span>
            <button className="btn btn-secondary" autoFocus onClick={() => setConfirm("")}>Cancel</button>
            <button className="btn btn-danger" onClick={() => void rollback()}>Roll Back</button>
          </div>
        ) : (
          <button className="btn btn-secondary" style={{ justifySelf: "start" }} disabled={!!working} onClick={() => setConfirm("rollback")}>
            Roll Back the Last Update…
          </button>
        )
      )}

      {working && <div className="field-row__hint" role="status">◌ {working}</div>}
      {message && !working && <div className="field-row__hint" aria-live="polite">{message}</div>}
    </div>
  );
}
