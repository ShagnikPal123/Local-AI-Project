/** One way into Nyx for a file, however it arrives.
 *
 * The owner: "for files I want a way to drag and drop it so even if I don't
 * click on it I can drag it, the site ids that it's a file, then pulls up the
 * file drop box" and "Allow for copy paste of pictures where it uploads as a
 * file though shows the picture so the user knows which one it is."
 *
 * So dragging anywhere in the window, pasting a picture (including a Windows
 * snip), and the paperclip button all end in the same place: the tab that is
 * open takes the file, or the chat takes it when the open tab has no use for
 * files. Uploading goes through `/api/uploads`, which runs the malicious-file
 * checks before anything is written, and the verdict comes back with the
 * record so callers can show it.
 *
 * Other panels use `useFileTarget` to say "files dropped while I'm on screen
 * are mine"; the newest registered target wins, which matches what the eye
 * expects when a sheet opens over a tab.
 */

import { useEffect, useRef } from "react";
import { uploadFile, type UploadRecord } from "../api";

export type FileSource = "drop" | "paste" | "pick";
export type FileHandler = (files: File[], source: FileSource) => void;

export type FileTargetOptions = {
  /** Shown in the drop box: "Drop files for Data Absorption". */
  label?: string;
  /** Extensions or mime prefixes this target wants, for the drop box wording. */
  accept?: string[];
  /** A target that is mounted but not visible can step aside. */
  enabled?: boolean;
};

type Target = { id: string; handler: FileHandler; options: FileTargetOptions; order: number };

const targets: Target[] = [];
let order = 0;

/** Files pasted or dropped go here. Returns the unregister function. */
export function registerFileTarget(id: string, handler: FileHandler, options: FileTargetOptions = {}): () => void {
  order += 1;
  const target: Target = { id, handler, options, order };
  targets.push(target);
  return () => {
    const at = targets.indexOf(target);
    if (at >= 0) targets.splice(at, 1);
  };
}

function activeTarget(): Target | null {
  const live = targets.filter((target) => target.options.enabled !== false);
  if (!live.length) return null;
  return live.reduce((best, target) => (target.order > best.order ? target : best));
}

/** What the drop box says files will go to right now. */
export function currentTargetLabel(): string {
  return activeTarget()?.options.label ?? "the chat";
}

/** Hand files to whichever part of the app is listening. */
export function deliverFiles(files: File[], source: FileSource): boolean {
  if (!files.length) return false;
  const target = activeTarget();
  if (!target) {
    // Nothing is mounted yet (the app is still starting): keep them for a moment.
    window.setTimeout(() => { activeTarget()?.handler(files, source); }, 300);
    return false;
  }
  target.handler(files, source);
  window.dispatchEvent(new CustomEvent("nyx:files", { detail: { files, source, target: target.id } }));
  return true;
}

/** React version of `registerFileTarget`. */
export function useFileTarget(id: string, handler: FileHandler, options: FileTargetOptions = {}): void {
  const latest = useRef(handler);
  latest.current = handler;
  const { label, enabled } = options;
  const accept = options.accept?.join(",") ?? "";
  useEffect(
    () => registerFileTarget(id, (files, source) => latest.current(files, source),
                             { label, enabled, accept: accept ? accept.split(",") : undefined }),
    [id, label, enabled, accept],
  );
}

/** Files pasted into one element (the composer's box, a note, a code editor). */
export function usePasteFiles(
  ref: { current: HTMLElement | null },
  handler: (files: File[]) => void,
  options: { enabled?: boolean } = {},
): void {
  const latest = useRef(handler);
  latest.current = handler;
  useEffect(() => {
    const element = ref.current;
    if (!element || options.enabled === false) return;
    const onPaste = (event: ClipboardEvent) => {
      const files = filesFromClipboard(event.clipboardData);
      if (!files.length) return;
      event.preventDefault();                       // the picture must not also land as text
      markHandled(event);
      latest.current(files);
    };
    element.addEventListener("paste", onPaste as EventListener);
    return () => element.removeEventListener("paste", onPaste as EventListener);
  }, [ref, options.enabled]);
}

const handledPastes = new WeakSet<ClipboardEvent>();

function markHandled(event: ClipboardEvent): void {
  handledPastes.add(event);
}

export function pasteWasHandled(event: ClipboardEvent): boolean {
  return handledPastes.has(event);
}

/** Pictures and files on the clipboard, named so the owner can tell them apart. */
export function filesFromClipboard(data: DataTransfer | null): File[] {
  if (!data) return [];
  const files: File[] = [];
  for (const item of Array.from(data.items ?? [])) {
    if (item.kind !== "file") continue;
    const file = item.getAsFile();
    if (!file) continue;
    files.push(namedForClipboard(file));
  }
  if (!files.length) for (const file of Array.from(data.files ?? [])) files.push(namedForClipboard(file));
  return files;
}

/** A snip arrives as "image.png"; a name with the time in it is easier to tell apart. */
function namedForClipboard(file: File): File {
  const generic = !file.name || /^(image|screenshot|clipboard)\.(png|jpe?g|webp|gif)$/i.test(file.name);
  if (!generic) return file;
  const now = new Date();
  const two = (value: number) => String(value).padStart(2, "0");
  const stamp = `${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}-${two(now.getHours())}${two(now.getMinutes())}${two(now.getSeconds())}`;
  const extension = (file.type.split("/")[1] || "png").replace("jpeg", "jpg");
  return new File([file], `snip-${stamp}.${extension}`, { type: file.type || "image/png" });
}

export type CheckedUpload = {
  ok: boolean;
  record?: UploadRecord & { security?: { level: string; message?: string; reasons?: string[]; cautions?: string[] } };
  /** Set when the file was refused — the words come from the checks. */
  error?: string;
  /** Set when it was accepted with something worth saying. */
  caution?: string;
};

/** Upload one file and turn the checks' verdict into something a panel can show. */
export async function uploadChecked(file: File): Promise<CheckedUpload> {
  const result = await uploadFile(file);
  if (!result.ok) return { ok: false, error: result.error };
  const record = result.data as CheckedUpload["record"];
  const security = record?.security;
  const caution = security && security.level !== "clean"
    ? security.message || [...(security.reasons ?? []), ...(security.cautions ?? [])].join(" ")
    : undefined;
  return { ok: true, record, caution };
}

/** A picture to show in a chip before the upload finishes. */
export function previewUrl(file: File): string | undefined {
  return file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined;
}
