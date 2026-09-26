/** The drop box that appears the moment a file is dragged over Nyx.
 *
 * The owner: "even if I don't click on it I can drag it, the site ids that it's
 * a file, then pulls up the file drop box."
 *
 * It listens on the window, so it does not matter where the file is dragged —
 * over the chat, over a tab, over an open sheet. Dragged text or a link is
 * ignored: only a real file shows the box. What happens next is up to whichever
 * panel registered itself with `useFileTarget`; the box says which one that is.
 *
 * Pasting is handled here too, for everywhere that does not take the paste
 * itself: a Windows snip (Win+Shift+S) is a picture on the clipboard, so
 * Ctrl+V anywhere in Nyx sends it the same way a drop would.
 */

import { useEffect, useState } from "react";
import { currentTargetLabel, deliverFiles, filesFromClipboard, pasteWasHandled } from "./fileIntake";
import "./filedrop.css";

function draggingFiles(event: DragEvent): boolean {
  const types = event.dataTransfer?.types;
  if (!types) return false;
  return Array.from(types).includes("Files");
}

export function FileDropOverlay() {
  const [over, setOver] = useState(false);
  const [count, setCount] = useState(0);
  const [label, setLabel] = useState("the chat");
  const [note, setNote] = useState("");

  useEffect(() => {
    let depth = 0;

    const onEnter = (event: DragEvent) => {
      if (!draggingFiles(event)) return;
      depth += 1;
      setCount(event.dataTransfer?.items?.length ?? 0);
      setLabel(currentTargetLabel());
      setOver(true);
    };
    const onOver = (event: DragEvent) => {
      if (!draggingFiles(event)) return;
      event.preventDefault();                       // without this the browser opens the file itself
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    };
    const onLeave = (event: DragEvent) => {
      if (!draggingFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setOver(false);
    };
    const onDrop = (event: DragEvent) => {
      if (!draggingFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setOver(false);
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length) deliverFiles(files, "drop");
    };
    const onPaste = (event: ClipboardEvent) => {
      if (pasteWasHandled(event)) return;           // the composer already took it
      const target = event.target as HTMLElement | null;
      const files = filesFromClipboard(event.clipboardData);
      if (!files.length) return;
      // A picture pasted into a text box that handles its own pastes is not ours.
      if (target?.closest?.("[data-nyx-paste]")) return;
      event.preventDefault();
      deliverFiles(files, "paste");
      setNote(files.length === 1 ? `Added ${files[0].name} to ${currentTargetLabel()}` : `Added ${files.length} files`);
      window.setTimeout(() => setNote(""), 2600);
    };

    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragover", onOver);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDrop);
    window.addEventListener("paste", onPaste as EventListener);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDrop);
      window.removeEventListener("paste", onPaste as EventListener);
    };
  }, []);

  return (
    <>
      {over && (
        <div className="filedrop" role="presentation">
          <div className="filedrop__box">
            <svg viewBox="0 0 48 48" width="44" height="44" fill="none" stroke="currentColor" strokeWidth="2"
                 strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M24 32V10m0 0-8 8m8-8 8 8" />
              <path d="M8 30v6a4 4 0 0 0 4 4h24a4 4 0 0 0 4-4v-6" />
            </svg>
            <div className="filedrop__title">Drop {count > 1 ? `${count} files` : "the file"} here</div>
            <div className="filedrop__sub">It goes to {label} — Nyx checks it before it keeps it</div>
          </div>
        </div>
      )}
      {note && <div className="filedrop__note" role="status" aria-live="polite">{note}</div>}
    </>
  );
}
