// Nyx Ichos Collab — the server half of the beta testers' collaboration site (Request K, 2026-09-16).
//
// The owner: "a second website for beta testers where they can apply changes to github, have a special page for
// collaboration where they send and show all changes and it auto uploads those changes to that tab."
//
// The repository is private, so a static page cannot read or write it. These Vercel functions hold the owner's
// GitHub token (an environment variable, never in a file) and do exactly three things:
//   • verify a tester's Nyx access key (the same Ed25519 keys Nyx verifies offline — only public keys live here);
//   • turn a tester's change into a branch `beta/<tester>/<slug>-<id>` and a pull request labelled `beta-change`
//     (feedback without files becomes an issue labelled `beta-feedback`). Nothing is ever merged here — the owner
//     reviews and merges on GitHub;
//   • list every change and piece of feedback for the collaboration page, which refreshes itself.
// Files are checked before anything reaches GitHub: safe relative paths only, no personal data or secrets files,
// size limits, and a secret scan with the same patterns build_release.py uses.
//
// Environment (set by the owner in Vercel → Settings → Environment Variables):
//   GITHUB_TOKEN              fine-grained token for the repo: Contents, Pull requests and Issues read/write
//   GITHUB_REPO               owner/name (default ShagnikPal123/Local-AI-Project)
//   GITHUB_BASE               branch pull requests target (default main)
//   NYX_ACCESS_PUBLIC_KEYS    JSON {"kid": "hex public key"} — print it with: python beta_collab.py --vercel-env
//   NYX_REVOKED_KEY_IDS       comma-separated key ids that may no longer send changes

import crypto from "node:crypto";

export const LIMITS = { files: 30, fileBytes: 300_000, totalBytes: 2_000_000, title: 120, description: 6000, perHour: 10 };
export const KINDS = ["code", "tab", "skill", "agent", "design", "feedback"];
const KEY_PREFIX = "NYX1-";
const SPKI_ED25519 = Buffer.from("302a300506032b6570032100", "hex");

const DENY_PATH = [
  /(^|\/)\.env(\.|$)/i, /(^|\/)\.secrets\.json$/i, /(^|\/)\.git(\/|$)/i, /(^|\/)node_modules(\/|$)/i, /(^|\/)\.venv(\/|$)/i,
  /(^|\/)(chats|memory|auth|internal_chats|client_state|device_profile|engine|model_choice)\.json$/i,
  /(^|\/)(profiles|uploads|brain|learning|logs|tts_cache|voice_tmp|attachments|checkpoints|code_backups|autopilot|notes|trading|data)(\/|$)/i,
  /secret/i, /(^|\/)id_(rsa|ed25519)/i, /\.(pem|key|pfx|p12|sqlite|db)$/i, /(^|\/)dist(\/|$)/i,
  // A change to CI or editor config runs on the owner's machines with their
  // secrets, before anybody has read the diff.
  /(^|\/)\.github(\/|$)/i, /(^|\/)\.vscode(\/|$)/i, /(^|\/)\.claude(\/|$)/i, /(^|\/)\.husky(\/|$)/i,
  // Nothing runnable or opaque: a change is text a person can read in the PR.
  /\.(exe|dll|msi|scr|com|pif|cpl|jar|lnk|iso|img|apk|dmg|pkg|so|dylib|bin|pyc|whl|zip|7z|rar|gz)$/i,
];

//: The shapes malware takes in a source file. Matched in what a tester sends,
//: so a change that would run commands on the owner's PC never reaches a PR.
const MALICIOUS = [
  [/powershell(?:\.exe)?[^\n]{0,80}\s-(?:e|en|enc|encodedcommand)\s+[A-Za-z0-9+/=]{40,}/i, "a PowerShell command hidden in base64"],
  [/(?:iex|invoke-expression)[^\n]{0,60}(?:downloadstring|downloadfile|net\.webclient|invoke-webrequest)/i, "code downloaded from the web and run"],
  [/(?:curl|wget)\s+[^\n|;]{4,200}\|\s*(?:sudo\s+)?(?:ba|z|d)?sh\b/i, "a download piped straight into a shell"],
  [/child_process[\s\S]{0,160}(?:exec|execSync|spawn)\s*\([^)]{0,120}(?:https?:|\$\{|atob\(|Buffer\.from\()/i, "a shell command built at runtime"],
  [/(?:eval|new Function)\s*\(\s*(?:atob|decodeURIComponent|unescape|Buffer\.from)\s*\(/i, "hidden code that is decoded and run"],
  [/(?:eval|exec)\s*\(\s*(?:base64\.b64decode|bytes\.fromhex|codecs\.decode)\s*\(/i, "hidden code that is decoded and run"],
  [/__import__\s*\(\s*['"]os['"]\s*\)\s*\.(?:system|popen)/i, "a hidden shell call"],
  [/(?:ba)?sh\s+-i\s*>&\s*\/dev\/tcp\//i, "a reverse shell"],
  [/\bnc(?:at)?\s+-[a-z]{0,3}e\s+\/bin\/(?:ba)?sh/i, "a reverse shell"],
  [/vssadmin(?:\.exe)?\s+delete\s+shadows|wbadmin(?:\.exe)?\s+delete\s+catalog/i, "deletion of Windows backups"],
  [/\brm\s+-rf\s+(?:\/|~|\$HOME|\*)(?:\s|$)/i, "deletion of a whole drive or home folder"],
  [/stratum\+(?:tcp|ssl):\/\/|\bxmrig\b|\bminerd\b/i, "a cryptocurrency miner"],
  [/process\.env[\s\S]{0,200}(?:fetch|axios|https?\.request)\s*\(|(?:fetch|axios|https?\.request)\s*\([\s\S]{0,200}process\.env/i,
    "environment variables sent to a web address"],
  [/os\.environ[\s\S]{0,200}requests\.(?:post|put|get)\s*\(|requests\.(?:post|put|get)\s*\([\s\S]{0,200}os\.environ/i,
    "environment variables sent to a web address"],
  [/\bTVqQAAMAAAAE|\bTVpQAAIAAAAE/, "a Windows program encoded in base64"],
  [/\bmimikatz\b|sekurlsa::logonpasswords/i, "a password-stealing tool"],
  [/EICAR-STANDARD-ANTIVIRUS-TEST-FILE/, "the anti-virus test signature"],
];
//: Right-to-left overrides and invisible characters: code that reads one way
//: and runs another ("Trojan Source").
const HIDDEN_CHARS = /[‪-‮⁦-⁩​-‏⁠]/;
const INSTALL_HOOK = /"(?:pre|post)?install"\s*:/;

const SECRET_ASSIGN = /(?:API_KEY|SECRET|TOKEN|PASSWORD)\s*[=:]\s*['"]?([A-Za-z0-9_\-.]{20,})/g;
const RAW_TOKENS = [
  /AIza[0-9A-Za-z_\-]{30,}/g, /\bAQ\.[0-9A-Za-z_\-]{20,}/g, /\bsk-(?:proj-)?[0-9A-Za-z_\-]{20,}/g, /\bsk-ant-[0-9A-Za-z_\-]{20,}/g,
  /\bnvapi-[0-9A-Za-z_\-]{20,}/g, /\bgsk_[0-9A-Za-z]{20,}/g, /\bghp_[0-9A-Za-z]{30,}/g, /\bgithub_pat_[0-9A-Za-z_]{30,}/g,
  /\b[0-9a-f]{48,}\b/g, /NYX1-[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}/g,
];
const PLACEHOLDER = /^(x+|your|example|placeholder|changeme|replace|dummy|test)/i;

export class CollabError extends Error {
  constructor(message, status = 400) { super(message); this.status = status; }
}

function b64u(text) {
  return Buffer.from(String(text).replace(/-/g, "+").replace(/_/g, "/"), "base64");
}

export function publicKeys(env = process.env) {
  try { return JSON.parse(env.NYX_ACCESS_PUBLIC_KEYS || "{}"); } catch { return {}; }
}

/** The tester behind a Nyx access key, or a CollabError saying why not. */
export function verifyKey(key, env = process.env, now = Date.now() / 1000) {
  const text = String(key || "").trim();
  if (!text.startsWith(KEY_PREFIX)) throw new CollabError("Paste your Nyx access key (it starts with NYX1-).", 401);
  const parts = text.slice(KEY_PREFIX.length).split(".");
  if (parts.length !== 2 || !parts[0] || !parts[1]) throw new CollabError("That access key is malformed.", 401);
  let payloadBytes, payload;
  try {
    payloadBytes = b64u(parts[0]);
    payload = JSON.parse(payloadBytes.toString("utf8"));
  } catch { throw new CollabError("That access key is malformed.", 401); }
  if (!payload || !payload.kid || !payload.id) throw new CollabError("That access key is malformed.", 401);
  const hex = publicKeys(env)[payload.kid];
  if (!hex) throw new CollabError("This key was signed by a key this site doesn't know yet — ask the owner.", 401);
  const publicKey = crypto.createPublicKey({ key: Buffer.concat([SPKI_ED25519, Buffer.from(hex, "hex")]), format: "der", type: "spki" });
  if (!crypto.verify(null, payloadBytes, publicKey, b64u(parts[1]))) throw new CollabError("This key's signature doesn't match.", 401);
  if (payload.exp && now > payload.exp) throw new CollabError("This access key has expired.", 401);
  const revoked = String(env.NYX_REVOKED_KEY_IDS || "").split(",").map((s) => s.trim()).filter(Boolean);
  if (revoked.includes(String(payload.id))) throw new CollabError("This access key has been revoked.", 401);
  return { id: String(payload.id), name: String(payload.name || "Tester").slice(0, 80), role: String(payload.role || "beta") };
}

export function safePath(path) {
  const clean = String(path || "").replace(/\\/g, "/").replace(/^\.\//, "").trim();
  if (!clean || clean.startsWith("/") || /^[a-z]:/i.test(clean) || clean.split("/").some((p) => p === ".." || p === "")) {
    throw new CollabError(`"${String(path).slice(0, 80)}" isn't a path inside the project.`);
  }
  if (clean.length > 200) throw new CollabError("A file path is too long.");
  if (DENY_PATH.some((re) => re.test(clean))) throw new CollabError(`${clean} can't be shared: it's personal data or a secrets file.`);
  return clean;
}

export function scanSecrets(files) {
  const findings = [];
  for (const file of files) {
    const text = String(file.content || "");
    for (const match of text.matchAll(SECRET_ASSIGN)) {
      const value = match[1];
      if (value === value.toUpperCase() || PLACEHOLDER.test(value) || (value.includes("_") && value === value.toLowerCase())) continue;
      findings.push(`${file.path}: …${value.slice(-4)}`);
    }
    for (const pattern of RAW_TOKENS) {
      for (const match of text.matchAll(pattern)) {
        if (PLACEHOLDER.test(match[0])) continue;
        findings.push(`${file.path}: a token (…${match[0].slice(-4)})`);
      }
    }
  }
  return findings;
}

/** Anything in a tester's files that would run on somebody else's machine. */
export function scanMalicious(files) {
  const findings = [];
  for (const file of files) {
    const text = String(file.content || "");
    for (const [pattern, label] of MALICIOUS) {
      if (pattern.test(text)) findings.push(`${file.path}: ${label}`);
    }
    if (HIDDEN_CHARS.test(text)) findings.push(`${file.path}: invisible characters that hide what the code does`);
    if (/(^|\/)package(-lock)?\.json$/i.test(file.path) && INSTALL_HOOK.test(text)) {
      findings.push(`${file.path}: an install script that runs on npm install`);
    }
  }
  return [...new Set(findings)];
}

/** Everything a submission must satisfy before GitHub is touched. */
export function validateSubmission(body) {
  const title = String(body?.title || "").trim();
  const description = String(body?.description || "").trim();
  const kind = KINDS.includes(body?.kind) ? body.kind : "code";
  if (title.length < 4) throw new CollabError("Give the change a title (4+ characters).");
  if (title.length > LIMITS.title) throw new CollabError(`Keep the title under ${LIMITS.title} characters.`);
  if (description.length > LIMITS.description) throw new CollabError("The description is too long.");
  const rawFiles = Array.isArray(body?.files) ? body.files : [];
  if (kind !== "feedback" && rawFiles.length === 0) throw new CollabError("Add at least one file, or send it as feedback.");
  if (rawFiles.length > LIMITS.files) throw new CollabError(`At most ${LIMITS.files} files in one change.`);
  let total = 0;
  const seen = new Set();
  const files = rawFiles.map((file) => {
    const path = safePath(file?.path);
    if (seen.has(path)) throw new CollabError(`${path} is listed twice.`);
    seen.add(path);
    const content = String(file?.content ?? "");
    const bytes = Buffer.byteLength(content, "utf8");
    if (bytes > LIMITS.fileBytes) throw new CollabError(`${path} is larger than ${LIMITS.fileBytes / 1000} KB.`);
    total += bytes;
    return { path, content };
  });
  if (total > LIMITS.totalBytes) throw new CollabError("The change is too large in total.");
  const secrets = scanSecrets(files);
  if (secrets.length) throw new CollabError(`Not sent — it looks like a secret is inside: ${secrets.slice(0, 3).join("; ")}. Remove it first.`);
  const dangerous = scanMalicious(files);
  if (dangerous.length) {
    throw new CollabError(
      `Not sent — this change contains ${dangerous.slice(0, 3).join("; ")}. Nyx's owner reviews every change by hand, ` +
      `so anything that runs commands is refused here. If it is a false alarm, describe what you are trying to do and ask first.`,
    );
  }
  return { title, description, kind, files };
}

export function slug(text, max = 40) {
  return String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, max) || "change";
}

const META = /<!--\s*nyx-collab\s+(\{.*?\})\s*-->/s;

export function metaBlock(meta) {
  return `<!-- nyx-collab ${JSON.stringify(meta)} -->`;
}

export function readMeta(body) {
  const match = META.exec(String(body || ""));
  if (!match) return null;
  try { return JSON.parse(match[1]); } catch { return null; }
}

// --- GitHub ------------------------------------------------------------------------------------------

export function githubConfig(env = process.env) {
  const token = env.GITHUB_TOKEN || "";
  if (!token) throw new CollabError("The site isn't connected to GitHub yet (the owner adds GITHUB_TOKEN in Vercel).", 503);
  return { token, repo: env.GITHUB_REPO || "ShagnikPal123/Local-AI-Project", base: env.GITHUB_BASE || "main" };
}

export async function gh(config, path, options = {}, fetchImpl = globalThis.fetch) {
  const response = await fetchImpl(`https://api.github.com${path}`, {
    ...options,
    headers: {
      Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "nyx-ichos-collab",
      Authorization: `Bearer ${config.token}`, ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { message: text.slice(0, 200) }; }
  if (!response.ok) {
    const message = (data && data.message) || `GitHub answered ${response.status}`;
    throw new CollabError(`GitHub: ${String(message).replace(config.token, "…")}`, response.status === 404 ? 502 : response.status);
  }
  return data;
}

async function ensureLabel(config, name, color, description, fetchImpl) {
  try {
    await gh(config, `/repos/${config.repo}/labels`, { method: "POST", body: JSON.stringify({ name, color, description }) }, fetchImpl);
  } catch (error) {
    if (!(error instanceof CollabError) || (error.status !== 422 && error.status !== 400)) throw error; // 422: already exists
  }
}

export async function recentCount(config, tester, fetchImpl) {
  const since = new Date(Date.now() - 3600_000).toISOString().slice(0, 19);
  const query = encodeURIComponent(`repo:${config.repo} "key:${tester.id}" created:>${since}`);
  const data = await gh(config, `/search/issues?q=${query}&per_page=1`, {}, fetchImpl);
  return Number(data?.total_count || 0);
}

/** A tester's change → branch + commit + pull request (or an issue for feedback). */
export async function submitChange(config, tester, change, fetchImpl = globalThis.fetch, now = new Date()) {
  if (await recentCount(config, tester, fetchImpl) >= LIMITS.perHour) {
    throw new CollabError(`You've sent ${LIMITS.perHour} changes in the last hour — try again a little later.`, 429);
  }
  const shortId = crypto.randomBytes(3).toString("hex");
  const meta = { tester: tester.name, key: tester.id, kind: change.kind, files: change.files.map((f) => f.path), sent: now.toISOString() };
  const body = `${change.description || "_No description._"}\n\n---\nSent by **${tester.name}** from Nyx Ichos Collab · ${change.kind}` +
    ` · key:${tester.id}\n\n${metaBlock(meta)}`;
  if (change.kind === "feedback" && change.files.length === 0) {
    await ensureLabel(config, "beta-feedback", "8b7cff", "Feedback from beta testers", fetchImpl);
    const issue = await gh(config, `/repos/${config.repo}/issues`, {
      method: "POST", body: JSON.stringify({ title: change.title, body, labels: ["beta-feedback"] }),
    }, fetchImpl);
    return { kind: "feedback", number: issue.number, url: issue.html_url };
  }
  const ref = await gh(config, `/repos/${config.repo}/git/ref/heads/${encodeURIComponent(config.base)}`, {}, fetchImpl);
  const baseSha = ref.object.sha;
  const baseCommit = await gh(config, `/repos/${config.repo}/git/commits/${baseSha}`, {}, fetchImpl);
  const tree = [];
  for (const file of change.files) {
    const blob = await gh(config, `/repos/${config.repo}/git/blobs`, {
      method: "POST", body: JSON.stringify({ content: Buffer.from(file.content, "utf8").toString("base64"), encoding: "base64" }),
    }, fetchImpl);
    tree.push({ path: file.path, mode: "100644", type: "blob", sha: blob.sha });
  }
  const newTree = await gh(config, `/repos/${config.repo}/git/trees`, {
    method: "POST", body: JSON.stringify({ base_tree: baseCommit.tree.sha, tree }),
  }, fetchImpl);
  const commit = await gh(config, `/repos/${config.repo}/git/commits`, {
    method: "POST",
    body: JSON.stringify({ message: `${change.title}\n\nBeta change from ${tester.name} (Nyx Ichos Collab).`, tree: newTree.sha, parents: [baseSha] }),
  }, fetchImpl);
  const branch = `beta/${slug(tester.name, 24)}/${slug(change.title)}-${shortId}`;
  await gh(config, `/repos/${config.repo}/git/refs`, { method: "POST", body: JSON.stringify({ ref: `refs/heads/${branch}`, sha: commit.sha }) }, fetchImpl);
  const pull = await gh(config, `/repos/${config.repo}/pulls`, {
    method: "POST", body: JSON.stringify({ title: change.title, head: branch, base: config.base, body, maintainer_can_modify: true }),
  }, fetchImpl);
  await ensureLabel(config, "beta-change", "30d158", "A change sent by a beta tester", fetchImpl);
  await gh(config, `/repos/${config.repo}/issues/${pull.number}/labels`, { method: "POST", body: JSON.stringify({ labels: ["beta-change", `beta-${change.kind}`] }) }, fetchImpl);
  return { kind: "change", number: pull.number, url: pull.html_url, branch };
}

function strip(body) {
  return String(body || "").replace(META, "").replace(/\n---\nSent by[\s\S]*$/, "").trim().slice(0, 600);
}

/** Every change and piece of feedback, newest first, as the collaboration page shows them. */
export async function feed(config, fetchImpl = globalThis.fetch) {
  const [pulls, issues] = await Promise.all([
    gh(config, `/repos/${config.repo}/pulls?state=all&per_page=60&sort=created&direction=desc`, {}, fetchImpl),
    gh(config, `/repos/${config.repo}/issues?state=all&labels=beta-feedback&per_page=40&sort=created&direction=desc`, {}, fetchImpl),
  ]);
  const items = [];
  for (const pull of pulls || []) {
    const meta = readMeta(pull.body);
    const labelled = (pull.labels || []).some((l) => l.name === "beta-change");
    if (!meta && !labelled) continue;
    items.push({
      id: `pr-${pull.number}`, number: pull.number, kind: meta?.kind || "code", title: pull.title,
      tester: meta?.tester || pull.user?.login || "tester", summary: strip(pull.body), files: meta?.files || [],
      status: pull.merged_at ? "merged" : pull.state, created_at: pull.created_at, updated_at: pull.updated_at, url: pull.html_url,
      branch: pull.head?.ref || "",
    });
  }
  for (const issue of issues || []) {
    if (issue.pull_request) continue;
    const meta = readMeta(issue.body);
    items.push({
      id: `issue-${issue.number}`, number: issue.number, kind: "feedback", title: issue.title, tester: meta?.tester || issue.user?.login || "tester",
      summary: strip(issue.body), files: [], status: issue.state, created_at: issue.created_at, updated_at: issue.updated_at,
      url: issue.html_url, comments: issue.comments || 0,
    });
  }
  items.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  const counts = { total: items.length, open: 0, merged: 0, closed: 0, feedback: 0 };
  for (const item of items) {
    if (item.kind === "feedback") counts.feedback += 1;
    counts[item.status] = (counts[item.status] || 0) + 1;
  }
  return { items, counts, repo: config.repo, at: new Date().toISOString() };
}

export async function readJson(req) {
  if (req.body && typeof req.body === "object") return req.body;
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > LIMITS.totalBytes * 2) throw new CollabError("The request is too large.", 413);
    chunks.push(chunk);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}"); } catch { throw new CollabError("Send JSON."); }
}

export function send(res, status, data, headers = {}) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  for (const [k, v] of Object.entries(headers)) res.setHeader(k, v);
  res.end(JSON.stringify(data));
}
