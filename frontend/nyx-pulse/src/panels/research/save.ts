/** Save an export to disk. A plain link cannot carry the session header once the install is claimed. */

import { authHeaders } from "../../api";

export async function saveFrom(path: string, fallbackName: string): Promise<string | null> {
  try {
    const response = await fetch(path, { headers: authHeaders() });
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      return (detail && typeof detail.detail === "string" ? detail.detail : `Export failed (${response.status})`);
    }
    const disposition = response.headers.get("content-disposition") ?? "";
    const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? fallbackName;
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    return null;
  } catch {
    return "Cannot reach the local backend";
  }
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
