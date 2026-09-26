// POST /api/collab/verify — "Signed in as …" for the send form. The key is checked, never stored.
import { CollabError, readJson, send, verifyKey } from "../_lib/collab.js";

export default async function handler(req, res) {
  if (req.method !== "POST") return send(res, 405, { error: "Use POST." });
  try {
    const tester = verifyKey((await readJson(req)).key);
    return send(res, 200, { ok: true, name: tester.name, role: tester.role, id: tester.id }, { "Cache-Control": "no-store" });
  } catch (error) {
    const status = error instanceof CollabError ? error.status : 500;
    return send(res, status, { ok: false, error: error instanceof CollabError ? error.message : "Could not check the key." },
      { "Cache-Control": "no-store" });
  }
}
