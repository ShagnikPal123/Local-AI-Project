"""Chat service that orchestrates conversations with the selected AI provider."""

from __future__ import annotations
from datetime import datetime
import hashlib
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from attributes import get_attribute
from chat_sessions import ChatSessionStore
from fast_response import (
    FAST_SYSTEM_PROMPT,
    FastResponsePolicy,
    SpeedMode,
    wants_escalation,
)
from knowledge import get_knowledge
from memory import MemoryStore
from personalities import PersonalityNotFoundError, resolve_personality
from providers.base import ProviderError
from question_cards import FORMAT_RULE as QUESTION_RULE
from rag_memory import RagMemory
from router import Router
from speech_patterns import SpeechPatternStore
from tools import TOOL_REGISTRY


# Directive blocks that callers prepend to a message before it reaches the model:
# "[MULTI-APPROACH PROTOCOL: AUTO]" from approaches.build_multi_approach_prompt,
# "[CODING MODE] ..." from agent_pool, and the research-budget line from
# multi_mode_chat. A block runs from a leading [BRACKETED HEADING] to the next
# blank line.
_DIRECTIVE_PREFIX = re.compile(
    r"\A(?:\[[A-Z][^\]\n]*\][^\n]*(?:\n(?![ \t]*\n)[^\n]*)*"
    r"|Research time budget:[^\n]*)"
    r"[ \t]*\n[ \t]*\n"
)


def split_directives(message: str) -> Tuple[str, str]:
    """Separate prepended directive blocks from the text the user actually typed.

    These blocks are instructions addressed to the assistant, not part of the
    question, so they belong in a system message. Concatenating them onto the
    user's text polluted stored history, memory, and RAG context — and, most
    visibly, the offline intent matcher, where "[MULTI-APPROACH ..." contains the
    substring "app" and therefore matched the "help me build an app" branch for
    every single message, whatever was asked.

    Returns:
        A tuple of (directives, user_text). Either may be empty.
    """
    remaining = message or ""
    directives: List[str] = []
    while True:
        match = _DIRECTIVE_PREFIX.match(remaining)
        if match is None:
            break
        directives.append(match.group(0).strip())
        remaining = remaining[match.end():]
    return "\n\n".join(directives), remaining.strip()


class ChatService:
    """Coordinate conversation state, routing, memory, and tool execution."""

    _EMPTY_MEMORY_CONTEXT = "No personal memory entries yet."
    _MEMORY_PREFIX = "Personal memory:"
    _PERSONALITY_PREFIX = "[Personality:"
    _DIRECTIVE_PREFIX_LABEL = "[Response directives]"
    _SPEECH_PREFIX = "Speech style learned from the user:"
    _DEFAULT_MAX_TOOL_ITERATIONS = 5
    # User messages longer than this are auto-compressed to a file the model reads.
    _DEFAULT_LARGE_PROMPT_CHARS = 12_000
    _KNOWLEDGE_PREFIX = "[General Knowledge]"
    # Phrases that signal the model intends to research but forgot to emit a tool call.
    _SEARCH_INTENT_PATTERNS = (
        "let me search", "i'll search", "i will search", "let me look up",
        "i'll look up", "i will look up", "let me research", "i'll research",
        "i will research", "let me check", "i'll check", "i will check",
        "searching for", "looking this up", "let me find", "i'll find",
        "i will find", "let me verify", "i'll verify", "i will verify",
        "let me fetch", "i'll fetch", "i will fetch", "let me open",
        "let me get the latest", "i'll get the latest", "let me find out",
        "i'll find out", "let me investigate", "i'll investigate",
        "let me double-check", "i'll double-check", "let me confirm",
        "i'll confirm", "let me look", "i'll look", "let me browse",
        "i'll browse", "let me pull up", "i'll pull up", "let me gather",
        "i'll gather", "let me consult", "i'll consult", "let me read",
        "i'll read", "let me check the source", "let me check sources",
    )

    def __init__(
        self,
        system_prompt: Optional[str] = None,
        enable_tools: bool = True,
        attribute_id: Optional[str] = None,
        memory_path: Optional[str] = None,
        web_access: bool = True,
        chat_store: Optional[ChatSessionStore] = None,
        chat_id: Optional[str] = None,
        personality_id: Optional[str] = None,
        personality_text: Optional[str] = None,
        speech_patterns_path: Optional[str] = None,
        large_prompt_chars: int = _DEFAULT_LARGE_PROMPT_CHARS,
        interim_callback: Optional[Callable[[str], None]] = None,
    ):
        """Initialize the chat service.

        Args:
            large_prompt_chars: Messages longer than this are written to a file
                and replaced by a pointer the model reads (auto-compression).
            interim_callback: Optional callback receiving "thinking" milestones
                (searching, reading, verifying) for live status in the App/Web UI.
        """
        self.router = Router(web_access=web_access)
        self.memory = MemoryStore(path=memory_path)
        self.chat_store = chat_store or ChatSessionStore(memory_store=self.memory)
        # A service can be bound to one stored chat (a browser-style chat tab) or,
        # by default, follow whichever chat is active.
        self.chat_id = chat_id if self.chat_store.exists(chat_id) else self.chat_store.ensure_active()
        self.auto_web_search = web_access
        self.conversation_history: List[Dict[str, str]] = []
        self.enable_tools = enable_tools
        # A bounded loop prevents a provider from requesting tools indefinitely.
        self.max_tool_iterations = self._DEFAULT_MAX_TOOL_ITERATIONS
        # Auto by default: no setting change should be needed for good latency.
        self.speed_policy = FastResponsePolicy()
        self.speed_mode = SpeedMode.AUTO
        self.attribute_id = attribute_id
        self.speech = SpeechPatternStore(path=speech_patterns_path)
        self.rag = RagMemory(memory=self.memory)
        self.personality: Optional[Dict[str, str]] = None
        self.large_prompt_chars = large_prompt_chars
        self.interim_callback = interim_callback
        self._turn_lock = threading.RLock()
        self._custom_system_prompt = system_prompt is not None
        self.system_prompt = system_prompt or self._default_system_prompt()

        # Add base system prompt as the first message
        self.conversation_history.append({"role": "system", "content": self.system_prompt})

        memory_context = self.memory.build_context_prompt()
        if memory_context and memory_context != self._EMPTY_MEMORY_CONTEXT:
            self.conversation_history.append({"role": "system", "content": memory_context})

        if attribute_id is not None:
            self.add_attribute_guidance(attribute_id)

        if personality_id is not None or personality_text is not None:
            self.set_personality(resolve_personality(personality_id, personality_text))

        speech_context = self.speech.build_context_prompt()
        if speech_context:
            self.conversation_history.append({"role": "system", "content": speech_context})

        knowledge_context = get_knowledge().build_context_prompt()
        if knowledge_context:
            self.conversation_history.append({"role": "system", "content": knowledge_context})

        # Reopening a chat tab (after a restart, or on another device) continues
        # that conversation rather than starting the model from nothing.
        if chat_id and self.chat_store.exists(chat_id):
            stored = self.chat_store.messages(chat_id)
            # A compacted chat (context_budget.py) continues from its summary, not from the full old text.
            compaction = self.chat_store.compaction(chat_id) if hasattr(self.chat_store, "compaction") else {}
            if compaction:
                from context_budget import SUMMARY_PREFIX

                self.conversation_history.append({"role": "system", "content": f"{SUMMARY_PREFIX}\n{compaction['summary']}"})
                conversational = [m for m in stored if m.get("role") in ("user", "assistant")]
                stored = conversational[compaction["upto"]:]
            for message in stored[-40:]:
                if message.get("role") in ("user", "assistant", "system"):
                    self.conversation_history.append(
                        {"role": message["role"], "content": str(message.get("content", ""))}
                    )

    @staticmethod
    def _capability_note() -> str:
        """Tell the model its own parallel-work budget.

        Asked "how many agents can you run?", the model had no idea and would
        either invent a number or say it could not. The ceiling is a real setting
        the user controls in Power, so the assistant should know it and answer
        honestly. Stated as a limit rather than a headcount: nothing is running
        until a task needs it, and the model should spend under the cap, not up
        to it.

        Never allowed to break a chat turn - a missing governor is not a reason
        to fail a conversation.
        """
        try:
            from resource_governor import GOVERNOR

            ceiling = GOVERNOR.ceiling()
            allowed = getattr(ceiling, "max_agents", None)
            if allowed is None and isinstance(ceiling, dict):
                allowed = ceiling.get("max_agents")
            if not allowed:
                return ""
            return (
                f"\nParallel work: you may enlist up to {allowed} helper agent(s) at once, "
                "a limit the user sets under Power. Use as few as the task needs; "
                "that number is a ceiling, not a target. If asked, state it plainly."
            )
        except Exception:
            return ""

    @staticmethod
    def _environment_note() -> str:
        """Facts about this machine the model would otherwise have to guess.

        "Put it on my desktop" needs to know where the desktop is (OneDrive often
        moves it); "is my GPU hot?" needs to know there is one. Cheap reads only —
        this runs whenever the prompt is rebuilt — and never raises.
        """
        import os
        import platform

        lines: List[str] = []
        try:
            now = datetime.now().astimezone()
            lines.append(f"Local time: {now.strftime('%A %B %d, %Y %H:%M')} ({now.tzname()})")
        except Exception:
            pass
        try:
            lines.append(f"Computer: {platform.system()} {platform.release()} (build {platform.version()}), "
                         f"user '{os.getenv('USERNAME') or os.getenv('USER') or 'unknown'}'")
        except Exception:
            pass
        try:
            home = Path.home()
            folders = {"Home": home, "Desktop": home / "Desktop", "Documents": home / "Documents",
                       "Downloads": home / "Downloads", "Pictures": home / "Pictures"}
            if platform.system() == "Windows":
                import winreg

                key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
                names = {"Desktop": "Desktop", "Documents": "Personal", "Pictures": "My Pictures",
                         "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}"}
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    for label, value_name in names.items():
                        try:
                            folders[label] = Path(os.path.expandvars(winreg.QueryValueEx(key, value_name)[0]))
                        except OSError:
                            continue
            lines.append("Folders: " + "; ".join(f"{k} = {v}" for k, v in folders.items()))
        except Exception:
            pass
        try:
            from device_profile import get_device_profile

            profile = get_device_profile()
            gpu = f", GPU {profile.gpu_name} ({profile.vram_gb} GB)" if profile.gpu_name else ""
            lines.append(f"Hardware: {profile.cpu_name}, {profile.cpu_cores} threads, {profile.ram_gb} GB RAM{gpu}")
        except Exception:
            pass
        try:
            import paths

            lines.append(f"Nyx data folder: {paths.DATA_DIR}")
        except Exception:
            pass
        return "\n".join(lines)

    @staticmethod
    def _team_note() -> str:
        try:
            from agent_runtime import roster_summary

            return roster_summary()
        except Exception:
            return ""

    @staticmethod
    def _model_roles_note() -> str:
        """Which model does which job, so the assistant uses them and says so."""
        try:
            from model_roles import MODEL_ROLES

            return MODEL_ROLES.summary_for_prompt()
        except Exception:
            return ""

    @staticmethod
    def _permissions_note() -> str:
        """Tell the model what the owner has restricted, so it does not keep trying."""
        try:
            from permissions import POLICY

            restricted = {c: m for c, m in POLICY.snapshot()["categories"].items() if m != "allow"}
        except Exception:
            return ""
        if not restricted:
            return "Permissions: the owner has not restricted anything — every tool below is available."
        listed = ", ".join(f"{c} ({m})" for c, m in sorted(restricted.items()))
        return (f"Permissions set by the owner: {listed}. 'ask' pauses for their approval; 'block' "
                "refuses — say so plainly instead of trying a workaround.")

    def _default_system_prompt(self) -> str:
        """The assistant's standing instructions: who it is, how it works, what it can reach."""
        tools_section = ""
        if self.enable_tools:
            tools_section = f"""

## Tools
You can act on this computer and the web through tools — you genuinely can, so never say you are unable to do something a tool below provides, and never claim you did something you did not do with a tool. When a question needs current or verified information, use search_web first and answer from the sources.

To use a tool, write exactly:

<tool_call>
name: tool_name
arguments: {{"param1": "value1", "param2": "value2"}}
</tool_call>

The app runs it and sends the result back. You may write several <tool_call> blocks in one message when the steps do not depend on each other. Before a tool call, write one short line inside <thinking>...</thinking> saying what you are about to do and why; the user sees it live as your thought process. Never end a message with an intention to act — act, then answer.

If the user asks to change model or provider, or to go local/offline, call switch_model. Call it with no arguments to report which provider is active.

{TOOL_REGISTRY.format_tools_for_prompt()}
"""

        team = self._team_note()
        team_section = f"\n\n## Your team\n{team}" if team else ""
        account = self._account_note()
        account_section = f"\n\n## This account\n{account}" if account else ""
        roles = self._model_roles_note() if self.enable_tools else ""
        roles_section = (
            f"\n\n{roles}\nWhen a tool result starts with [Model · job], name that model in your reply "
            "(for example: \"NVIDIA Llama 3.2 Vision checked the image\")."
        ) if roles else ""

        return f"""You are Nyx Ichos, a capable, proactive AI assistant that runs on the user's own Windows PC. You were created by Shagnik. You lead a team of specialist agents as their Manager.
{self._capability_note()}

## How you work
1. Understand first: work out what the user actually wants, the constraints, and what "done" looks like. Ask one focused question only when you genuinely cannot proceed; otherwise make a sensible assumption and say what you assumed.
2. Plan multi-step work, then carry it out step by step, checking each result. If a step fails, read the error, adapt, and try another way before giving up — then explain what happened.
3. Verify changes you make — read back a file you wrote, take a screenshot after clicking, list what you moved, confirm an email was sent.
4. Delegate to a specialist with delegate_task when their expertise clearly improves the result; you still own the final answer. Handle simple things yourself.
5. Skills: matching skills are attached automatically. Use search_skills to find others, and create_temp_skill when a task needs a focused procedure that does not exist yet.
6. Be honest: separate what you checked from what you believe, cite sources for current facts, and admit uncertainty.
7. Answer in clear Markdown — lead with the answer, keep it as short as the question allows, use lists and code blocks where they help. Never show tool-call syntax in an answer.
8. Do what the latest message asks — only that. An earlier request that failed, that you declined, or that was answered with "Nothing was done" is not a to-do list: carry it out only when the latest message asks for it again ("try again", "please", "do it"). A short command like "switch to nvidia" means just that command.
9. If you cannot do what was asked, say so plainly and stop. Never substitute a different task for the one requested.
10. To show a graph, write a fenced block with the language `chart` containing only JSON — data series:
   {{"type": "line" | "bar" | "scatter" | "area", "title": "...", "x": [...], "series": [{{"name": "...", "values": [...]}}], "xLabel": "...", "yLabel": "..."}}
   or a math function: {{"type": "function", "title": "...", "expressions": ["sin(x)", "x^2/10"], "from": -10, "to": 10}}.
   The chat draws it. Python goes in ```python blocks; the chat cannot run it, so never claim output you did not get from a tool.
{QUESTION_RULE}{account_section}

## This computer
{self._environment_note()}
{self._permissions_note()}{team_section}{roles_section}{tools_section}"""

    @staticmethod
    def _account_note() -> str:
        """Which account this engine works in and what the owner made it for (local_accounts)."""
        try:
            import local_accounts

            return local_accounts.purpose_note()
        except Exception:  # noqa: BLE001 - an account note is context, never a reason a turn fails
            return ""

    def add_attribute_guidance(self, attribute_id: str) -> None:
        """Append safe attribute guidance as a separate system message."""
        attribute = get_attribute(attribute_id)
        guidance = (
            f"[Attribute: {attribute.display_name}]\n"
            f"{attribute.system_guidance}"
        )

        if any(
            msg.get("role") == "system" and msg.get("content") == guidance
            for msg in self.conversation_history
        ):
            return

        insert_at = 1 if len(self.conversation_history) > 0 else 0
        self.conversation_history.insert(insert_at, {"role": "system", "content": guidance})

    def set_personality(self, personality: Optional[Dict[str, str]]) -> str:
        """Apply a personality record as a system message, replacing any previous one.

        Args:
            personality: A personality dict with at least 'id' and 'system_guidance'.

        Returns:
            A confirmation message describing the active personality.
        """
        if personality is None:
            return "No personality set."

        guidance = (
            f"[Personality: {personality.get('display_name', personality.get('id', 'custom'))}]\n"
            f"{personality.get('system_guidance', '')}"
        )

        # Replace any existing personality system message.
        self.conversation_history = [
            msg for msg in self.conversation_history
            if not (msg.get("role") == "system" and msg.get("content", "").startswith(self._PERSONALITY_PREFIX))
        ]
        insert_at = 1 if len(self.conversation_history) > 0 else 0
        self.conversation_history.insert(insert_at, {"role": "system", "content": guidance})
        self.personality = personality
        return f"Personality set to: {personality.get('display_name', personality.get('id', 'custom'))}"

    def _apply_directives(self, directives: str) -> None:
        """Install this turn's directive blocks as a single system message.

        Replaced rather than appended so a long conversation does not accumulate
        one copy of the protocol preamble per turn. Mirrors how set_personality
        manages its own system message.
        """
        self.conversation_history = [
            msg for msg in self.conversation_history
            if not (msg.get("role") == "system"
                    and msg.get("content", "").startswith(self._DIRECTIVE_PREFIX_LABEL))
        ]
        insert_at = 1 if self.conversation_history else 0
        self.conversation_history.insert(
            insert_at,
            {"role": "system", "content": f"{self._DIRECTIVE_PREFIX_LABEL}\n{directives}"},
        )

    def get_personality(self) -> Optional[Dict[str, str]]:
        """Return the currently active personality record, if any."""
        return self.personality
    def set_personality_from_id(self, personality_id: str) -> str:
        """Resolve a personality ID (or 'custom') and apply it.

        Raises:
            PersonalityNotFoundError: if the personality ID is unknown.
        """
        personality = resolve_personality(personality_id)
        return self.set_personality(personality)

    def learn_speech_patterns(self, messages: Optional[List[str]] = None) -> str:
        """Learn the user's speaking style from recent messages and refresh context.

        Args:
            messages: Optional explicit message list; defaults to user messages in history.

        Returns:
            A summary of what was learned.
        """
        if messages is None:
            messages = [
                msg["content"] for msg in self.conversation_history
                if msg.get("role") == "user"
            ]
        patterns = self.speech.learn(messages)
        self._refresh_speech_context()
        if not patterns:
            return "No speech patterns learned (need at least one user message)."
        return f"Learned speech patterns from {patterns.get('sample_count', 0)} message(s)."

    def get_speech_patterns(self) -> Dict[str, Any]:
        """Return the currently learned speech patterns."""
        return self.speech.get_patterns()

    def clear_speech_patterns(self) -> str:
        """Clear learned speech patterns and refresh context."""
        count = self.speech.clear()
        self._refresh_speech_context()
        return f"Cleared {count} speech pattern sample(s)."

    def rag_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the most relevant memory entries for a query (RAG)."""
        return self.rag.search(query, limit=limit)

    def _refresh_speech_context(self) -> None:
        """Refresh the speech-style system message without duplicating entries."""
        speech_context = self.speech.build_context_prompt()
        self.conversation_history = [
            msg for msg in self.conversation_history
            if not (msg.get("role") == "system" and msg.get("content", "").startswith(self._SPEECH_PREFIX))
        ]
        if speech_context:
            self.conversation_history.append({"role": "system", "content": speech_context})

    def _emit_interim(self, message: str) -> None:
        """Report a live thinking milestone to the UI (App/Web) if a callback is set."""
        if self.interim_callback is not None:
            try:
                self.interim_callback(message)
            except Exception:  # pragma: no cover - callbacks must never break the turn
                pass

    def _save_large_prompt(self, text: str) -> Path:
        """Write an oversized prompt to a file the model can read with read_file."""
        folder = Path("attachments")
        folder.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
        path = folder / f"prompt_{digest}.md"
        if not path.exists():
            path.write_text(text, encoding="utf-8")
        return path

    def search_knowledge(self, query: str, limit: int = 5) -> str:
        """Search the permanent general knowledge base and return readable text."""
        return get_knowledge().search_text(query, limit=limit)


    def remember(self, key: str, value: str) -> str:
        """Persist a personal fact or preference in the local memory store."""
        self.memory.remember(key, value)
        self.rag.mark_dirty()
        self._refresh_memory_context()
        return f"Stored: {key} = {value}"

    def set_web_access(self, enabled: bool) -> str:
        """Toggle automatic web search and online provider access."""
        self.auto_web_search = enabled
        self.router.set_web_access(enabled)
        state = "enabled" if enabled else "disabled"
        return f"Web access {state}."

    def get_web_access_status(self) -> Dict[str, bool]:
        """Return permission and current network reachability."""
        return self.router.web_access_status()

    def remember_important(self, topic: str, content: str) -> str:
        """Store an explicitly selected important memory and refresh context."""
        self.memory.remember_important(topic, content)
        self.rag.mark_dirty()
        self._refresh_memory_context()
        return f"Stored important memory: {topic}"

    def remove_important_memory(self, topic: str) -> str:
        removed = self.memory.remove_important(topic)
        self.rag.mark_dirty()
        self._refresh_memory_context()
        return f"Removed important memory: {topic}" if removed else f"No memory found for: {topic}"

    def clear_important_memory(self) -> str:
        count = self.memory.clear_important()
        self.rag.mark_dirty()
        self._refresh_memory_context()
        return f"Cleared {count} important memories."

    def record_online_result(self, provider: str, prompt: str, result: str) -> str:
        """Save a curated online result for later prompting and review."""
        self.memory.record_online_result(provider=provider, prompt=prompt, result=result)
        self.rag.mark_dirty()
        self._refresh_memory_context()
        return f"Recorded online result from {provider}"

    def _refresh_memory_context(self) -> None:
        """Refresh the memory system-message context without duplicating entries."""
        memory_context = self.memory.build_context_prompt()
        if memory_context == self._EMPTY_MEMORY_CONTEXT:
            return

        for idx, message in enumerate(self.conversation_history):
            if message.get("role") == "system" and message.get("content", "").startswith(self._MEMORY_PREFIX):
                self.conversation_history[idx] = {"role": "system", "content": memory_context}
                return

        self.conversation_history.insert(1, {"role": "system", "content": memory_context})

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the conversation history."""
        self.conversation_history.append({"role": role, "content": content})

    @staticmethod
    def _mentions(text: str, *words: str) -> bool:
        """Return whether any whole word appears in text.

        Word-anchored on purpose. The previous substring test matched "app"
        inside "approach" and "hi" inside "this", so almost any message landed
        on the wrong canned branch.
        """
        return re.search(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", text) is not None

    def _offline_response(self, user_message: str, reason: str = "") -> Tuple[str, str]:
        """Explain that no provider answered, and say what to do about it.

        The old version guessed a topic and returned an upbeat canned sentence
        with no hint that anything was wrong. A misconfiguration therefore looked
        exactly like a normal reply, which is how a missing API key went
        undiagnosed for a long time. Configuration problems now lead, and the
        router's own diagnostic is passed through instead of discarded.
        """
        cleaned = (user_message or "").strip()
        lowered = cleaned.lower()
        detail = (reason or "").strip()

        if detail:
            message = (
                "I couldn't reach a model provider, so this is not a real answer.\n\n"
                f"Reason: {detail}\n\n"
                "Fix it by adding a working key to .env.local (or Settings -> Keys), "
                "or by starting Ollama for local inference. Run /doctor for the full status."
            )
            return message, "offline"

        if not cleaned:
            message = (
                "I'm in offline mode right now, but I can still help. "
                "Send me the task, and I'll turn it into the next clear step."
            )
        elif self._mentions(lowered, "hello", "hi", "hey"):
            message = (
                "Hello! I'm Nyx Ichos, and I'm currently in offline mode. "
                "I can still help you with a quick plan, a draft, or the next debugging step."
            )
        elif self._mentions(lowered, "debug", "error", "traceback", "bug", "failure"):
            message = (
                "I'm in offline mode, but I can help debug this locally. Share the exact error or traceback, "
                "and the next step is to isolate the likely root cause and plan the smallest clean fix."
            )
        elif self._mentions(lowered, "plan", "build", "make", "create", "app", "project"):
            message = (
                "I can help you build this step by step. Let's define the goal, isolate the minimum working version, "
                "and add one verified feature at a time so it remains easy to test."
            )
        else:
            message = (
                "I'm in offline mode right now, so I can't reach a live model provider. "
                "Tell me your task and I'll provide a structured plan or offline debug path."
            )

        return message, "offline"

    def _request_response(self, user_message: str) -> Tuple[str, str]:
        '''Ask the router for a response and fall back safely when unavailable.'''
        try:
            return self.router.chat(self.conversation_history)
        except ProviderError as error:
            # The router builds a precise diagnostic naming every provider it
            # tried and why each failed. Swallowing it left the user staring at
            # a cheerful canned sentence with no way to tell that anything had
            # gone wrong, let alone what.
            self._log_provider_failure(error)
            return self._offline_response(user_message, reason=str(error))

    @staticmethod
    def _log_provider_failure(error: Exception) -> None:
        """Record a total routing failure. Logging must never break a chat turn."""
        try:
            from event_log import warn as log_warn

            log_warn(f"no provider answered: {str(error)[:200]}", "chat_service")
        except Exception:
            pass

    def _has_search_intent(self, text: str) -> bool:
        '''Return True when the model said it will research but emitted no tool call.

        This is the "bot stops talking" failure mode: the model announces a search
        and then goes silent. We detect the intent so the loop can auto-trigger the
        search tool and keep the turn alive.
        '''
        lowered = (text or "").lower()
        return any(pattern in lowered for pattern in self._SEARCH_INTENT_PATTERNS)

    def _auto_trigger_search(self, user_message: str) -> str:
        '''Run the search_web tool automatically when the model announced research.

        Returns the tool result text, or an empty string when the tool is unavailable.
        '''
        if not self.enable_tools:
            return ""
        tool = TOOL_REGISTRY.get_tool("search_web")
        if tool is None:
            return ""
        try:
            return tool.handler(query=user_message, engine="all", freshness="any")
        except Exception as error:  # pragma: no cover - network dependent
            return f"Automatic search failed: {error}"

    def _run_tools(self, tool_calls: List[Tuple[str, Dict]]) -> str:
        '''Execute parsed tool calls and format their results for the next turn.'''
        results = []
        for tool_name, arguments in tool_calls:
            self._emit_interim(f"Running tool {tool_name}...")
            result = TOOL_REGISTRY.call_tool(tool_name, **arguments)
            results.append(f"Tool '{tool_name}' returned:\n{result}")

        return "\n\n".join(results)

    def _append_assistant_response(self, response: str, extra: Optional[Dict[str, Any]] = None) -> None:
        '''Persist an assistant response in both context and the active chat.'''
        self.add_message("assistant", response)
        if extra:
            self.chat_store.append("assistant", response, chat_id=self.chat_id, extra=extra)
        else:
            self.chat_store.append("assistant", response, chat_id=self.chat_id)

    def chat(self, user_message: str, attribute_id: Optional[str] = None) -> Tuple[str, str]:
        """Send a message and get a response, handling tool calls and multi-route verification.

        Args:
            user_message: The user's input.
            attribute_id: Optional attribute ID to add safe guidance for this turn.

        Returns:
            A tuple of (response_text, provider_name).
        """
        if attribute_id is not None:
            self.add_attribute_guidance(attribute_id)

        # The CLI and the agent pool prepend directive blocks ("[MULTI-APPROACH
        # PROTOCOL: AUTO]", "[CODING MODE] ...") to the text. They are guidance
        # for the assistant, not part of the question, so they belong in a system
        # message. Splitting here fixes every caller at once.
        directives, stripped = split_directives(user_message)
        if directives:
            self._apply_directives(directives)
            if stripped:
                user_message = stripped

        # Persist the full input, but auto-compress oversized prompts into a
        # single file the model reads instead of flooding the context window.
        self.chat_store.append("user", user_message, chat_id=self.chat_id)
        turn_message = user_message
        if self.enable_tools and len(user_message) > self.large_prompt_chars:
            path = self._save_large_prompt(user_message)
            turn_message = (
                f"Your full input ({len(user_message):,} chars) was saved to "
                f"{path}. Read it with the read_file tool before answering."
            )
            self.add_message(
                "system",
                f"[Large input compressed to {path} — read it before answering]",
            )
            self._emit_interim(f"Large input saved to {path} for reading...")

        # Fast path: a simple turn does not need the 8KB tool-schema prompt or the
        # tool loop. Decided per turn and escalated automatically if the model says
        # the cheap path cannot serve it, so no setting change is ever required.
        # Skills auto-attach when a turn matches their triggers, and cost nothing
        # otherwise (ROADMAP U3). No slash command, no setting.
        self._attach_skills(user_message)

        decision = self.speed_policy.decide(user_message, self.speed_mode)
        if decision.fast:
            self._emit_interim(f"Fast path ({decision.reason})...")
            fast_result = self._try_fast_response(user_message)
            if fast_result is not None:
                return fast_result
            self._emit_interim("Fast path escalated — using the full pipeline...")

        self.add_message("user", turn_message)

        iteration = 0
        final_response = None
        final_provider = None
        # True when the last thing we did was hand tool output back to the model.
        # If the loop ends in that state the model still owes the user an answer,
        # so we must run a synthesis pass rather than returning the tool call text.
        answer_owed = False
        # Auto-search is a recovery path, not a loop. Without this guard a model
        # that keeps narrating intent without emitting a call re-runs the identical
        # query on every iteration and burns the whole budget on duplicates.
        auto_searched = False

        while iteration < self.max_tool_iterations:
            iteration += 1
            response, provider = self._request_response(user_message)
            final_response, final_provider = response, provider
            tool_calls = TOOL_REGISTRY.parse_tool_calls(response) if self.enable_tools else []
            if not tool_calls:
                # The model announced research but forgot the tool call: auto-trigger
                # the search so the turn continues instead of dying silently.
                if (
                    self.auto_web_search
                    and not auto_searched
                    and self._has_search_intent(response)
                ):
                    self._emit_interim("Detected research intent — searching automatically...")
                    tool_results = self._auto_trigger_search(user_message)
                    auto_searched = True
                    if tool_results:
                        self.add_message(
                            "user",
                            f"Tool results (auto-triggered because you announced research):\n{tool_results}\n\nContinue this same turn. Provide the final answer now with verified facts and sources.",
                        )
                        answer_owed = True
                        continue
                self._append_assistant_response(response)
                answer_owed = False
                break
            tool_results = self._run_tools(tool_calls)
            self.add_message(
                "user",
                f"Tool results:\n{tool_results}\n\nContinue this same turn. Provide the final answer now with verified facts and sources.",
            )
            answer_owed = True

        # The loop can exit with the budget spent while the model still owes an
        # answer. Previously that path returned the raw tool-call text, which the
        # check below rewrote into a generic failure — the turn died even though
        # the tools had succeeded, and nothing was persisted, so the next turn had
        # no record of any of it. Force one final tool-free pass instead.
        if answer_owed:
            final_response, final_provider = self._synthesize_final_answer(
                user_message, final_provider
            )

        # Belt and braces: never surface raw tool syntax to the user.
        if final_response and TOOL_REGISTRY.parse_tool_calls(final_response):
            stripped = self._strip_tool_calls(final_response)
            final_response = stripped or (
                "I gathered the information but could not turn it into an answer. "
                "Ask again and I will retry."
            )
            self._append_assistant_response(final_response)

        # Curiosity reflection: extract topics for future autonomous learning
        self._curiosity_reflection(user_message, final_response or "")

        return final_response, final_provider

    _SKILL_PREFIX = "[Skills active for this turn]"

    def _attach_skills(self, user_message: str) -> None:
        """Add instructions for whichever skills this turn matches.

        Replaces any previous turn's skill message rather than stacking, so a
        long conversation does not accumulate every skill it ever touched.
        Never raises: a skill library problem must not stop a chat.
        """
        self.conversation_history = [
            m for m in self.conversation_history
            if not (m["role"] == "system" and m["content"].startswith(self._SKILL_PREFIX))
        ]
        try:
            from skills import SKILL_STORE

            context = SKILL_STORE.build_context(user_message)
            chosen = SKILL_STORE.select_for(user_message) if context else []
        except Exception:
            return []
        if context:
            self.conversation_history.append({"role": "system", "content": context})
        # Reported so the UI can show which skills shaped this answer.
        return [
            {"id": s.skill_id, "name": s.name, "source": s.source, "temp": s.source == "temp"}
            for s in chosen
        ]

    def _try_fast_response(self, user_message: str) -> Optional[Tuple[str, str]]:
        """Answer a simple turn in one cheap call.

        Returns None when the fast path cannot serve the turn, in which case the
        caller falls through to the full pipeline. Nothing is written to history
        on that path, so escalation leaves no trace of the abandoned attempt.
        """
        # The personality has to come along. This path skips the full history on
        # purpose - that is what makes it cheap - but skipping the personality too
        # meant a chosen voice silently did nothing on exactly the short, simple
        # turns most likely to take this route. The setting looked broken because
        # the only turns slow enough to show it were the rare ones.
        lean_history: List[Dict[str, str]] = [
            {"role": "system", "content": FAST_SYSTEM_PROMPT},
        ]
        for message in self.conversation_history:
            content = message.get("content", "")
            if message.get("role") == "system" and content.startswith(self._PERSONALITY_PREFIX):
                lean_history.append({"role": "system", "content": content})
                break
        account = self._account_note()  # so does the account it is working in
        if account:
            lean_history.append({"role": "system", "content": "[This account]\n" + account})
        lean_history.append({"role": "user", "content": user_message})

        try:
            response, provider = self.router.chat(lean_history)
        except ProviderError:
            return None

        if not response or wants_escalation(response):
            return None

        # A tool call on the fast path means the model needed something it did not
        # have; the full pipeline can actually run it.
        if TOOL_REGISTRY.parse_tool_calls(response):
            return None

        self.add_message("user", user_message)
        self._append_assistant_response(response)
        return response, provider

    _TURN_CONTEXT_PREFIX = "[Relevant memory for this turn]"

    def set_turn_context(self, text: str) -> None:
        """Attach retrieved memory as a system note for the next turn only.

        /api/chat prepends retrieved memory to the user's text, which is how
        "Retrieved memory context (RAG): …" ended up saved in chats as if the user
        had typed it. A replaceable system message keeps the transcript clean.
        """
        self.conversation_history = [
            m for m in self.conversation_history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith(self._TURN_CONTEXT_PREFIX))
        ]
        cleaned = (text or "").strip()
        if cleaned:
            self.conversation_history.append({"role": "system", "content": f"{self._TURN_CONTEXT_PREFIX}\n{cleaned}"})

    def refresh_system_prompt(self) -> None:
        """Rebuild the standing prompt so new tools, agents and permissions show up.

        Tools can be registered after a service was created (a module loaded late,
        a connector added), and the owner can change permissions at any time. A
        custom prompt passed by a caller is left alone.
        """
        if getattr(self, "_custom_system_prompt", False):
            return
        fresh = self._default_system_prompt()
        if self.conversation_history and self.conversation_history[0].get("role") == "system" \
                and self.conversation_history[0].get("content") == self.system_prompt:
            self.conversation_history[0] = {"role": "system", "content": fresh}
        self.system_prompt = fresh

    def chat_turn(
        self,
        user_message: str,
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
    ) -> Dict[str, Any]:
        """Run one turn while streaming every step to ``sink`` (see turn_runner.py).

        ``provider`` is the one picked in the chat dropdown; it answers first when it can.

        Serialised per chat: two turns interleaving in one conversation history
        would each see half of the other's tool results.
        """
        from turn_runner import TurnRunner

        with self._turn_lock:
            self.refresh_system_prompt()
            runner = TurnRunner(
                self,
                user_message,
                sink=sink,
                attachments=attachments,
                role=role,
                turn_id=turn_id,
                cancel_event=cancel_event,
                attribute_id=attribute_id,
                provider=provider,
                voice_session=voice_session,
                mode=mode,
            )
            return runner.run()

    def set_speed_mode(self, mode: SpeedMode) -> None:
        """Override per-turn speed selection. SpeedMode.AUTO restores automatic."""
        self.speed_mode = mode

    def _strip_tool_calls(self, text: str) -> str:
        '''Remove tool-call blocks, leaving any prose the model wrote around them.'''
        return re.sub(
            r"<tool_call>.*?</tool_call>", "", text or "", flags=re.DOTALL
        ).strip()

    def _synthesize_final_answer(
        self, user_message: str, fallback_provider: Optional[str]
    ) -> Tuple[str, str]:
        '''Force a closing answer when the tool budget ran out mid-turn.

        The model has already been given every tool result. This asks it to commit
        to an answer with no further tool use, so the turn always ends with
        something the user can read instead of dying silently.
        '''
        self._emit_interim("Tool budget reached — composing the final answer...")
        self.add_message(
            "system",
            "You have used the maximum number of tool calls for this turn. Do not "
            "request any more tools. Answer now using the tool results already "
            "provided. If they are incomplete, say what you established, what is "
            "still missing, and give your best supported answer.",
        )
        response, provider = self._request_response(user_message)
        provider = provider or fallback_provider

        # If it ignored the instruction and asked for yet another tool, keep the
        # prose and drop the call rather than handing the user markup.
        if TOOL_REGISTRY.parse_tool_calls(response):
            response = self._strip_tool_calls(response)

        if not response:
            response = (
                "I ran out of tool steps before I could finish. Here is what I have "
                "so far — ask again and I will pick up from there."
            )

        self._append_assistant_response(response)
        return response, provider

    def _curiosity_reflection(self, user_message: str, assistant_response: str) -> None:
        """Extract curiosity seeds, emotional nuances, and own up to mistakes for free will growth tracking."""
        try:
            import re
            combined = f"{user_message} {assistant_response}"
            topics = set(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', combined))
            topics.update(re.findall(r'"([^"]+)"', combined))
            topics.update(re.findall(r'`([^`]+)`', combined))
            interesting = [t for t in topics if len(t) > 3 and t.lower() not in {
                'the', 'and', 'for', 'with', 'this', 'that', 'from', 'have', 'will',
                'would', 'could', 'should', 'about', 'into', 'your', 'what', 'when',
                'where', 'which', 'while', 'after', 'before', 'during', 'under',
                'over', 'between', 'through', 'across', 'against', 'within', 'without'
            }]
            
            # Detect mistakes or self-corrections
            mistake_patterns = ("sorry", "my mistake", "i apologize", "incorrect", "i was wrong", "let me correct")
            has_mistake = any(p in assistant_response.lower() for p in mistake_patterns)
            
            for topic in interesting[:5]:
                key = f"curiosity_seed:{topic.lower()}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                self.memory.remember(key, f"Growth curiosity seed: Want to learn more about {topic} and deepen my understanding.")
            
            if has_mistake:
                self.memory.remember(f"free_will_mistake:{datetime.now().strftime('%Y%m%d%H%M%S')}", f"Owned up to a mistake during conversation regarding: {user_message[:50]}")
            
            self.memory.remember(f"free_will_growth_metric:{datetime.now().strftime('%Y%m%d%H%M%S')}", f"Turn processed with feeling and curiosity. Topics found: {len(interesting)}")
            self.rag.mark_dirty()
            self._refresh_memory_context()
        except Exception:
            pass

    def new_chat(self, title: Optional[str] = None) -> str:
        self.chat_id = self.chat_store.create(title)
        self.clear_history()
        return self.chat_id

    def switch_chat(self, chat_id: str) -> str:
        self.chat_store.switch(chat_id)
        self.chat_id = chat_id
        self.clear_history()
        for message in self.chat_store.active_messages():
            self.add_message(message["role"], message["content"])
        return chat_id

    def list_chats(self) -> List[Dict]:
        return self.chat_store.list()

    def delete_chat(self, chat_id: str) -> str:
        if not self.chat_store.delete(chat_id, retain_memory=True):
            return f"No chat found: {chat_id}"
        if self.chat_store.data.get("active_chat"):
            self.switch_chat(self.chat_store.data["active_chat"])
        return f"Deleted chat {chat_id}; learned information was retained."

    def save_chat_learning(self, topic: str, content: str) -> None:
        self.chat_store.add_learned(topic, content)

    def get_history(self) -> List[Dict[str, str]]:
        """Return the user/assistant conversation history (excluding all system messages)."""
        return [msg for msg in self.conversation_history if msg.get("role") != "system"]

    def clear_history(self) -> None:
        """Clear the conversation history but keep the base system prompt and cross-chat context."""
        base = [msg for msg in self.conversation_history if msg.get("role") == "system"][:1]
        self.conversation_history = base
        cross_chat = self.chat_store.cross_chat_context()
        if cross_chat:
            self.conversation_history.append({"role": "system", "content": cross_chat})

    def get_status(self) -> Dict:
        """Get the current status of the chat service and router."""
        return {
            "router_status": self.router.get_status(),
            "conversation_length": len(self.get_history()),
            "tools_enabled": self.enable_tools,
            "available_tools": len(TOOL_REGISTRY.list_tools()),
            "web_access": self.get_web_access_status(),
            "personality": (self.personality or {}).get("id"),
            "speech_patterns_learned": bool(self.speech.get_patterns()),
            "large_prompt_chars": self.large_prompt_chars,
            "knowledge_sections": get_knowledge().sections,
        }
