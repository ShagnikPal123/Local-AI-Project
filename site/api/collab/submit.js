// POST /api/collab/submit — a tester sends a change (→ pull request) or feedback (→ issue). Never merges anything.
import { CollabError, githubConfig, readJson, send, submitChange, validateSubmission, verifyKey } from "../_lib/collab.js";

export default async function handler(req, res) {
  if (req.method !== "POST") return send(res, 405, { error: "Use POST." });
  try {
    const body = await readJson(req);
    const tester = verifyKey(body.key);
    const change = validateSubmission(body);
    const result = await submitChange(githubConfig(), tester, change);
    return send(res, 200, { ok: true, tester: tester.name, ...result }, { "Cache-Control": "no-store" });
  } catch (error) {
    const status = error instanceof CollabError ? error.status : 500;
    return send(res, status, { ok: false, error: error instanceof CollabError ? error.message : "Could not send it — try again." },
      { "Cache-Control": "no-store" });
  }
}
