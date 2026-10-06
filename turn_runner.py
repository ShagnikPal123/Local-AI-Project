"""One chat turn, streamed: what the user watches while Nyx works.

The owner's request: "after giving a prompt the AI should be showing that it's
working, and what it's working on, and thought process."

``ChatService.chat()`` answers in one blocking call — correct, but silent. This
runs the same turn while publishing every step as an event (schema in
OVERHAUL_CONTRACTS.md §3.1):

* ``status`` — what is happening now, in words ("gemini-3.5-flash is thinking").
* ``thought`` / ``thought.delta`` — the model's own reasoning summaries (Gemini
  thought parts) and its short ``<thinking>`` plan lines before acting.
* ``skill.used`` — which skills were attached, and why the answer sounds as it does.
* ``tool.start`` / ``tool.progress`` / ``tool.image`` / ``tool.end`` — each action,
  emitted by the tool registry itself so no tool can skip it.
* ``answer.delta`` — the reply as it is written; ``answer.reset`` when text that
  started streaming turned out to be the lead-in to a tool call.
* ``done`` / ``error``.

Everything the non-streaming path does for correctness still happens here:
directive splitting, skills, memory, the forced final answer when the tool budget
runs out, and never showing raw tool-call markup to the user.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from providers.base import ProviderError
from tool_context import ToolContext, use_context
from tools import TOOL_REGISTRY
try:
    from tools import load_custom_vocabulary
except Exception:  # pragma: no cover - vocabulary loader may not exist in all environments
    load_custom_vocabulary = None

#: A tool call, closed or not — models sometimes stop before ``</tool_call>``.
_TOOL_CALL_RE = re.compile(r"<tool_call>.*?(?:</tool_call>|\Z)", re.DOTALL)
_THINKING_RE = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL | re.IGNORECASE)

#: Recent user/assistant turns the quick path carries, so "and tomorrow?" still
#: knows what "tomorrow" is about. The old fast path sent the message alone.
_FAST_CONTEXT_TURNS = 8

#: How much of each tool result is kept in history once the turn is over. The
#: full text was needed while working; later turns only need to know it happened.
_COMPACT_RESULT_CHARS = 600

#: Written into the history after a turn that did not do what was asked, so the
#: next turn does not treat that request as pending work (Request G11: "switch to
#: nvidia" also carried out the download request that had just failed twice).
FAILED_TURN_NOTE = (
    "[Turn not completed] The request just above was NOT carried out and is not pending. "
    "Do not act on it in later turns unless the user asks for it again (\"try again\", \"please\", \"do it\")."
)

#: Repairs a turn may spend on unreadable tool calls and empty replies before giving up.
_MAX_REPAIRS = 2


class StreamFilter:
    """Split a streaming reply into answer text and thinking, hiding tool markup.

    Tags can arrive split across chunks ("<tool" + "_call>"), so text that could
    be the start of a tag is held back until the next chunk decides it.
    """

    _OPEN = {"<tool_call>": "tool", "<thinking>": "thinking"}
    _CLOSE = {"tool": "</tool_call>", "thinking": "</thinking>"}

    def __init__(self, on_answer: Callable[[str], None], on_thought: Callable[[str], None]) -> None:
        self.on_answer = on_answer
        self.on_thought = on_thought
        self.pending = ""
        self.state = "text"
        self.answer_chars = 0
        self.saw_tool_call = False

    def _emit(self, text: str) -> None:
        if not text:
            return
        if self.state == "thinking":
            self.on_thought(text)
        elif self.state == "text":
            self.answer_chars += len(text)
            self.on_answer(text)

    def feed(self, chunk: str) -> None:
        self.pending += chunk
        while self.pending:
            lowered = self.pending.lower()
            if self.state == "text":
                hits = [(lowered.find(tag), tag) for tag in self._OPEN if lowered.find(tag) != -1]
                if hits:
                    index, tag = min(hits)
                    self._emit(self.pending[:index])
                    self.pending = self.pending[index + len(tag):]
                    self.state = self._OPEN[tag]
                    if self.state == "tool":
                        self.saw_tool_call = True
                    continue
                keep = self._partial_suffix(lowered, tuple(self._OPEN))
                self._emit(self.pending[: len(self.pending) - keep])
                self.pending = self.pending[len(self.pending) - keep:]
                return
            close = self._CLOSE[self.state]
            index = lowered.find(close)
            if index != -1:
                self._emit(self.pending[:index])
                self.pending = self.pending[index + len(close):]
                self.state = "text"
                continue
            keep = self._partial_suffix(lowered, (close,))
            self._emit(self.pending[: len(self.pending) - keep])
            self.pending = self.pending[len(self.pending) - keep:]
            return

    def finish(self) -> None:
        if self.state in ("text", "thinking"):
            self._emit(self.pending)
        self.pending = ""

    @staticmethod
    def _partial_suffix(text: str, tags: Tuple[str, ...]) -> int:
        """Length of the longest ending of ``text`` that could begin a tag."""
        longest = 0
        for tag in tags:
            for size in range(1, len(tag)):
                if text.endswith(tag[:size]):
                    longest = max(longest, size)
        return longest


_MENTION_PREFIX = "[Agents mentioned by the user]"


def _agent_command_names() -> set:
    """Slash-command names that call an agent (``/coder``), so a called agent is not also auto-matched."""
    try:
        import commands

        return {c["name"] for c in commands.agent_commands()}
    except Exception:  # pragma: no cover
        return set()


def chat_modes_swarm_nudge() -> str:
    """The one reminder a Swarm turn gets when it answered without its swarm (chat_modes.SWARM_NUDGE)."""
    try:
        import chat_modes

        return chat_modes.SWARM_NUDGE
    except Exception:  # pragma: no cover
        return "Swarm mode: hand the parts to agents with dispatch_agents, then merge their reports."


def mentioned_agents(text: str) -> List[str]:
    """Roster agents the user @mentioned, in the order written.

    Accepts the name as shown ("@Web Design"), squashed ("@WebDesign"), or its
    first word when that is unambiguous ("@Finance").
    """
    if "@" not in (text or ""):
        return []
    try:
        from agent_runtime import load_roster

        roster = [a["name"] for a in load_roster() if a.get("role") != "master"]
    except Exception:
        return []

    first_words: Dict[str, int] = {}
    for name in roster:
        word = re.split(r"[\s&]+", name.strip())[0].lower()
        first_words[word] = first_words.get(word, 0) + 1

    found: List[tuple] = []
    for name in roster:
        variants = {name, re.sub(r"[\s&]+", "", name)}
        word = re.split(r"[\s&]+", name.strip())[0]
        if first_words.get(word.lower()) == 1:
            variants.add(word)
        for variant in sorted(variants, key=len, reverse=True):
            match = re.search(r"@" + re.escape(variant) + r"(?![\w-])", text, re.IGNORECASE)
            if match:
                found.append((match.start(), name))
                break
    ordered = []
    for _pos, name in sorted(found):
        if name not in ordered:
            ordered.append(name)
    return ordered


#: Citation marks some models copy from their training format, e.g. "【open_link†L1-L4】".
_CITATION_MARK_RE = re.compile(r"【[^】\n]{1,60}†[^】\n]{0,40}】")


def visible_answer(text: str) -> str:
    """The reply with thinking, tool-call blocks and stray citation marks removed."""
    cleaned = _TOOL_CALL_RE.sub("", text or "")
    cleaned = _THINKING_RE.sub("", cleaned)
    cleaned = _CITATION_MARK_RE.sub("", cleaned)
    return cleaned.strip()


#: A specialist reports back to the Manager ("Report from Coder (12s): Understood: …"). In the agent's
#: own chat there is no Manager to report to, so the wrapper is dropped and it just talks.
_REPORT_HEADER_RE = re.compile(r"^\s*Report from [^\n:]{1,60}:?\s*", re.IGNORECASE)
_UNDERSTOOD_RE = re.compile(r"^\s*Understood:.*(?:\n|$)", re.IGNORECASE | re.MULTILINE)


def _as_conversation(report: str) -> str:
    """A specialist's report, read as its own words in its own chat."""
    text = _REPORT_HEADER_RE.sub("", report or "", count=1)
    text = _UNDERSTOOD_RE.sub("", text, count=1)
    return text.strip()


def thinking_lines(text: str) -> List[str]:
    return [m.strip() for m in _THINKING_RE.findall(text or "") if m.strip()]


class TurnRunner:
    """Runs one streaming turn against a ChatService."""

    def __init__(
        self,
        service: Any,
        message: str,
        *,
        sink: Callable[[Dict[str, Any]], None],
        attachments: Optional[List[str]] = None,
        role: str = "local",
        turn_id: Optional[str] = None,
        cancel_event: Any = None,
        attribute_id: Optional[str] = None,
        provider: Optional[str] = None,
        voice_session: str = "",
        mode: Optional[str] = None,
    ) -> None:
        self.service = service
        self.message = message or ""
        #: Set when the owner spoke this turn: the voice pipeline may already have written the answer.
        self.voice_session = (voice_session or "").strip()
        self.sink = sink
        self.attachments = list(attachments or [])
        self.role = role
        self.turn_id = turn_id or uuid.uuid4().hex[:12]
        self.attribute_id = attribute_id
        self.started = time.perf_counter()
        self.context = ToolContext(turn_id=self.turn_id, chat_id=getattr(service, "chat_id", "default"),
                                   role=role, sink=self._publish)
        if cancel_event is not None:
            self.context.cancelled = cancel_event
        # A conversation can carry its own gate for tools (the Free Will tab: freewill.prepare puts it there).
        self.context.guard = getattr(service, "tool_guard", None)
        self.provider = ""
        self.model = ""
        self.tools_used: List[str] = []
        self.user_text = self.message
        self.mode = "full"
        #: The slider under the composer: normal | cowork | plan | plan_go (chat_modes.py).
        self.chat_mode = mode or "normal"
        self.mode_switches: Dict[str, Any] = {}
        self.escalated = False
        self.skill_ids: List[str] = []
        self.agent_names: List[str] = []
        self.records: List[Dict[str, Any]] = []
        #: Pictures generated this turn, as (upload id, name).
        self.generated_images: List[Tuple[str, str]] = []
        self._tool_categories: Dict[str, str] = {}
        #: The provider picked in the chat dropdown ("" / None = the router decides).
        self.prefer_provider: Optional[str] = (provider or "").strip().lower() or None
        if self.prefer_provider == "auto":
            self.prefer_provider = None
        #: Why providers could not answer this turn, by name (for the "answered instead" notice).
        self._provider_problems: Dict[str, str] = {}
        self._fallback_announced = False
        #: True when the turn ended without doing what was asked.
        self.failed = False
        #: Text the answer drew on (tool results), for the Sources drop-down (Request H15).
        self._source_texts: List[str] = []
        self.sources: List[Dict[str, str]] = []

    # --- events ---------------------------------------------------------------

    def _publish(self, event: Dict[str, Any]) -> None:
        event.setdefault("turn_id", self.turn_id)
        if event.get("type") == "tool.start" and event.get("call_id"):
            self._tool_categories[str(event["call_id"])] = str(event.get("category") or "")
        elif event.get("type") == "tool.end" and event.get("ok") and event.get("preview"):
            try:
                import super_brain

                # What Nyx read while working (pages, files, mail) is remembered too.
                super_brain.ingest_tool_result(str(event.get("name", "")), self._tool_categories.get(str(event.get("call_id")), ""),
                                               str(event.get("preview", "")))
            except Exception:  # pragma: no cover
                pass
        if event.get("type") == "model.switched" and event.get("provider"):
            # The model switched providers mid-turn; the rest of the turn follows it.
            self.prefer_provider = str(event["provider"]).lower()
            self._fallback_announced = True
        if event.get("type") == "agent.update" and event.get("name") and event["name"] not in self.agent_names:
            self.agent_names.append(str(event["name"]))
        if event.get("type") == "tool.image" and event.get("generated") and event.get("upload_id"):
            self.generated_images.append((str(event["upload_id"]), str(event.get("name") or "Generated image")))
        try:
            self.sink(event)
        except Exception:  # pragma: no cover - a UI problem must not fail the turn
            pass

    def emit(self, event_type: str, **payload: Any) -> None:
        self._publish({"type": event_type, **payload})

    def cancelled(self) -> bool:
        return self.context.cancelled.is_set()

    # --- the turn ---------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        with use_context(self.context):
            try:
                return self._run()
            except ProviderError as error:
                return self._finish_offline(str(error))
            except Exception as error:  # noqa: BLE001 - the user must hear about anything that ends the turn
                self._mark_not_done()
                self.emit("error", message=f"{type(error).__name__}: {error}")
                raise

    def _run(self) -> Dict[str, Any]:
        from chat_service import split_directives
        from config import SETTINGS

        service = self.service
        if self.attribute_id is not None:
            service.add_attribute_guidance(self.attribute_id)

        directives, stripped = split_directives(self.message)
        user_text = stripped or self.message
        if directives:
            service._apply_directives(directives)
        # "[fresh] …" is the Refresh button on a cached answer: skip the cache.
        fresh = user_text.lower().startswith("[fresh]")
        if fresh:
            user_text = user_text[len("[fresh]"):].strip() or user_text
        self.user_text = user_text

        # The slider under the composer (Project Null N82–N84): Normal is quick and
        # thinks out loud, Co-work works on without checking in, Plan writes the plan
        # and may not change anything until the owner approves it.
        self.mode_switches = self._apply_chat_mode()

        attachment_text, images, records = self._load_attachments()
        mode = "full" if (images or attachment_text) else None
        if self.mode_switches.get("force_full"):
            mode = "full"
        self.emit("turn.start", chat_id=service.chat_id, attachments=records)
        self.emit("status", phase="route", text="Reading your message")

        stored = user_text
        if records:
            stored += "\n\n" + "\n".join(f"[Attached: {r.get('name')}]" for r in records)
        service.chat_store.append("user", stored, chat_id=service.chat_id)

        # Request H13: /commands anywhere in the message — their skills are read first.
        service.conversation_history = [
            m for m in service.conversation_history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith(("[Commands the user wrote]", "[Adult mode is on]")))
        ]
        try:
            import content_mode

            adult = content_mode.system_prompt()
            if adult:
                service.conversation_history.append({"role": "system", "content": adult})
        except Exception:  # pragma: no cover - a settings problem must not stop the turn
            pass
        command_brief: Dict[str, Any] = {"found": [], "skills": [], "context": ""}
        try:
            import commands as commands_module

            command_brief = commands_module.brief_for(user_text)
        except Exception:  # pragma: no cover - commands never block a turn
            pass
        if command_brief["found"]:
            names = ", ".join(f"/{n}" for n in command_brief["found"])
            self.emit("status", phase="route", text=f"Reading {names} first")

        skills = service._attach_skills(user_text) or []
        if command_brief["skills"]:
            called = {str(x["id"]) for x in command_brief["skills"]}
            skills = command_brief["skills"] + [s for s in skills if str(s.get("id")) not in called]
        if command_brief["context"]:
            # First among the turn's system context, so it is read before other skills and memory.
            insert_at = next((i for i, m in enumerate(service.conversation_history) if m.get("role") != "system"),
                             len(service.conversation_history))
            service.conversation_history.insert(insert_at, {"role": "system", "content": command_brief["context"]})
        if skills:
            self.emit("skill.used", skills=skills)
            self.skill_ids = [str(sk.get("id") or sk.get("name") or "") for sk in skills if isinstance(sk, dict)]

        # Persistent custom vocabulary: load from storage and inject as system context so it applies every turn.
        self._apply_custom_vocabulary()

        # Learning: a cached answer, learned style, and what similar turns needed.
        hooks = self._learning_before(user_text, records, fresh)
        cached = hooks.get("cache_hit")
        if cached is not None:
            return self._finish_cached(user_text, cached)
        self._apply_style_hints(hooks.get("style_hints") or "")
        suggestion = hooks.get("suggestion") or {}
        route = suggestion.get("route") or {}
        if command_brief["found"]:
            mode = "full"  # the quick path carries no skills, so a message with /commands never takes it
        if mode is None and isinstance(route, dict) and route.get("label") == "full" and float(route.get("p") or 0) >= 0.75:
            mode = "full"
            self.emit("learning.note", text="Similar requests needed tools before, so going straight to the full pipeline.")

        # Prompt optimizer (Settings): the model reads the owner's words plus a refined brief.
        # Normal and Plan skip the refining pass: it can cost seconds, and "much faster" was the point.
        model_text = (user_text if self.mode_switches.get("skip_optimizer")
                      else self._optimize_prompt(user_text, records, hooks.get("style_hints") or ""))

        service.conversation_history = [
            m for m in service.conversation_history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith(_MENTION_PREFIX))
        ]
        mentioned = mentioned_agents(user_text)
        if mentioned:
            # "@Finance compare these funds" is an instruction to use that agent,
            # so it must not take the fast path (which has no tools) and the
            # Manager is told plainly to delegate rather than answer itself.
            names = ", ".join(mentioned)
            self.emit("status", phase="agents", text=f"Bringing in {names}")
            service.conversation_history.append({
                "role": "system",
                "content": (
                    f"{_MENTION_PREFIX}\nThe user addressed these agents directly with @mentions: {names}. "
                    "Hand each of them the part of the request meant for them with delegate_task "
                    "(delegate_parallel when there are several), including all the context they need, "
                    "then combine their reports into your answer."
                ),
            })
            mode = "full"

        # Auto skill / Auto agent (Update 1, U21): "/auto" or "@auto" — Nyx picks the skills, agents and
        # connectors for the job and runs the team itself; each agent's request and reply are shown (U46).
        auto_called = False
        try:
            import auto_team

            service.conversation_history = [
                m for m in service.conversation_history
                if not (m.get("role") == "system" and str(m.get("content", "")).startswith(auto_team.PREFIX))
            ]
            if auto_team.called(user_text):
                auto_called = True
                team = auto_team.assemble(user_text)
                self.emit("status", phase="agents", text=auto_team.status_line(team))
                self.emit("auto.team", **auto_team.view(team))
                service.conversation_history.append({"role": "system", "content": auto_team.brief(team)})
                mode = "full"
        except Exception:  # pragma: no cover - Auto never blocks a turn
            pass

        # Sub-agents Nyx should bring in by itself (owner, 2026-09-16: "AI should auto use the sub agent it needs").
        try:
            import agent_match

            service.conversation_history = [
                m for m in service.conversation_history
                if not (m.get("role") == "system" and str(m.get("content", "")).startswith(agent_match.PREFIX))
            ]
            called_agents = any(name for name in command_brief.get("found", []) if name in _agent_command_names())
            if (getattr(SETTINGS, "auto_agents", True) and not mentioned and not called_agents and not auto_called
                    and not self._chat_agent()):
                auto_matches = agent_match.match(user_text)
                if auto_matches:
                    self.emit("status", phase="agents", text="Bringing in " + ", ".join(m["name"] for m in auto_matches))
                    self.emit("agents.suggested", agents=auto_matches)
                    service.conversation_history.append({"role": "system", "content": agent_match.brief(auto_matches)})
                    mode = "full"
        except Exception:  # pragma: no cover - matching never blocks a turn
            pass

        # Command Zone: a one-line instruction for the whole team. The brief tells the Manager to route it
        # (agents, tabs, ideas for later), so it needs the tools — never the quick path.
        try:
            import command_zone

            zone_prefix = command_zone.BRIEF_PREFIX
            zone_brief = command_zone.brief_for_chat(getattr(service, "chat_id", ""))
        except Exception:  # pragma: no cover - the zone never blocks a turn
            zone_prefix, zone_brief = "[Command Zone]", ""
        service.conversation_history = [
            m for m in service.conversation_history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith(zone_prefix))
        ]
        if zone_brief:
            self.emit("status", phase="route", text="Routing this to the team")
            service.conversation_history.append({"role": "system", "content": zone_brief})
            mode = "full"

        consult_settings = self._consult_settings()
        heavy = False
        if self.mode_switches.get("skip_consult"):
            consult_settings = {**consult_settings, "consult": "off"}  # second opinions cost 25 s
        if consult_settings["consult"] != "off":
            try:
                import consult as consult_module

                heavy = consult_settings["consult"] == "always" or consult_module.is_heavy(user_text)
            except Exception:  # pragma: no cover
                heavy = False
        if heavy:
            mode = "full"  # a hard request gets the tools and the second opinions, not the quick path

        if mode is None:
            decision = service.speed_policy.decide(user_text, service.speed_mode)
            mode = "fast" if decision.fast else "full"
        self.mode = mode
        self.emit("status", phase="think", text="Answering" if mode == "fast" else "Planning how to do this")

        owner_agent = self._chat_agent()
        if owner_agent:
            return self._answer_as_agent(owner_agent, user_text, attachment_text)

        # Request Q: past the owner's threshold, summarize earlier messages before this turn instead of overflowing.
        try:
            import context_budget

            context_budget.maybe_auto_compact(service, provider=self.prefer_provider or getattr(SETTINGS, "preferred_online_provider", "") or "",
                                              chat_store=service.chat_store, chat_id=getattr(service, "chat_id", ""), emit=self.emit)
        except Exception:  # pragma: no cover - compaction never blocks a turn
            pass

        # The owner spoke, and the answer was already written while they were
        # still talking. Only questions and small talk get here (voice_pipeline
        # refuses to draft anything that would act), so nothing is skipped.
        if self.voice_session and not images and not attachment_text:
            spoken = self._voice_draft(user_text)
            if spoken is not None:
                return spoken

        if mode == "fast":
            result = self._fast_path(user_text, model_text)
            if result is not None:
                return result
            self.escalated = True
            self.emit("status", phase="think", text="This needs tools — switching to the full pipeline")

        service.conversation_history = [
            m for m in service.conversation_history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith("[Second opinions]"))
        ]
        if heavy:
            self._consult(user_text, consult_settings)

        content = model_text if not attachment_text else f"{model_text}\n\n{attachment_text}"
        turn_message: Dict[str, Any] = {"role": "user", "content": content}
        if images:
            turn_message["images"] = images
        service.conversation_history.append(turn_message)
        history_start = len(service.conversation_history) - 1

        reply = self._tool_loop(max_steps=self.mode_switches.get("max_steps") or getattr(SETTINGS, "max_tool_steps", 24))
        self._compact_turn(history_start)
        if model_text != user_text and history_start < len(service.conversation_history):
            # Later turns carry the owner's own words, not this turn's brief.
            message = service.conversation_history[history_start]
            message["content"] = str(message.get("content", "")).replace(model_text, user_text, 1)
        return self._finish(reply)

    def _apply_chat_mode(self) -> Dict[str, Any]:
        """Set this turn's temperament from the mode slider, and gate its tools in Plan mode."""
        try:
            import chat_modes
        except Exception:  # pragma: no cover - the chat works without modes
            return {}
        switches = chat_modes.prepare(self.service, self.chat_mode, self.user_text)
        self.context.guard = getattr(self.service, "tool_guard", None)
        # Swarm: dispatch_agents reads this to allow the owner's swarm size instead of the usual few boxes.
        self.context.swarm = int(switches.get("swarm") or 0)
        words = {"normal": "Normal — a quick answer",
                 "cowork": "Co-work — working in the background",
                 "plan": "Plan — writing the plan first, changing nothing",
                 "plan_go": "Working through the plan you approved",
                 "swarm": f"Swarm — up to {switches.get('swarm') or 0} agents at once"}[switches["mode"]]
        if switches.get("auto"):
            self.emit("status", phase="route", text=f"Auto picked {words} ({switches.get('auto_reason')})")
        elif switches["mode"] != "normal":
            self.emit("status", phase="route", text=words)
        self.emit("chat.mode", mode=switches["mode"], auto=bool(switches.get("auto")),
                  reason=str(switches.get("auto_reason") or ""), swarm=int(switches.get("swarm") or 0))
        return switches

    def _consult_settings(self) -> Dict[str, Any]:
        try:
            import consult as consult_module

            return consult_module.manager_settings()
        except Exception:  # pragma: no cover
            return {"consult": "off", "consult_models": "both", "consult_with": []}

    def _consult(self, user_text: str, settings: Dict[str, Any]) -> None:
        """Ask the same model (fresh) and another model for short notes before working (Requests H2, H6)."""
        from config import SETTINGS

        try:
            import consult as consult_module

            primary = self.prefer_provider or SETTINGS.preferred_online_provider
            primary_model = str(getattr(SETTINGS, f"{primary}_model", "") or "")
            seats = consult_module.seats(primary, primary_model, settings["consult_models"],
                                         consult_module.agents_named(settings["consult_with"]))
            if not seats:
                return
            self.emit("status", phase="think", text="Hard one — getting second opinions from " + ", ".join(s["label"] for s in seats))
            notes = consult_module.consult(
                user_text, primary=primary, primary_model=primary_model, models=settings["consult_models"],
                agents=consult_module.agents_named(settings["consult_with"]), budget=25,
                on_note=lambda note: self.emit("thought", text=f"{note['by']}: {note['text']}", source="consult"))
        except Exception as error:  # noqa: BLE001 - consulting never costs the turn
            self.emit("learning.note", text=f"Second opinions skipped: {error}")
            return
        if notes:
            self.emit("consult.done", seats=[n["by"] for n in notes])
            self.service.conversation_history.append({"role": "system", "content": consult_module.as_context(notes)})

    def _chat_agent(self) -> str:
        """The agent this chat belongs to, if any (owner request: link a sub-agent to a chat)."""
        try:
            store = getattr(self.service, "chat_store", None)
            getter = getattr(store, "agent_for", None)
            name = getter(getattr(self.service, "chat_id", "")) if callable(getter) else ""
            from agent_runtime import roster_entry_exact

            return name if name and roster_entry_exact(name) else ""
        except Exception:  # pragma: no cover - a linking problem must not stop the chat
            return ""

    def _answer_as_agent(self, name: str, user_text: str, attachment_text: str = "") -> Dict[str, Any]:
        """Hand the whole turn to one specialist: this chat is theirs."""
        from agent_runtime import run_specialist

        self.emit("status", phase="agents", text=f"{name} is answering — this chat is theirs")
        history = [m for m in self.service.conversation_history if m.get("role") in ("user", "assistant")][-6:]
        context = "\n".join(f"{m['role']}: {str(m.get('content', ''))[:400]}" for m in history)
        if attachment_text:
            context += f"\n\nAttached:\n{attachment_text[:4000]}"
        try:
            report = run_specialist(name, user_text, context=context)
        except Exception as error:  # noqa: BLE001 - the owner must hear what went wrong
            report = f"{name} could not finish: {type(error).__name__}: {error}"
            self.failed = True
        reply = _as_conversation(visible_answer(report)) or f"{name} came back with nothing to say."
        self.emit("answer.delta", text=reply)
        self.agent_names.append(name)
        self.provider = self.provider or f"agent:{name}"
        self.service.add_message("user", user_text)
        self._save_reply(reply)
        return self._finish(reply)

    def _optimize_prompt(self, user_text: str, records: List[Dict[str, Any]], style: str) -> str:
        try:
            from prompt_optimizer import OPTIMIZER, assess
        except Exception:  # pragma: no cover - the optimizer is optional
            return user_text
        settings = OPTIMIZER.settings()
        if not settings.get("enabled"):
            return user_text
        if assess(user_text, settings).mode != "keep":
            self.emit("status", phase="route", text="Refining your request")
        recent = [m for m in self.service.conversation_history if m.get("role") in ("user", "assistant")]
        topic = str(recent[-1].get("content", ""))[:300] if recent else ""
        tab = ""
        try:
            import presence

            tab = presence.snapshot().get("tab") or ""
        except Exception:
            pass
        context = {"recent_topic": topic, "attachments": [str(r.get("name")) for r in records if r.get("name")],
                   "tab": tab, "style": style[:200]}
        try:
            result = OPTIMIZER.optimize(user_text, context, turn_id=self.turn_id)
        except Exception as error:  # noqa: BLE001 - never lose a turn to the optimizer
            self.emit("learning.note", text=f"Prompt optimizer skipped: {error}")
            return user_text
        if result.changed and settings.get("show_in_chat", True):
            self.emit("prompt.optimized", **result.event())
        return result.model_text if result.changed else user_text

    # --- attachments --------------------------------------------------------------

    def _load_attachments(self) -> Tuple[str, List[Dict[str, str]], List[Dict[str, Any]]]:
        if not self.attachments:
            return "", [], []
        import uploads

        texts: List[str] = []
        images: List[Dict[str, str]] = []
        records: List[Dict[str, Any]] = []
        for upload_id in self.attachments[:12]:
            loaded = uploads.model_input_for_upload(str(upload_id))
            if loaded is None:
                texts.append(f"[An attachment ({upload_id}) could not be found — it may have been deleted.]")
                continue
            texts.append(loaded["text"])
            images.extend(loaded.get("images", []))
            records.append(loaded["record"])
        return "\n\n".join(texts), images, records

    # --- quick answers ----------------------------------------------------------------

    def _voice_draft(self, user_text: str) -> Optional[Dict[str, Any]]:
        """Use the answer the voice pipeline wrote while the owner was speaking."""
        try:
            import voice_pipeline

            draft = voice_pipeline.take_draft(self.voice_session, user_text)
        except Exception:  # pragma: no cover - never lose a turn over a missing draft
            return None
        if not draft or not draft.get("text"):
            return None
        reply = str(draft["text"]).strip()
        self.provider = draft.get("provider") or "voice"
        self.model = draft.get("model") or ""
        self.mode = "fast"
        self.emit("status", phase="think", text="Answering from what it worked out while you spoke")
        self.emit("answer.delta", text=reply)
        self.service.add_message("user", user_text)
        self._save_reply(reply)
        return self._finish(reply)

    def _fast_path(self, user_text: str, model_text: Optional[str] = None) -> Optional[Dict[str, Any]]:
        from fast_response import FAST_SYSTEM_PROMPT, wants_escalation

        service = self.service
        lean: List[Dict[str, Any]] = [{"role": "system", "content": FAST_SYSTEM_PROMPT}]
        for message in service.conversation_history:
            content = message.get("content", "")
            if message.get("role") == "system" and content.startswith(service._PERSONALITY_PREFIX):
                lean.append({"role": "system", "content": content})
                break
        recent = [m for m in service.conversation_history if m.get("role") in ("user", "assistant")]
        for message in recent[-_FAST_CONTEXT_TURNS:]:
            lean.append({"role": message["role"], "content": message.get("content", "")})
        lean.append({"role": "user", "content": model_text or user_text})

        text, answered = self._stream_model(lean, smart=False)
        if answered is None:
            return None
        if not text.strip() or wants_escalation(text) or TOOL_REGISTRY.parse_tool_calls(text):
            self.emit("answer.reset")
            return None

        reply = visible_answer(text)
        service.add_message("user", user_text)
        reply = self._attach_generated(reply)
        self._save_reply(reply)
        return self._finish(reply)

    # --- the working loop -------------------------------------------------------------

    def _stream_model(self, history: List[Dict[str, Any]], smart: bool,
                      exclude: Optional[List[str]] = None) -> Tuple[str, Optional[str]]:
        """One model call, streamed. Returns (full text, provider) or ("", None) on failure."""
        from config import SETTINGS

        service = self.service
        filter_ = StreamFilter(
            on_answer=lambda t: self.emit("answer.delta", text=t),
            on_thought=lambda t: self.emit("thought.delta", text=t, source="plan"),
        )

        def on_event(event: Dict[str, Any]) -> None:
            kind = event.get("type")
            if kind == "provider":
                self.provider = event.get("name", "")
                self.model = event.get("model", "") or self._default_model(self.provider)
                label = self.model or self.provider
                self.emit("status", phase="think", text=f"{label} is thinking", provider=self.provider, model=self.model)
            elif kind == "thought":
                self.emit("thought.delta", text=event.get("text", ""), source="model")
            elif kind == "text":
                filter_.feed(event.get("text", ""))
            elif kind == "reset":
                if filter_.answer_chars:
                    self.emit("answer.reset")
                filter_.__init__(filter_.on_answer, filter_.on_thought)
            elif kind == "provider.unavailable":
                self._provider_problems[str(event.get("name", ""))] = str(event.get("reason", ""))
            elif kind == "attempt.failed":
                self._provider_problems.setdefault(str(event.get("name", "")), str(event.get("error", "")))

        router = service.router
        if not hasattr(router, "stream"):
            text, provider = router.chat(history)
            filter_.feed(text)
            filter_.finish()
            return text, provider
        try:
            # Identity 0 (Big Kahuna) links the model calls it plans to this turn (same thread).
            from identity0.provider import set_current_turn

            set_current_turn(self.turn_id)
        except Exception:  # pragma: no cover - the brain's bookkeeping never blocks a turn
            set_current_turn = None
        try:
            text, provider = router.stream(
                history, on_event, smart=smart,
                thinking=bool(getattr(SETTINGS, "show_thinking", True)),
                cancelled=self.cancelled,
                prefer=self.prefer_provider,
                exclude=exclude,
            )
        except ProviderError:
            if self.cancelled():
                return "", None
            raise
        finally:
            if set_current_turn is not None:
                set_current_turn("")
        filter_.finish()
        self.last_answer_chars = filter_.answer_chars
        self._announce_fallback(provider)
        return text, provider

    def _announce_fallback(self, used: Optional[str]) -> None:
        """Tell the owner, once, when the provider they picked did not answer."""
        wanted = self.prefer_provider
        if not wanted or not used or used == wanted or self._fallback_announced:
            return
        self._fallback_announced = True
        reason = self._provider_problems.get(wanted) or "it did not answer"
        self.emit("provider.fallback", wanted=wanted, used=used, reason=reason[:240])
        self.emit("learning.note", text=f"{wanted} could not answer ({reason[:120]}), so {used} answered instead.")

    @staticmethod
    def _default_model(provider: str) -> str:
        if provider == "gemini":
            try:
                from config import SETTINGS

                return SETTINGS.gemini_model
            except Exception:
                return ""
        return ""

    def _tool_loop(self, max_steps: int) -> str:
        service = self.service
        history = service.conversation_history
        auto_searched = False
        repairs = 0
        exclude: List[str] = []
        #: The longest answer-like text a model wrote before calling a tool. Models often write
        #: the whole answer and then add a tool call (save a note, look one thing up); the reset
        #: that hides the lead-in wiped that answer, and the final step said little or nothing
        #: (Request H9: "the text and the speech bubble disappear after a long time of thinking").
        written_before_tools = ""
        swarm_nudged = False

        for step in range(1, max_steps + 1):
            if self.cancelled():
                return "Stopped. Here is where things were left — ask me to continue any time."
            self.last_answer_chars = 0
            text, provider = self._stream_model(history, smart=True, exclude=exclude or None)
            if provider is None:
                return "Stopped."

            calls = TOOL_REGISTRY.parse_tool_calls(text) if service.enable_tools else []
            if not calls and service.enable_tools and "<tool_call>" in (text or "") and repairs < _MAX_REPAIRS:
                # The model tried to act but wrote a call nobody can read. Answering
                # "no usable answer" here dropped the owner's request on the floor.
                repairs += 1
                self.emit("answer.reset")
                self.emit("status", phase="think", text="That tool call was unreadable — asking for it again")
                history.append({"role": "assistant", "content": text})
                history.append({"role": "user", "_tool_results": True, "content": (
                    "Your tool call could not be read, so nothing ran. Write it again as exactly one block:\n"
                    "<tool_call>\nname: tool_name\narguments: {\"key\": \"value\"}\n</tool_call>\n"
                    "The arguments must be one JSON object. Write Windows paths with forward slashes "
                    "(C:/Users/name) or doubled backslashes.")})
                continue
            if not calls and not visible_answer(text) and repairs < _MAX_REPAIRS:
                repairs += 1
                self.emit("answer.reset")
                if (text or "").strip():
                    # Only thinking came back: ask the same model to finish.
                    self.emit("status", phase="think", text="Only a plan came back — asking for the answer")
                    history.append({"role": "assistant", "content": text})
                    history.append({"role": "user", "_tool_results": True,
                                    "content": "You wrote only your plan. Continue this same turn: act or answer now."})
                else:
                    exclude.append(provider)
                    self._provider_problems.setdefault(provider, "it sent back an empty reply")
                    self.emit("status", phase="think", text=f"{provider} sent back an empty reply — trying another model")
                continue
            if not calls:
                if (service.auto_web_search and not auto_searched and service._has_search_intent(text)):
                    auto_searched = True
                    self.emit("answer.reset")
                    self.emit("status", phase="tool", text="You mentioned checking — searching now")
                    results = TOOL_REGISTRY.call_tool("search_web", query=self._last_user_text(), engine="all", freshness="any")
                    history.append({"role": "assistant", "content": text})
                    history.append({"role": "user", "content": f"Tool results (auto-triggered because you announced research):\n{results}\n\nContinue this same turn and give the final answer now."})
                    continue
                if (self.mode_switches.get("mode") == "swarm" and not swarm_nudged
                        and "dispatch_agents" not in self.tools_used):
                    # Swarm mode answered alone. Models skip the swarm for anything they can answer from memory,
                    # which made the mode look like Normal; ask once for the parts to go to agents (Update 1, U5).
                    swarm_nudged = True
                    self.emit("answer.reset")
                    self.emit("status", phase="agents", text="Swarm — handing the parts to agents")
                    history.append({"role": "assistant", "content": text})
                    history.append({"role": "user", "_tool_results": True, "content": chat_modes_swarm_nudge()})
                    continue
                reply = visible_answer(text)
                if len(written_before_tools) >= 400 and len(reply) < 160 and written_before_tools not in reply:
                    self.emit("answer.reset")
                    reply = (written_before_tools + ("\n\n" + reply if reply else "")).strip()
                    self.emit("answer.delta", text=reply)
                if not reply:
                    self.failed = True
                    names = sorted(set(exclude + [provider] + list(self._provider_problems)))
                    tried = "; ".join(f"{n} — {self._provider_problems[n]}" if self._provider_problems.get(n) else n
                                      for n in names if n)
                    reply = (f"Nothing was done for this request. No model gave a usable answer ({tried}). "
                             "Ask again, or pick a different model in the dropdown.")
                reply = self._attach_generated(reply)
                self._save_reply(reply)
                return reply

            # A tool step. Anything already streamed was the lead-in, not the answer.
            if getattr(self, "last_answer_chars", 0):
                self.emit("answer.reset")
            narration = visible_answer(text)
            if narration:
                self.emit("thought", text=narration, source="narration")
                if len(narration) > len(written_before_tools):
                    written_before_tools = narration

            history.append({"role": "assistant", "content": text})
            outputs = []
            for name, arguments in calls[:8]:
                if self.cancelled():
                    break
                self.tools_used.append(name)
                try:
                    result = TOOL_REGISTRY.call_tool(name, **arguments)
                except Exception as error:  # noqa: BLE001 - one broken call must not end the turn
                    result = f"Error calling tool '{name}': {type(error).__name__}: {error}"
                outputs.append(f"Tool '{name}' returned:\n{result}")
                self._note_sources(arguments, result)
            self.emit("status", phase="think", text="Reviewing what the tools returned")

            follow_up: Dict[str, Any] = {
                "role": "user",
                "content": "Tool results:\n" + "\n\n".join(outputs)
                + "\n\nContinue this same turn: take the next step, or give the final answer if the task is done.",
                "_tool_results": True,
            }
            images = self.context.take_images()
            if images:
                follow_up["images"] = images
                follow_up["content"] += f"\n({len(images)} image(s) attached above for you to look at.)"
            history.append(follow_up)

        return self._forced_answer()

    def _forced_answer(self) -> str:
        service = self.service
        self.emit("status", phase="answer", text="Step budget reached — writing up what was found")
        service.conversation_history.append({
            "role": "system",
            "content": ("You have used the maximum number of tool steps for this turn. Do not request "
                        "more tools. Answer now: say what you did, what you established, and what is left."),
        })
        text, _provider = self._stream_model(service.conversation_history, smart=True)
        reply = visible_answer(text) or ("I ran out of steps before finishing. Ask me to continue and I "
                                         "will pick up from here.")
        reply = self._attach_generated(reply)
        self._save_reply(reply)
        return reply

    def _last_user_text(self) -> str:
        for message in reversed(self.service.conversation_history):
            if message.get("role") == "user" and not message.get("_tool_results"):
                return str(message.get("content", ""))[:500]
        return self.message[:500]

    # --- tidy up ------------------------------------------------------------------------

    def _compact_turn(self, start: int) -> None:
        """Shrink this turn's working messages once the answer exists.

        Tool results and screenshots were essential while working; carried into
        every later turn they would crowd out the conversation and resend
        megabytes of images. Keep a short record of each step instead.
        """
        history = self.service.conversation_history
        if start >= len(history):
            return
        for message in history[start:]:
            if message.get("images"):
                names = ", ".join(i.get("name") or i.get("mime", "image") for i in message["images"])
                message.pop("images", None)
                message["content"] = f"{message.get('content', '')}\n[Images were shown here: {names}]"
            if message.get("_tool_results"):
                content = message.get("content", "")
                if len(content) > _COMPACT_RESULT_CHARS:
                    message["content"] = content[:_COMPACT_RESULT_CHARS] + "\n… [tool output trimmed after this turn]"
                message.pop("_tool_results", None)

    def _attach_generated(self, reply: str) -> str:
        """Make sure pictures made this turn are part of the saved answer.

        The model often describes the picture without repeating its link, and
        the chat history is text — so after a reload the picture was gone.
        Missing images are appended as Markdown, and streamed to the live view.
        """
        missing = [(uid, name) for uid, name in self.generated_images if f"/api/uploads/{uid}" not in (reply or "")]
        if not missing:
            return reply
        addition = "\n\n" + "\n".join(f"![{name}](/api/uploads/{uid})" for uid, name in missing)
        self.emit("answer.delta", text=addition)
        return (reply or "") + addition

    # --- learning ------------------------------------------------------------------

    _STYLE_PREFIX = "[Learned preferences]"

    def _context_key(self) -> str:
        """What makes a cached answer reusable: personality and the model family answering."""
        try:
            from config import SETTINGS

            personality = (getattr(self.service, "personality", None) or {}).get("id", "default")
            provider = self.prefer_provider or SETTINGS.preferred_online_provider
            return f"{personality}|{provider}|{getattr(SETTINGS, 'gemini_model', '')}"
        except Exception:
            return "default"

    def _learning_before(self, user_text: str, records: List[Dict[str, Any]], fresh: bool) -> Dict[str, Any]:
        self.records = records
        try:
            from learning_hooks import before_turn

            hooks = before_turn(user_text, chat_id=getattr(self.service, "chat_id", ""),
                                context_key=self._context_key(), attachments=records)
        except Exception:
            return {}
        if fresh or self._in_command_zone():
            hooks["cache_hit"] = None  # a command is work to hand out again, never a remembered reply
        return hooks

    def _in_command_zone(self) -> bool:
        try:
            import command_zone

            return bool(command_zone.brief_for_chat(getattr(self.service, "chat_id", "")))
        except Exception:
            return False

    def _apply_style_hints(self, hints: str) -> None:
        service = self.service
        service.conversation_history = [
            m for m in service.conversation_history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith(self._STYLE_PREFIX))
        ]
        if hints.strip():
            service.conversation_history.append({"role": "system", "content": f"{self._STYLE_PREFIX}\n{hints.strip()}"})

    def _apply_custom_vocabulary(self) -> None:
        """Load the user's persistent custom vocabulary and inject it into the system prompt."""
        if load_custom_vocabulary is None:
            return
        try:
            vocab = load_custom_vocabulary()
        except Exception:
            return
        if not vocab:
            return
        service = self.service
        # Remove any existing vocabulary block
        service.conversation_history = [
            m for m in service.conversation_history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith("[Custom Vocabulary]"))
        ]
        # Format vocabulary for the model
        lines = ["[Custom Vocabulary]", "The following colloquial rules and lexicon replacements apply to this conversation:"]
        for key, value in vocab.items():
            lines.append(f"- {key} → {value}")
        lines.append("Apply these consistently in all responses.")
        service.conversation_history.append({"role": "system", "content": "\n".join(lines)})

    def _finish_cached(self, user_text: str, hit: Any) -> Dict[str, Any]:
        """Answer from the response cache — labelled as such, with a Refresh action in the UI."""
        self.emit("cache.hit", cached_at=getattr(hit, "cached_at", 0), similarity=getattr(hit, "similarity", 1.0))
        self.emit("status", phase="answer", text="Answered from memory")
        reply = str(getattr(hit, "reply", "") or "")
        self.emit("answer.delta", text=reply)
        self.service.add_message("user", user_text)
        self.service._append_assistant_response(reply)
        self.provider = f"cache ({getattr(hit, 'provider', '') or 'earlier answer'})"
        self.from_cache = True
        return self._finish(reply)

    def _grow_brain(self, reply: str, elapsed_ms: int) -> None:
        """Super learn: every turn feeds the knowledge graph and trains Nyx Core (both in the background)."""
        try:
            import nyx_core
            import super_brain

            super_brain.ingest_turn(self.user_text, reply, provider=self.provider or "", tools=self.tools_used)
            nyx_core.observe_async(turn_id=self.turn_id, message=self.user_text, reply=reply, mode=self.mode,
                                   escalated=self.escalated, provider=self.provider or "", model=self.model or "",
                                   tools=list(self.tools_used), ok=self.provider not in ("", "offline") and not self.cancelled(),
                                   latency_ms=float(elapsed_ms), from_cache=bool(getattr(self, "from_cache", False)))
        except Exception:  # pragma: no cover - learning never breaks a turn
            pass

    def _learning_after(self, reply: str, elapsed_ms: int) -> None:
        self._grow_brain(reply, elapsed_ms)
        if getattr(self, "from_cache", False):
            return
        try:
            from learning import TurnSummary
            from learning_hooks import after_turn

            summary = TurnSummary(
                turn_id=self.turn_id, chat_id=str(getattr(self.service, "chat_id", "")), message=self.user_text,
                mode=self.mode, escalated=self.escalated, provider=self.provider or "", model=self.model or "",
                agents=list(self.agent_names), skills=list(self.skill_ids), tools=list(self.tools_used),
                latency_ms=float(elapsed_ms), ok=self.provider not in ("", "offline") and not self.cancelled(),
                reply_chars=len(reply or ""),
            )
            after_turn(summary, reply, self._context_key(), attachments=self.records)
        except Exception:
            pass

    def _mark_not_done(self) -> None:
        """Leave a note after a turn that did not do what was asked (see FAILED_TURN_NOTE)."""
        history = self.service.conversation_history
        if not any(m.get("content") == FAILED_TURN_NOTE for m in history[-2:]):
            history.append({"role": "system", "content": FAILED_TURN_NOTE})

    def _note_sources(self, arguments: Any, result: Any) -> None:
        """Links a tool used or returned. fetch_webpage returns only page text, so its url argument counts too."""
        text = str(result or "")
        if isinstance(arguments, dict) and not text.startswith(("Error", "Blocked")):
            first = next((line.strip() for line in text.splitlines() if line.strip()), "")
            title = first.lstrip("# ").strip() if 3 <= len(first) <= 120 else ""
            for key in ("url", "link", "href"):
                value = arguments.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    self._source_texts.append(f"{title} — {value}" if title else value)
        if "http" in text:
            self._source_texts.append(text[:20000])

    def _save_reply(self, reply: str) -> None:
        """Save the answer with its sources, so the drop-down survives a reload (Request H15)."""
        try:
            import sources as sources_module

            self.sources = sources_module.extract(reply or "", *self._source_texts)
        except Exception:  # pragma: no cover - sources are a nicety
            self.sources = []
        service = self.service
        if self.sources:
            try:
                service._append_assistant_response(reply, extra={"sources": self.sources})
                return
            except TypeError:  # a service without extra (older fakes in tests)
                pass
        service._append_assistant_response(reply)

    def _finish(self, reply: str) -> Dict[str, Any]:
        if self.failed:
            self._mark_not_done()
        elapsed_ms = round((time.perf_counter() - self.started) * 1000)
        self._learning_after(reply, elapsed_ms)
        result = {
            "reply": reply,
            "provider": self.provider or "unknown",
            "model": self.model,
            "elapsed_ms": elapsed_ms,
            "chat_id": self.service.chat_id,
            "turn_id": self.turn_id,
            "tools": self.tools_used,
            "stopped": self.cancelled(),
            "sources": self.sources,
        }
        self.emit("done", **result)
        return result

    def _finish_offline(self, reason: str) -> Dict[str, Any]:
        message, _ = self.service._offline_response(self.message, reason=reason)
        try:
            import super_brain

            # No model reachable: Nyx Core answers from what it has already learned.
            memories = [m for m in super_brain.BRAIN.recall(self.user_text or self.message, limit=4) if m["score"] > 1.5]
            if memories:
                message += "\n\nFrom what I've already learned, this may help:\n" + "\n".join(
                    f"- {m['text'][:300]} _(from {m['source']})_" for m in memories)
                self.emit("learning.note", text=f"Answered from Nyx's own memory ({len(memories)} memories) while models are unreachable.")
        except Exception:  # pragma: no cover
            pass
        self.emit("answer.reset")
        self.emit("answer.delta", text=message)
        self.service._append_assistant_response(message)
        self.provider = "offline"
        self.failed = True
        return self._finish(message)
