# Nyx Ichos Beta & Developer Program

Nyx Ichos is a local-first AI assistant that lives on your own machine, works with a team of
specialist agents, sees and controls your screen when you let it, and gets smarter the more
you shape it. It is still being built in the open, in real time. The Beta & Developer Program
is how a small group of people outside the owner get an early, honest look at it — not a
polished product demo, but the actual thing, warts included — in exchange for the feedback
that makes it better. If that sounds like your kind of software, there's a place for you here.

---

## The two tiers

### Beta Tester

For people who want to *use* Nyx early and tell us what breaks.

**Perks**
- Early access to new agents, skills, voices, and UI before general release
- A direct line to report bugs and request features — feedback that's actually read
- First look at the tab system, the visible computer-control cursor, and new design passes
- Optional credit as an early tester if you want it

**Expectations**
- Things will break. That's the point of testing early — please report it rather than quietly
  working around it
- No guaranteed response time — this is a small team, not a support desk
- Please don't treat beta builds as production-stable for anything you can't afford to lose

### Developer

For people who want to *build on* Nyx — new tabs, new skills, new agents, integrations.

**Perks**
- Everything in Beta, plus:
- Access to the Developer panel and the underlying API surface
- Full visibility into the agent roster, skill library, and tab specs, with room to extend them
- Early access to skill export formats so a skill you like works in Claude, ChatGPT, Gemini, or
  a coding agent, not just inside Nyx
- A closer collaboration channel for anything you want to see prioritized

**Expectations**
- Comfortable reading JSON/Markdown specs and, ideally, some code
- Report what you build and what you break with the same honesty asked of beta testers
- Respect the permission model — developer access is deeper access, not unrestricted access to
  other people's machines or data

---

## How to apply

Tell us a little about yourself and which tier you're after:

- What you'd use Nyx for
- Beta Tester or Developer
- Anything you'd want to build or test first

**Apply here:** _[owner to add — a short form link or a contact address goes here]_

Spots are limited early on so the feedback loop stays tight and personal. If you're not in the
first wave, you're not forgotten — the program grows as the app does.

---

## How access keys work

Approved applicants get a **signed access key** — a single string that proves your tier
without needing an account on someone else's server. Two ways to use one:

1. **Paste it in the app** — open the Access panel and redeem your key directly.
2. **One click** — open the link you were sent in the form `nyx://redeem?key=...` and Nyx
   redeems it automatically.

A key is tied to a role (Beta or Developer), may expire on a set date or never, and can be
revoked if it's misused — redeeming it never hands over a password or account, just unlocks
what that tier is meant to see. If a key stops working, it's expired or been revoked; reapply
through the same channel above.

---

## Feedback etiquette

Good feedback is the whole point of this program, so a few ground rules keep it useful:

- **One issue per report.** Three bugs in one message means two of them get lost.
- **Say what you did, what you expected, and what actually happened.** "It's broken" helps no
  one; "I asked it to send an email with no account configured and it said it sent one" does.
- **Screenshots and screen recordings are gold**, especially for anything visual or for the
  computer-control cursor.
- **Security or privacy issues go to the private channel, not a public one** — please flag
  those directly rather than posting reproduction steps where anyone can see them.
- **Blunt is fine, cruel isn't.** Tell us it's bad if it's bad — just tell us *why*.

---

## Developer resources (outline)

Full technical docs ship alongside the developer panel; this is the map of what's in them:

- **API** — the chat streaming contract (how a turn's status, thoughts, tool calls, and answer
  stream to a client), the tool registry and permission categories, and the system/computer/
  email/voice/access route groups.
- **Skills** — how a skill is structured (name, description, triggers, instructions), how the
  assistant searches and auto-attaches them, how temporary task skills get created and shown,
  and the export formats that turn a Nyx skill into a Claude `SKILL.md`, a ChatGPT/GPT
  instruction block, a Gemini Gem, an `AGENTS.md` section, or a plain portable prompt.
- **Agents** — the roster shape (goal, expertise, tools, skills, voice), how the Manager routes
  and delegates, and how to propose a new specialist.
- **Tab specs** — how a dynamic tab is defined, edited live, and rolled back, so you can build
  your own or extend an existing one.

---

## FAQ

**Is this free?**
Yes for beta and developer access. Nyx itself is built to run local models for free where
possible; the program doesn't add a paywall.

**Does anything I do get sent somewhere I don't expect?**
Nyx is local-first by design — it runs on your machine. Anything that needs the internet (web
search, a cloud model, sending an email) only happens for actions you actually asked for.

**What if my key expires or I lose it?**
Reapply through the same channel you used the first time. Keys can be reissued.

**Can access be revoked?**
Yes — if a key is shared publicly, abused, or misused, it can be revoked. This keeps the
program sustainable for everyone still in it.

**Is it safe to let Nyx control my computer or read my email?**
Every category of access (screen/mouse control, email, files, and so on) is opt-in and shown
plainly in the Permissions panel, defaulting to allowed but always visible and changeable —
nothing happens silently, and you can turn any category off at any time.

**What's the real difference between Beta and Developer?**
Beta is about using Nyx and telling us what breaks. Developer is about building on top of it —
new skills, tabs, or integrations — and needs a bit more technical comfort as a result. Most
developers are also, happily, beta testers.
