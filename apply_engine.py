"""The Apply tab (Request R16): tell Nyx what to change about itself, with files, pictures and links; it plans the
change, shows every part, and applies a part only when the owner presses Apply on it.

The owner: "Add a apply tab and in this it is basically just a way to prompt the ai and also upload field, pictures m,
and such so that the ai then follows it and applies to itself. In this tab what happens is basically improving the ai
in changing its code, adding tabs, and more. Similar to vibe coding which I am doing now. It can use images to
understand ui format. It uses apple and normal design skills together. Can search. and more."

How one request travels:

1. **Read** what came with it: documents as text, pictures through a vision model asked about their *layout*
   (regions, components, colours, spacing), links through the SSRF-safe reader Data Absorption uses.
2. **Design guidance** for anything visual: the topics of Apple's Human Interface Guidelines the request touches (the
   local HIG library), general design principles, and any design skill Nyx has. Optionally a web search.
3. **Plan** with the code model: at most five changes, each through one of Nyx's own reviewed paths — a tab (a
   validated spec: data, never code), a skill, an agent or more for an agent, a Python change (``self_patch``: sandbox
   tests, a critic on the real diff, rollback), or an interface change (a diff from the Code tab's editor).
4. **Nothing is applied by the plan.** Each change is a box and the owner's Apply is the approval. An interface edit is
   written only when applied and goes live after a rebuild, which is its own button.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from paths import PROJECT_DIR, data_path

_LOG = logging.getLogger("nyx.apply")

KINDS = ("tab", "code", "ui", "skill", "agent", "agent_feature")
MAX_CHANGES = 5
MAX_UPLOADS = 6
MAX_LINKS = 4
MAX_JOBS = 30
UI_SUFFIXES = (".tsx", ".ts", ".css")
_VISUAL = re.compile(r"(?i)\b(tab|ui|look|looks|design|layout|colou?rs?|buttons?|page|screen|panel|style|theme|font|"
                     r"icons?|image|picture|mock-?up|sidebar|header|card|dark|light|glass|spacing|animation)\b")

SYSTEM = ("You are Nyx planning a change to yourself for your owner, the way a careful senior engineer and product "
          "designer would. You change yourself only through the paths listed. Reply with JSON only.")

PICTURE_PROMPT = (
    "The owner attached this picture to a request to change an app's interface. Describe it for a developer who must "
    "reproduce it: the regions and where they sit (header, sidebar, panels, grid), every component with its label "
    "(buttons, lists, inputs, charts, cards), the visual style (dark or light, colours as hex where you can tell, "
    "corner radius, fonts, spacing and density), and anything notable. If it is not an interface, say what it shows "
    "and what in it matters for the request. Be concrete and short: at most 180 words.")

GENERAL_DESIGN = """General design principles (use them together with Apple's guidance):
- Hierarchy: one clear primary action per view; size, weight and position say what matters most.
- Consistency: reuse the app's own components, spacing and colours before inventing new ones.
- Spacing on a 4/8-point grid; group related things with space rather than lines.
- Contrast of at least 4.5:1 for text (3:1 for large text and controls); never rely on colour alone.
- Click targets at least 28x28 points (44x44 on touch); keyboard focus always visible.
- Plain words: buttons are title-case verbs, places are nouns; say what happened and what to do next.
- Motion is brief, purposeful, and off when the system asks for reduced motion.
- Empty, loading and error states are designed, never blank.
- Progressive disclosure: the essentials first, the rest one click away."""

WAYS = """Ways to change yourself (use only these):
1. "tab": a new tab made of blocks, stored as data and shown at once. Block types: {blocks}. Optional "accent"
   "#rrggbb", "theme" {{"surface": "solid|glass|clear", "font": "system|rounded|serif|mono", "text": "#rrggbb",
   "radius": 0-28}}, "background" {{"kind": "color", "value": "#rrggbb"}} or {{"kind": "gradient", "colors":
   ["#rrggbb", "#rrggbb"], "angle": 135}}. Connectors a tab may use: {connectors}.
2. "code": a change to ONE existing Python module of yours (the back end). Say exactly what to change. Nyx writes it,
   runs the tests in a sandbox, a reviewer reads the real diff, and only then is it applied; it can be rolled back.
3. "ui": a change to ONE existing interface file (TSX or CSS under frontend/nyx-pulse/src). Say exactly what to change;
   the owner sees the diff, applies it, and the app is rebuilt.
4. "skill": instructions you follow whenever a request matches ("name", "description", "instructions", "triggers").
5. "agent": a new specialist ("name", "goal", "expertise" list, "instructions").
6. "agent_feature": more for an existing agent ("agent", "add_expertise" list, "add_instructions")."""

REPLY = """Reply with JSON only:
{"understood": "what they asked, in one or two sentences",
 "summary": "what you will change and why, two or three sentences",
 "changes": [
   {"kind": "tab", "title": "short title", "why": "one sentence",
    "tab": {"label": "...", "icon": "ph-...", "description": "...", "blocks": [{"type": "...", "title": "...", "config": {}}]}},
   {"kind": "code", "title": "...", "why": "...", "target": "module.py", "description": "exactly what to change"},
   {"kind": "ui", "title": "...", "why": "...", "target": "panels/SomePanel.tsx", "description": "exactly what to change"},
   {"kind": "skill", "title": "...", "why": "...", "skill": {"name": "...", "description": "...", "instructions": "...", "triggers": ["..."]}},
   {"kind": "agent", "title": "...", "why": "...", "agent": {"name": "...", "goal": "...", "expertise": ["..."], "instructions": "..."}},
   {"kind": "agent_feature", "title": "...", "why": "...", "agent": "an existing agent's name", "add_expertise": ["..."], "add_instructions": "..."}
 ],
 "questions": []}
Rules: at most five changes, the smallest set that does what they asked. A tab or a skill is enough for many requests;
use "code" or "ui" only when your own behaviour or look must change. Follow the design guidance for anything visual.
Never touch permissions, secrets, sign-in or the review gate. Ask in "questions" only what you truly cannot decide."""


class ApplyError(RuntimeError):
    """Something the owner should read, as it is."""


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z0-9]{2,}", (text or "").lower())}


def _listy(value: Any, limit: int = 600) -> str:
    """Expertise may come as a list or as a sentence; the stores keep a comma-separated string."""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v).strip() for v in value if str(v).strip())
    return _clean(value, limit)


def excerpt(markdown: str, limit: int = 1400) -> str:
    """The readable start of a guideline: no front matter, no link noise, whitespace folded."""
    text = re.sub(r"^---.*?---\s*", "", markdown or "", flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:limit]


# ---------------------------------------------------------------------------
# Checking what the model planned
# ---------------------------------------------------------------------------


def vet_change(raw: Any, *, root: Path, ui_root: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    """(a change Nyx may offer, "") or (None, why it was left out)."""
    if not isinstance(raw, dict):
        return None, ""
    kind = _clean(raw.get("kind"), 20).lower()
    title = _clean(raw.get("title"), 120) or kind.replace("_", " ").title()
    why = _clean(raw.get("why"), 300)
    base = {"kind": kind, "title": title, "why": why, "status": "proposed"}
    if kind == "tab":
        from dynamic_tabs import TabSpecError, build_spec

        tab = raw.get("tab") if isinstance(raw.get("tab"), dict) else {}
        fields = {"label": _clean(tab.get("label"), 40), "blocks": tab.get("blocks") if isinstance(tab.get("blocks"), list) else [],
                  "icon": _clean(tab.get("icon"), 44) or "ph-squares-four", "description": _clean(tab.get("description"), 200),
                  "connectors": [str(c) for c in (tab.get("connectors") or []) if isinstance(c, str)][:5],
                  "accent": _clean(tab.get("accent"), 7), "theme": tab.get("theme") or None, "background": tab.get("background") or None}
        try:
            spec = build_spec(**fields, source="agent")
        except TabSpecError:
            # A bad colour, icon or connector should not cost the whole tab: drop the decoration and try once more.
            from dynamic_tabs import ALLOWED_CONNECTORS

            fields.update(icon="ph-squares-four", accent="", theme=None, background=None,
                          connectors=[c for c in fields["connectors"] if c in ALLOWED_CONNECTORS])
            try:
                spec = build_spec(**fields, source="agent")
            except TabSpecError as error:
                return None, f"The tab “{title}” was not usable: {error}"
        preview = spec.as_dict()
        return {**base, "tab": fields, "preview": {k: preview.get(k) for k in ("label", "icon", "description", "blocks",
                                                                                 "accent", "theme", "background")}}, ""
    if kind in ("code", "ui"):
        description = _clean(raw.get("description"), 2000)
        target = str(raw.get("target") or "").strip().strip("`'\"").replace("\\", "/")
        if not description or not target:
            return None, f"“{title}” did not say what to change or where."
        if kind == "ui" or target.endswith(UI_SUFFIXES):
            relative = re.sub(r"^(\./)?(frontend/nyx-pulse/)?(src/)?", "", target)
            path = (ui_root / relative).resolve()
            if not (path.is_file() and path.suffix in UI_SUFFIXES and path.is_relative_to(ui_root.resolve())):
                return None, f"Skipped “{title}”: {target} is not an interface file Nyx has."
            return {**base, "kind": "ui", "target": str(path.relative_to(ui_root.resolve())).replace("\\", "/"),
                    "description": description}, ""
        import self_patch

        try:
            path = self_patch.resolve_target(target, root)
        except self_patch.PatchError as error:
            return None, f"Skipped “{title}”: {error}"
        return {**base, "target": path.name, "path": str(path.relative_to(root)).replace("\\", "/"),
                "description": description}, ""
    if kind == "skill":
        spec = raw.get("skill") if isinstance(raw.get("skill"), dict) else {}
        name, instructions = _clean(spec.get("name") or title, 60), str(spec.get("instructions") or "").strip()[:6000]
        if not instructions:
            return None, f"The skill “{title}” had no instructions."
        triggers = spec.get("triggers") if isinstance(spec.get("triggers"), list) else str(spec.get("triggers") or "").split(",")
        return {**base, "spec": {"name": name, "description": _clean(spec.get("description") or why, 300),
                                 "instructions": instructions, "triggers": [_clean(t, 60) for t in triggers if _clean(t, 60)][:12]}}, ""
    if kind == "agent":
        spec = raw.get("agent") if isinstance(raw.get("agent"), dict) else {}
        name, goal = _clean(spec.get("name"), 40), _clean(spec.get("goal"), 300)
        if not name or not goal:
            return None, f"The agent “{title}” needs a name and a goal."
        return {**base, "spec": {"name": name, "goal": goal, "expertise": _listy(spec.get("expertise")),
                                 "instructions": str(spec.get("instructions") or "").strip()[:4000],
                                 "emoji": _clean(spec.get("emoji"), 4) or "🤖"}}, ""
    if kind == "agent_feature":
        agent = _clean(raw.get("agent") if isinstance(raw.get("agent"), str) else (raw.get("agent") or {}).get("name"), 40)
        add_expertise, add_instructions = _listy(raw.get("add_expertise")), str(raw.get("add_instructions") or "").strip()[:4000]
        if not agent or not (add_expertise or add_instructions):
            return None, f"“{title}” did not say which agent or what to add."
        return {**base, "spec": {"agent": agent, "add_expertise": add_expertise, "add_instructions": add_instructions}}, ""
    return None, f"Skipped a change of an unknown kind ({kind or 'none'})."


# ---------------------------------------------------------------------------
# What the plan is built from
# ---------------------------------------------------------------------------


def shipped_tab_labels(ui_root: Path) -> List[str]:
    try:
        text = (ui_root / "tabs.ts").read_text(encoding="utf-8")
    except OSError:
        return []
    return re.findall(r'label:\s*"([^"]+)"', text)[:60]


def python_modules(root: Path, request: str, limit: int = 40) -> List[str]:
    import self_patch

    wanted = _words(request)
    names: List[str] = []
    for folder in self_patch.CODE_DIRS:
        base = root / folder if folder else root
        if base.is_dir():
            names += [f"{folder}/{p.name}" if folder else p.name for p in sorted(base.glob("*.py"))
                      if p.name not in self_patch.PROTECTED_FILES and not p.name.startswith("test_")]
    core = {"chat_service.py", "router.py", "model_roles.py", "tools.py", "agent_runtime.py", "skills.py", "dynamic_tabs.py"}
    scored = sorted(names, key=lambda n: (-(len(_words(n.replace("_", " ")) & wanted) * 3 + (n.split("/")[-1] in core)), n))
    return scored[:limit]


def ui_files(ui_root: Path, request: str, limit: int = 40) -> List[str]:
    if not ui_root.is_dir():
        return []
    wanted = _words(request)
    files = [str(p.relative_to(ui_root)).replace("\\", "/") for p in ui_root.rglob("*")
             if p.suffix in UI_SUFFIXES and p.is_file() and "node_modules" not in p.parts]
    return sorted(files, key=lambda f: (-len(_words(re.sub(r"([a-z])([A-Z])", r"\1 \2", f).replace("/", " ")) & wanted), f))[:limit]


def build_plan_prompt(prompt: str, materials: Dict[str, Any], guidance: Dict[str, Any], web: str,
                      context: Dict[str, Any]) -> str:
    from dynamic_tabs import ALLOWED_CONNECTORS, BlockType

    parts = [f'The owner asks you to apply this to yourself:\n"""{prompt}"""']
    for item in materials.get("files", []):
        parts.append(f"File they gave — {item['name']}:\n{item['text'][:2500]}")
    for item in materials.get("pictures", []):
        parts.append(f"Picture they gave — {item['name']} (as the vision model saw it):\n{item['notes']}")
    for item in materials.get("links", []):
        parts.append(f"Link they gave — {item['title']} ({item['url']}):\n{item['text'][:2000]}")
    if web:
        parts.append(f"From a web search:\n{web}")
    if guidance.get("apple") or guidance.get("skills"):
        lines = ["Design guidance to follow:"]
        lines += [f"Apple HIG — {g['topic']}:\n{g['text']}" for g in guidance.get("apple", [])]
        lines.append(GENERAL_DESIGN)
        lines += [f"Nyx's design skill “{s['name']}”:\n{s['text']}" for s in guidance.get("skills", [])]
        parts.append("\n\n".join(lines))
    parts.append("How you are built now:\n"
                 f"- Tabs that ship with the app: {', '.join(context.get('tabs', [])) or 'unknown'}\n"
                 f"- Tabs added at run time: {', '.join(context.get('user_tabs', [])) or 'none'}\n"
                 f"- Agents: {', '.join(context.get('agents', [])) or 'none'}\n"
                 f"- Skills: {', '.join(context.get('skills', [])[:40]) or 'none'}\n"
                 f"- Python modules you may change: {', '.join(context.get('modules', []))}\n"
                 f"- Interface files you may change: {', '.join(context.get('ui', []))}")
    parts.append(WAYS.format(blocks=", ".join(b.value for b in BlockType), connectors=", ".join(sorted(ALLOWED_CONNECTORS))))
    parts.append(REPLY)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# The jobs
# ---------------------------------------------------------------------------


def _default_hooks() -> SimpleNamespace:
    """The real world. Tests pass their own."""

    def model(prompt: str, system: str, max_tokens: int) -> Tuple[str, str]:
        from model_roles import MODEL_ROLES

        run = MODEL_ROLES.run("code_generation", prompt, system="detailed thinking off\n" + system, max_tokens=max_tokens)
        return run.text, run.label

    def vision(image: bytes, mime: str, prompt: str) -> Tuple[str, str]:
        from model_roles import MODEL_ROLES

        run = MODEL_ROLES.run("image_check", prompt, images=[(image, mime or "image/png")], max_tokens=700)
        return run.text, run.label

    def search(query: str) -> str:
        from improve_review import web_notes

        return web_notes(query, limit=4)

    def hig() -> Any:
        from connectors.apple_design_connector import AppleDesignConnector

        return AppleDesignConnector()

    def design_skills() -> List[Dict[str, str]]:
        from skills import SKILL_STORE

        found = []
        for skill in SKILL_STORE.list_skills():
            text = f"{skill.get('name', '')} {skill.get('description', '')} {skill.get('category', '')}".lower()
            if skill.get("enabled", True) and re.search(r"\b(design|ui|ux|layout|interface|style)\b", text):
                found.append({"name": str(skill.get("name", "")), "text": excerpt(str(skill.get("instructions", "")), 1000)})
        return found[:2]

    def context() -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {"user_tabs": [], "agents": [], "skills": []}
        try:
            from dynamic_tabs import TAB_STORE

            out["user_tabs"] = [t.get("label", "") for t in TAB_STORE.list_tabs()][:30]
        except Exception:  # noqa: BLE001
            pass
        try:
            import agent_runtime

            out["agents"] = [str(a.get("name", "")) for a in agent_runtime.load_roster()][:30]
        except Exception:  # noqa: BLE001
            pass
        try:
            from skills import SKILL_STORE

            out["skills"] = [str(s.get("name", "")) for s in SKILL_STORE.list_skills()][:60]
        except Exception:  # noqa: BLE001
            pass
        return out

    def read_upload(upload_id: str) -> Dict[str, Any]:
        import uploads

        record = uploads.get_upload(upload_id)
        if record is None:
            raise ApplyError("One of the attachments is gone. Attach it again.")
        kind = uploads.kind_for(record["name"], record.get("mime", ""))
        if kind == "image":
            return {"kind": "image", "name": record["name"], "mime": record.get("mime") or "image/png",
                    "data": Path(record["path"]).read_bytes()}
        import absorb_sources

        return {"kind": "file", "name": record["name"], "text": absorb_sources.read_upload(upload_id).get("text", "")}

    def read_link(url: str) -> Dict[str, Any]:
        import absorb_sources

        return absorb_sources.read(absorb_sources.link_candidate(absorb_sources.check_url(url)))

    def create_tab(fields: Dict[str, Any], by: str) -> Dict[str, Any]:
        from dynamic_tabs import TAB_STORE, build_spec

        spec = build_spec(**fields, author=by, source="agent")
        TAB_STORE.create(spec)
        return {"tab_id": spec.tab_id, "label": spec.label}

    def delete_tab(tab_id: str) -> bool:
        from dynamic_tabs import TAB_STORE

        return TAB_STORE.delete(tab_id)

    def file_code(change: Dict[str, Any], prompt: str, by: str) -> str:
        from change_review import CHANGE_LOG, ChangeOrigin
        from improve_review import REVIEW_QUEUE

        record = CHANGE_LOG.propose(title=f"Apply: {change['title']}"[:140],
                                    description=f"{change['description']}\n\nWhy: {change.get('why', '')}\n\n"
                                                f"(Asked in the Apply tab: “{prompt[:300]}”)",
                                    author="Nyx · Apply tab", target=change["target"], origin=ChangeOrigin.AGENT)
        # The owner's Apply on this box is the approval; the edit is still written in a sandbox, tested and reviewed.
        REVIEW_QUEUE.approve(record.change_id, by=f"{by} (Apply tab)", implement=True)
        return record.change_id

    def code_status(change_id: str) -> Dict[str, Any]:
        from change_review import CHANGE_LOG
        from improve_review import REVIEW_QUEUE

        record = CHANGE_LOG.get(change_id)
        implement = (REVIEW_QUEUE.store.get(change_id) or {}).get("implement") or {}
        return {"status": record.status.value if record else "gone", **{k: implement.get(k) for k in
                                                                        ("state", "message", "lines", "diff") if k in implement}}

    def propose_ui(path: str, instruction: str) -> Dict[str, Any]:
        import code_workspace

        return code_workspace.propose(path, instruction)

    def open_ui(ui_root: Path) -> None:
        import code_workspace

        if not any(Path(w["path"]).resolve() == ui_root.resolve() for w in code_workspace.workspaces()):
            code_workspace.open_workspace(str(ui_root))

    def apply_ui(proposal_id: str) -> Dict[str, Any]:
        import code_workspace

        return code_workspace.apply(proposal_id)

    def undo_ui(proposal_id: str) -> Dict[str, Any]:
        import code_workspace

        return code_workspace.undo(proposal_id)

    def suggestion(item: Dict[str, Any], by: str) -> str:
        import absorb_engine

        return absorb_engine.apply_suggestion(item, by, "the Apply tab")

    def build(folder: Path) -> Tuple[bool, str]:
        npm = shutil.which("npm")
        if not npm:
            return False, "npm was not found on this PC, so the app cannot be rebuilt here."
        done = subprocess.run([npm, "run", "build"], cwd=str(folder), capture_output=True, text=True, timeout=600,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), encoding="utf-8", errors="replace")
        output = ((done.stdout or "") + "\n" + (done.stderr or "")).strip()
        return done.returncode == 0, "\n".join(output.splitlines()[-40:])

    return SimpleNamespace(model=model, vision=vision, search=search, hig=hig, design_skills=design_skills,
                           context=context, read_upload=read_upload, read_link=read_link, create_tab=create_tab,
                           delete_tab=delete_tab, file_code=file_code, code_status=code_status, propose_ui=propose_ui,
                           open_ui=open_ui, apply_ui=apply_ui, undo_ui=undo_ui, suggestion=suggestion, build=build)


class ApplyJobs:
    def __init__(self, *, hooks: Optional[SimpleNamespace] = None, root: Path = PROJECT_DIR,
                 ui_root: Optional[Path] = None, store: Optional[Path] = None, threaded: bool = True) -> None:
        self.hooks = hooks or _default_hooks()
        self.root = Path(root)
        self.ui_root = Path(ui_root) if ui_root else self.root / "frontend" / "nyx-pulse" / "src"
        self.store = Path(store) if store else data_path("apply/jobs.json")
        self.threaded = threaded
        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict[str, Any]] = self._load()
        self._build: Dict[str, Any] = {"state": "idle"}

    # --- storage -----------------------------------------------------------------------------------------------

    def _load(self) -> Dict[str, Dict[str, Any]]:
        try:
            data = json.loads(self.store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        jobs = {j["id"]: j for j in data.get("jobs", []) if isinstance(j, dict) and j.get("id")}
        for job in jobs.values():
            if job.get("status") in ("reading", "planning", "writing"):
                job["status"], job["error"] = "failed", "Nyx restarted while this was being planned. Send it again."
        return jobs

    def _save(self) -> None:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.get("created", 0), reverse=True)[:MAX_JOBS]
            self._jobs = {j["id"]: j for j in jobs}
            payload = json.dumps({"jobs": jobs}, ensure_ascii=False, default=str)
        try:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            temp = self.store.with_suffix(".json.tmp")
            temp.write_text(payload, encoding="utf-8")
            os.replace(temp, self.store)
        except OSError as error:  # pragma: no cover - the job still works in memory
            _LOG.warning("could not save apply jobs: %s", error)

    # --- reading -----------------------------------------------------------------------------------------------

    def overview(self) -> Dict[str, Any]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.get("created", 0), reverse=True)
            short = [{"id": j["id"], "prompt": j["prompt"][:160], "status": j["status"], "created": j["created"],
                      "changes": len(j.get("changes", [])),
                      "applied": sum(1 for c in j.get("changes", []) if c.get("status") == "applied")} for j in jobs]
            return {"jobs": short, "build": dict(self._build),
                    "running": any(j["status"] in ("reading", "planning", "writing") for j in jobs)}

    def get(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ApplyError("That request is not here any more.")
            public = json.loads(json.dumps(job, default=str))
        for change in public.get("changes", []):
            if change["kind"] == "code" and change.get("change_id"):
                try:
                    change["implement"] = self.hooks.code_status(change["change_id"])
                except Exception as error:  # noqa: BLE001
                    change["implement"] = {"state": "unknown", "message": str(error)[:200]}
        public["build"] = dict(self._build)
        return public

    # --- starting ----------------------------------------------------------------------------------------------

    def start(self, prompt: str, *, uploads: Optional[List[str]] = None, links: Optional[List[str]] = None,
              search: bool = True, by: str = "Owner") -> Dict[str, Any]:
        prompt = (prompt or "").strip()[:6000]
        if not prompt:
            raise ApplyError("Say what Nyx should change about itself.")
        with self._lock:
            if any(j["status"] in ("reading", "planning", "writing") for j in self._jobs.values()):
                raise ApplyError("Nyx is still planning the last request. Wait for it, or stop it first.")
            job = {"id": uuid.uuid4().hex[:10], "prompt": prompt, "by": by, "created": time.time(), "status": "reading",
                   "uploads": [str(u)[:64] for u in (uploads or [])][:MAX_UPLOADS],
                   "links": [str(u).strip()[:500] for u in (links or []) if str(u).strip()][:MAX_LINKS],
                   "search": bool(search), "steps": [], "notes": [], "inputs": {"files": [], "pictures": [], "links": []},
                   "guidance": {"apple": [], "skills": [], "web": False}, "understood": "", "summary": "",
                   "changes": [], "questions": [], "models": {}, "needs_rebuild": False, "cancel": False}
            self._jobs[job["id"]] = job
        self._save()
        if self.threaded:
            threading.Thread(target=self._run, args=(job["id"],), name=f"nyx-apply-{job['id']}", daemon=True).start()
        else:
            self._run(job["id"])
        return self.get(job["id"])

    def cancel(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ApplyError("That request is not here any more.")
            if job["status"] in ("reading", "planning", "writing"):
                job["cancel"] = True
                job["status"] = "cancelled"
        self._save()
        return self.get(job_id)

    # --- the pipeline ------------------------------------------------------------------------------------------

    def _step(self, job: Dict[str, Any], text: str, state: str = "running") -> None:
        with self._lock:
            if job["steps"] and job["steps"][-1]["state"] == "running":
                job["steps"][-1]["state"] = "done"
            job["steps"].append({"text": text, "state": state, "at": time.time()})
        self._save()

    def _live(self, job: Dict[str, Any]) -> bool:
        return not job.get("cancel")

    def _run(self, job_id: str) -> None:
        job = self._jobs[job_id]
        try:
            materials = self._read_inputs(job)
            if not self._live(job):
                return
            visual = bool(_VISUAL.search(job["prompt"])) or bool(materials["pictures"])
            guidance = self._guidance(job, materials) if visual else {"apple": [], "skills": []}
            web = ""
            if job["search"] and self._live(job):
                self._step(job, "Searching the web")
                try:
                    web = self.hooks.search(job["prompt"][:200]) or ""
                except Exception as error:  # noqa: BLE001 - searching is a help, not a requirement
                    job["notes"].append(f"The web search did not work: {str(error)[:160]}")
                job["guidance"]["web"] = bool(web)
            if not self._live(job):
                return
            self._step(job, "Seeing how Nyx is built now")
            context = {**self.hooks.context(), "tabs": shipped_tab_labels(self.ui_root),
                       "modules": python_modules(self.root, job["prompt"]), "ui": ui_files(self.ui_root, job["prompt"])}
            with self._lock:
                job["status"] = "planning"
            self._step(job, "Planning the change")
            reply, label = self.hooks.model(build_plan_prompt(job["prompt"], materials, guidance, web, context), SYSTEM, 3500)
            job["models"]["plan"] = label
            self._take_plan(job, reply)
            if not self._live(job):
                return
            for change in [c for c in job["changes"] if c["kind"] == "ui"]:
                self._write_ui(job, change, materials, guidance)
            with self._lock:
                if job["steps"] and job["steps"][-1]["state"] == "running":
                    job["steps"][-1]["state"] = "done"
                job["status"] = "ready" if job["changes"] else "empty"
        except Exception as error:  # noqa: BLE001 - the owner reads what went wrong
            _LOG.warning("apply job %s failed: %s", job_id, error)
            with self._lock:
                if job["steps"] and job["steps"][-1]["state"] == "running":
                    job["steps"][-1]["state"] = "failed"
                job["status"], job["error"] = "failed", str(error)[:400]
        self._save()

    def _read_inputs(self, job: Dict[str, Any]) -> Dict[str, Any]:
        materials: Dict[str, List[Dict[str, Any]]] = {"files": [], "pictures": [], "links": []}
        if job["uploads"]:
            self._step(job, f"Reading {len(job['uploads'])} attachment{'s' if len(job['uploads']) != 1 else ''}")
        for upload_id in job["uploads"]:
            if not self._live(job):
                break
            try:
                item = self.hooks.read_upload(upload_id)
                if item["kind"] == "image":
                    self._step(job, f"Looking at {item['name']} to understand its layout")
                    notes, label = self.hooks.vision(item["data"], item["mime"], PICTURE_PROMPT)
                    job["models"]["pictures"] = label
                    entry = {"name": item["name"], "notes": _clean(notes, 1600), "upload": upload_id}
                    materials["pictures"].append(entry)
                    job["inputs"]["pictures"].append(entry)
                else:
                    text = str(item.get("text") or "")
                    materials["files"].append({"name": item["name"], "text": text[:6000]})
                    job["inputs"]["files"].append({"name": item["name"], "chars": len(text)})
            except Exception as error:  # noqa: BLE001
                job["notes"].append(f"An attachment could not be read: {str(error)[:200]}")
        for url in job["links"]:
            if not self._live(job):
                break
            self._step(job, f"Reading {url[:80]}")
            try:
                page = self.hooks.read_link(url)
                entry = {"title": _clean(page.get("title") or url, 160), "url": url, "text": str(page.get("text") or "")[:4000]}
                materials["links"].append(entry)
                job["inputs"]["links"].append({"title": entry["title"], "url": url})
            except Exception as error:  # noqa: BLE001
                job["notes"].append(f"{url[:80]} could not be read: {str(error)[:160]}")
        return materials

    def _guidance(self, job: Dict[str, Any], materials: Dict[str, Any]) -> Dict[str, Any]:
        self._step(job, "Looking up Apple's design guidance and Nyx's design skills")
        guidance: Dict[str, Any] = {"apple": [], "skills": []}
        query = " ".join([job["prompt"][:300]] + [p["notes"][:200] for p in materials["pictures"]])
        try:
            hig = self.hooks.hig()
            if hig.is_available():
                for match in hig.lookup(query)[:3]:
                    document = hig.read_guideline(match["file"])
                    if document.get("ok"):
                        guidance["apple"].append({"topic": match["topic"], "text": excerpt(document["content"], 1300)})
        except Exception as error:  # noqa: BLE001
            job["notes"].append(f"Apple's guidance could not be read: {str(error)[:160]}")
        try:
            guidance["skills"] = self.hooks.design_skills()
        except Exception:  # noqa: BLE001
            guidance["skills"] = []
        job["guidance"]["apple"] = [g["topic"] for g in guidance["apple"]]
        job["guidance"]["skills"] = [s["name"] for s in guidance["skills"]]
        job["guidance"]["general"] = True
        return guidance

    def _take_plan(self, job: Dict[str, Any], reply: str) -> None:
        from absorb_engine import json_from

        data = json_from(reply)
        if not isinstance(data, dict):
            raise ApplyError("The plan did not come back in a form Nyx could read. Try again, maybe with fewer words.")
        changes, notes = [], []
        for raw in (data.get("changes") or [])[:MAX_CHANGES + 3]:
            change, note = vet_change(raw, root=self.root, ui_root=self.ui_root)
            if change and len(changes) < MAX_CHANGES:
                change["index"] = len(changes)
                changes.append(change)
            elif note:
                notes.append(note)
        with self._lock:
            job["understood"] = _clean(data.get("understood"), 600)
            job["summary"] = _clean(data.get("summary"), 900)
            job["questions"] = [_clean(q, 300) for q in (data.get("questions") or []) if _clean(q, 300)][:4]
            job["changes"] = changes
            job["notes"] += notes

    def _write_ui(self, job: Dict[str, Any], change: Dict[str, Any], materials: Dict[str, Any],
                  guidance: Dict[str, Any]) -> None:
        """Write the interface edit as a diff now, so the owner reads real code before applying. Nothing is saved."""
        self._step(job, f"Writing the edit for {change['target']}")
        with self._lock:
            job["status"] = "writing"
        instruction = change["description"]
        if materials["pictures"]:
            instruction += "\n\nThe owner's picture, as described: " + " ".join(p["notes"][:700] for p in materials["pictures"][:2])
        if guidance.get("apple"):
            instruction += "\n\nFollow Apple's guidance (" + ", ".join(g["topic"] for g in guidance["apple"]) + ") and: " \
                           + GENERAL_DESIGN.split("\n", 1)[1][:900]
        try:
            self.hooks.open_ui(self.ui_root)
            proposal = self.hooks.propose_ui(str(self.ui_root / change["target"]), instruction)
            change["proposal"] = {k: proposal.get(k) for k in ("id", "diff", "lines", "explanation", "model", "added", "removed")}
        except Exception as error:  # noqa: BLE001 - the owner can ask again from the box
            change["error"] = f"The edit could not be written: {str(error)[:300]}"

    # --- deciding ----------------------------------------------------------------------------------------------

    def decide(self, job_id: str, index: int, action: str, *, by: str = "Owner") -> Dict[str, Any]:
        if action not in ("apply", "skip", "undo", "retry"):
            raise ApplyError("Unknown action.")
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ApplyError("That request is not here any more.")
            if job["status"] not in ("ready", "empty"):
                raise ApplyError("Wait until the plan is ready.")
            change = next((c for c in job["changes"] if c.get("index") == index), None)
            if change is None:
                raise ApplyError("That change is not in this plan.")
            if change.get("busy"):
                raise ApplyError("That change is already being worked on.")
            change["busy"] = True
        try:
            self._decide(job, change, action, by)
        finally:
            with self._lock:
                change.pop("busy", None)
            self._save()
        return self.get(job_id)

    def _decide(self, job: Dict[str, Any], change: Dict[str, Any], action: str, by: str) -> None:
        kind, status = change["kind"], change["status"]
        if action == "skip":
            if status != "proposed":
                raise ApplyError("Only a change that has not been applied can be skipped.")
            change["status"] = "skipped"
            return
        if action == "retry":
            if kind != "ui" or status != "proposed":
                raise ApplyError("Only an interface edit that is not applied can be written again.")
            change.pop("error", None)
            self._write_ui(job, change, {"pictures": job["inputs"]["pictures"]}, {})
            return
        if action == "undo":
            if status != "applied":
                raise ApplyError("Only an applied change can be undone here.")
            if kind == "tab":
                self.hooks.delete_tab(change["result"]["tab_id"])
            elif kind == "ui":
                self.hooks.undo_ui(change["proposal"]["id"])
                job["needs_rebuild"] = True
            else:
                raise ApplyError("Undo this one where it lives: Improve → Review changes rolls back code; skills and "
                                 "agents are removed in their tabs.")
            change["status"] = "undone"
            return
        # apply
        if status != "proposed":
            raise ApplyError(f"That change is already {status}.")
        if kind == "tab":
            change["result"] = self.hooks.create_tab(change["tab"], by)
            change["message"] = f"Added the tab “{change['result']['label']}”. It is in the tab bar now."
        elif kind == "code":
            change["change_id"] = self.hooks.file_code(change, job["prompt"], by)
            change["message"] = ("Approved. Nyx is writing the edit in a sandbox, running the tests and having the real "
                                 "diff reviewed; it lands only if all of that passes, and Improve can roll it back.")
        elif kind == "ui":
            proposal = change.get("proposal") or {}
            if not proposal.get("id"):
                raise ApplyError(change.get("error") or "There is no edit to apply yet. Write it again first.")
            applied = self.hooks.apply_ui(proposal["id"])
            change["result"] = {"lines": applied.get("lines") or proposal.get("lines")}
            change["message"] = "Written to the file. Rebuild the app to see it; Undo puts the file back."
            job["needs_rebuild"] = True
        else:
            change["message"] = self.hooks.suggestion({"kind": kind, "title": change["title"], "why": change.get("why", ""),
                                                        "spec": change["spec"]}, by)
        change["status"] = "applied"
        change["applied_at"] = time.time()

    # --- rebuilding the app ------------------------------------------------------------------------------------

    def rebuild(self, *, by: str = "Owner") -> Dict[str, Any]:
        with self._lock:
            if self._build.get("state") == "running":
                raise ApplyError("The app is already being rebuilt.")
            self._build = {"state": "running", "started": time.time(), "by": by, "output": ""}
        folder = self.ui_root.parent

        def work() -> None:
            try:
                ok, output = self.hooks.build(folder)
            except Exception as error:  # noqa: BLE001
                ok, output = False, str(error)[:600]
            with self._lock:
                self._build = {**self._build, "state": "done" if ok else "failed", "finished": time.time(), "output": output}
                if ok:
                    for job in self._jobs.values():
                        job["needs_rebuild"] = False
            self._save()

        if self.threaded:
            threading.Thread(target=work, name="nyx-apply-rebuild", daemon=True).start()
        else:
            work()
        return dict(self._build)

    def build_status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._build)


_JOBS: Optional[ApplyJobs] = None
_JOBS_LOCK = threading.Lock()


def jobs() -> ApplyJobs:
    """The one set of Apply jobs (made on first use, so importing this module touches nothing)."""
    global _JOBS
    with _JOBS_LOCK:
        if _JOBS is None:
            _JOBS = ApplyJobs()
        return _JOBS
