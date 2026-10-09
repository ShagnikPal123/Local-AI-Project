/** Try what was built (site_preview.py, U11/U12): run the folder and keep it running, look at it inside Nyx, open it
 * in a browser, or download it as a zip. The owner: "open it either on a download where I can actually do things
 * without posting or on a website page or on the AI environment itself." Nothing here publishes anything. */

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api, authHeaders } from "../../api";
import { pushToast } from "../../state/toastStore";

interface Preview { id: string; folder: string; name: string; mode: "static" | "dev"; url: string; note: string; alive: boolean }

const same = (a: string, b: string) => a.replace(/[\\/]+$/, "").toLowerCase() === b.replace(/[\\/]+$/, "").toLowerCase();

export function PreviewBar({ folder }: { folder: string }) {
  const [previews, setPreviews] = useState<Preview[]>([]);
  const [busy, setBusy] = useState("");
  const [inside, setInside] = useState(false);
  const [frameKey, setFrameKey] = useState(0);

  const load = useCallback(async () => {
    const result = await api.get<{ previews: Preview[] }>("/api/code/previews");
    if (result.ok) setPreviews(result.data.previews);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const mine = previews.find((p) => same(p.folder, folder) && p.alive);
  const name = folder.split(/[\\/]/).filter(Boolean).pop() ?? folder;

  const run = async () => {
    setBusy("run");
    const result = await api.post<{ preview: Preview }>("/api/code/previews", { path: folder }, 120000);
    setBusy("");
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    await load();
    setInside(true);
    if (result.data.preview.note) pushToast(result.data.preview.note, "info");
  };

  const stop = async () => {
    if (!mine) return;
    setBusy("stop");
    await api.del(`/api/code/previews/${mine.id}`);
    setBusy("");
    setInside(false);
    await load();
  };

  const download = async () => {
    setBusy("zip");
    try {
      const response = await fetch(`/api/code/download?path=${encodeURIComponent(folder)}`, { headers: authHeaders() });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({ detail: "The download did not work." }));
        pushToast(String(detail.detail ?? "The download did not work."), "warn");
        return;
      }
      const blob = await response.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `${name}.zip`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <div className="code-try" role="group" aria-label={`Try ${name}`}>
        <span className="code__muted">Try {name}:</span>
        {mine ? (
          <>
            <button className="chat-inline" onClick={() => setInside((v) => !v)} aria-pressed={inside}>{inside ? "Hide Preview" : "View in Nyx"}</button>
            <a className="chat-inline" href={mine.url} target="_blank" rel="noreferrer">Open in Browser</a>
            <button className="chat-inline" onClick={() => void stop()} disabled={!!busy}>Stop</button>
          </>
        ) : (
          <button className="chat-inline" onClick={() => void run()} disabled={!!busy}>{busy === "run" ? "Starting…" : "Run ▸"}</button>
        )}
        <button className="chat-inline" onClick={() => void download()} disabled={!!busy}>{busy === "zip" ? "Packing…" : "Download .zip"}</button>
      </div>
      {mine && inside && createPortal(
        <div className="code-preview" role="dialog" aria-label={`Preview of ${name}`}>
          <div className="code-preview__bar">
            <b>{name}</b>
            <span className="code__muted">{mine.url}{mine.mode === "dev" ? " · its dev server" : ""}</span>
            <button className="chat-inline" onClick={() => setFrameKey((k) => k + 1)}>Reload</button>
            <a className="chat-inline" href={mine.url} target="_blank" rel="noreferrer">Open in Browser</a>
            <button className="chat-inline" onClick={() => setInside(false)} aria-label="Close preview">✕</button>
          </div>
          <iframe key={frameKey} src={mine.url} title={`Preview of ${name}`} sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-modals" />
        </div>,
        document.body,
      )}
    </>
  );
}
