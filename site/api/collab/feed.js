// GET /api/collab/feed — every change and piece of feedback, for the collaboration page (it refreshes itself).
import { CollabError, feed, githubConfig, send } from "../_lib/collab.js";

export default async function handler(req, res) {
  if (req.method !== "GET") return send(res, 405, { error: "Use GET." });
  try {
    const data = await feed(githubConfig());
    // A short shared cache: many open pages cost GitHub one call every 20 seconds, not one each.
    return send(res, 200, data, { "Cache-Control": "public, s-maxage=20, stale-while-revalidate=40" });
  } catch (error) {
    const status = error instanceof CollabError ? error.status : 500;
    return send(res, status, { error: error instanceof CollabError ? error.message : "The feed is unavailable right now." });
  }
}
