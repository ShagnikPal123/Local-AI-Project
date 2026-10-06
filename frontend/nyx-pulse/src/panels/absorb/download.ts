/** Save a file from an authenticated route: a plain link cannot carry the session header once the install is claimed. */

import { authHeaders } from "../../api";

export async function downloadFrom(path: string, fallbackName: string): Promise<string | null> {
  try {
    const response = await fetch(path, { headers: authHeaders() });
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      return (detail && typeof detail.detail === "string" ? detail.detail : `${response.status}`) || "Download failed";
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
