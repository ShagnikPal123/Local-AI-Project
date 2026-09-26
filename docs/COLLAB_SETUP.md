# Collab — turning on the beta testers' collaboration site

Request K (2026-09-16). Everything is built and tested locally; these are the owner-only steps that connect it to
GitHub and put it online. Nothing here happens automatically.

## What it is

- **Website:** `https://nyx-ichos.vercel.app/collab/` (`site/collab/index.html`). Live list of every change and piece
  of feedback testers sent (refreshes itself every 30 s), plus a form to send files or feedback with an access key.
- **Functions:** `site/api/collab/feed.js`, `submit.js`, `verify.js` (shared code in `site/api/_lib/collab.js`).
  A change becomes a branch `beta/<tester>/<title>-<id>` and a pull request labelled `beta-change` (+ `beta-code`,
  `beta-tab`…); feedback becomes an issue labelled `beta-feedback`. **Nothing is ever merged by the site** — you review
  and merge on GitHub.
- **In Nyx:** the Collab tab (`panels/CollabPanel.tsx`, `beta_collab.py`, `/api/collab/*`). Testers tick what they
  changed (code Nyx applied, tabs, skills, agents), see exactly which files leave the PC and that no secret is inside,
  and press Send. The same live list shows on the right.

## Safety built in

- Testers are identified by their **Nyx access key** (the `NYX1-…` keys you mint in the admin console). The site only
  has the **public** half of your signing key; it can check keys but never make them.
- Paths must be relative files inside the project; `.env*`, `.secrets.json`, chats, memory, auth, uploads, logs, brain
  data and anything named like a secret are refused. 30 files, 300 KB each, 2 MB total.
- A secret scan (the same patterns `build_release.py` uses, plus GitHub tokens and access keys) runs in Nyx before
  sending and again on the site.
- At most 10 submissions per tester per hour.
- The GitHub token lives only in Vercel's environment variables.

## Steps (about 10 minutes)

1. **Make a GitHub token** — github.com → Settings → Developer settings → Fine-grained tokens → Generate:
   repository access *Only select repositories* → `ShagnikPal123/Local-AI-Project`; permissions **Contents: Read and
   write**, **Pull requests: Read and write**, **Issues: Read and write**. Copy it.
2. **Protect `main`** (recommended) — repo → Settings → Branches → add a rule for `main`: require a pull request before
   merging. Testers' branches then can never reach `main` without you.
3. **Public keys for the site** — in the project folder run:
   `.venv\Scripts\python.exe beta_collab.py --vercel-env`
   It prints `NYX_ACCESS_PUBLIC_KEYS=…` (public keys only). If it prints `{}`, mint your first access key in the admin
   console first — that creates the signing key.
4. **Vercel** → the `nyx-ichos` project → Settings → Environment Variables → add:
   - `GITHUB_TOKEN` = the token from step 1
   - `NYX_ACCESS_PUBLIC_KEYS` = the value from step 3
   - optional: `GITHUB_REPO` (default `ShagnikPal123/Local-AI-Project`), `GITHUB_BASE` (default `main`),
     `NYX_REVOKED_KEY_IDS` (comma-separated key ids you revoked)
5. **Deploy** the `site/` folder as usual (the functions deploy with it; `site/package.json` marks them as ES modules).
   First delete the `beta/`, `collab/`, `api/` and `package.json` lines from `site/.vercelignore` — they keep these
   pages off the public site until this setup is done.
6. **Check** `https://nyx-ichos.vercel.app/collab/` — the counters load, and "Check Key" with a tester's key says
   "Signed in as …".

## Testing without GitHub

`site/api/_lib/collab.test.mjs` runs the functions against a fake GitHub:
`node --test site/api/_lib/collab.test.mjs` (also run by `tests/test_beta_collab.py`, which also proves a key signed
by Nyx's Python Ed25519 verifies in the site's Node code).
