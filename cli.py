"""Interactive CLI for Nyx Ichos AI assistant with multi-mode agent pool and strain-aware orchestration."""

from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path
import sys
from typing import Optional

from colorama import Fore, Style, init

from attributes import AttributeNotFoundError
from chat_service import ChatService
from metrics import GLOBAL_METRICS
from multi_mode_chat import get_multi_mode_chat
from providers.base import ProviderError

# Initialize colorama for cross-platform colored output
init(autoreset=True)


class CLI:
    """Interactive command-line interface for Nyx Ichos."""

    def __init__(
        self,
        name: str = "Nyx Ichos",
        attribute_id: Optional[str] = None,
        multi_mode: bool = True,
        verbose: bool = False,
    ):
        self.name = name
        self.attribute_id = attribute_id
        self.service = ChatService(attribute_id=attribute_id)
        self.multi_mode_enabled = multi_mode
        self.multi_chat = get_multi_mode_chat(use_pool=multi_mode) if multi_mode else None
        self.verbose = verbose
        self.approach = "auto"
        self.current_mode = "auto"
        self.running = False

    def print_welcome(self) -> None:
        """Print welcome banner, routing status, and hardware profile."""
        print(f"\n{Fore.CYAN}{'='*64}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{self.name}{Style.RESET_ALL} — High-Quality Local-First AI Assistant")
        print(f"{Style.DIM}Created by Shagnik{Style.RESET_ALL}")
        if self.attribute_id:
            print(f"{Fore.YELLOW}Attribute: {self.attribute_id}{Style.RESET_ALL}")
        if self.multi_mode_enabled:
            print(f"{Fore.MAGENTA}🤖 Multi-Agent Auto-Route & Double-Check Active{Style.RESET_ALL}")
        print()

        status = self.service.get_status() or {}
        router = status.get("router_status", {}) or {}
        health = router.get("hardware_health", {}) or {}
        dev_profile = router.get("device_profile", {}) or {}

        print(f"{Fore.YELLOW}System & Hardware Status:{Style.RESET_ALL}")
        print(f"  Device Tier: {router.get('device_tier', 'unknown')} (Power: {dev_profile.get('power_mode', 'balanced')})")
        print(f"  Max Workers: {dev_profile.get('max_workers', 2)}")
        print(f"  Online: {router.get('online', False)}")
        if health.get("gpu_temp_c", 0) > 0:
            print(f"  GPU Temp: {health.get('gpu_temp_c')}°C | VRAM: {health.get('vram_used_mb', 0)}/{health.get('vram_total_mb', 0)}MB")
        print(f"  Primary Provider: ", end="")

        if router.get("ollama_available"):
            print(f"{Fore.GREEN}Ollama (local){Style.RESET_ALL}")
        elif router.get("gemini_available"):
            print(f"{Fore.GREEN}Gemini (online){Style.RESET_ALL}")
        elif router.get("claude_available"):
            print(f"{Fore.GREEN}Claude (online){Style.RESET_ALL}")
        elif router.get("openai_available"):
            print(f"{Fore.GREEN}OpenAI (online){Style.RESET_ALL}")
        elif router.get("groq_available"):
            print(f"{Fore.GREEN}Groq (online){Style.RESET_ALL}")
        elif router.get("deepseek_available"):
            print(f"{Fore.GREEN}DeepSeek (online){Style.RESET_ALL}")
        elif router.get("kimi_available"):
            print(f"{Fore.GREEN}Kimi (online){Style.RESET_ALL}")
        elif router.get("perplexity_available"):
            print(f"{Fore.GREEN}Perplexity (online){Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}Offline Fallback Mode{Style.RESET_ALL}")

        if self.multi_mode_enabled and self.multi_chat:
            pool_stats = self.multi_chat.get_status().get("pool", {}) or {}
            print(f"  Agent Pool: {pool_stats.get('total_agents', 0)}/{pool_stats.get('max_agents', 4)} workers")
        print()

    def print_help(self) -> None:
        """Print available commands, modes, and attributes."""
        print(f"\n{Fore.CYAN}Commands:{Style.RESET_ALL}")
        print("  /help /status /metrics /quit                Basics & Diagnostics")
        print("  /modes | /mode [name]                       View or switch execution mode")
        print("  /attributes | /attribute [id]               View or apply persona attribute")
        print("  /agents <auto|on|off|N>                    Agent Worker Concurrency")
        print("  /apikey <provider> [key1,key2,...]         Secure Key Management")
        print("  /search <query> /fetch <url>                Multi-Source Web Research")
        print("  /important <topic> <info> /memory <action> Durable Memory Lifecycle")
        print("  /subagents <task>                           Specialist Delegation")
        print("  /web|/online <on|off|status>                Web Access Permissions")
        print("  /remember k=v                               Personalization")
        print("  /personality [id|custom <text>]             Switch AI personality")
        print("  /speech <learn|list|clear>                  Learn your speaking style")
        print("  /folder <status|add|remove|list|read|search>  Generic folder reader")
        print("  /rag <query>                                Retrieve memory context (RAG)")
        print("  /math <expr|equation>                      Solve math or equations (sqrt, π, x², ...)")
        print("  /knowledge <query>                          Search permanent general knowledge")
        print("  /think <task>                               Research in background, answer when ready")
        print("  /improve <scan|list|promote id>             Approval-gated self-improvement")
        print("  /finance <quote|history|knowledge|advice|status>  Live market data & financial literacy")
        print("  /models | /model <name>                         List or switch AI models (local + online)")
        print("  /voice <speak|listen|scan|voices|set|status>     Talk back, listen, voice ID, voices")
        print("  /clear /history /newchat /chats /switch     Session Management")
        print("  /deletechat <id> /pool /verbose             Maintenance & Diagnostics\n")

        print(f"{Fore.YELLOW}Available personalities:{Style.RESET_ALL} gen_z, close_friend, professional, concise, custom")

        print(f"{Fore.YELLOW}Available attributes:{Style.RESET_ALL} coding, web_development, app_development, debugging, explain, auto_model, finance")
        print(f"{Fore.YELLOW}Available modes:{Style.RESET_ALL}")
        print("  quick          Fast responses for simple tasks")
        print("  deep           Thorough analysis and reasoning")
        print("  research       Current web research and source comparison")
        print("  coding         Coding, debugging, imports, and tests")
        print("  super_research Extended, time-budgeted expert research")
        print("  self_improve   Safe, testable improvement proposals")
        print("  auto           Intelligent automatic selection\n")

    def print_modes(self) -> None:
        """Display all available execution modes and indicate which is active."""
        print(f"\n{Fore.CYAN}Available Modes:{Style.RESET_ALL}")
        modes = [
            ("quick", "Fast responses for simple tasks"),
            ("deep", "Thorough analysis and reasoning"),
            ("research", "Current web research and source comparison"),
            ("coding", "Coding, debugging, imports, and tests"),
            ("super_research", "Extended, time-budgeted expert research"),
            ("self_improve", "Safe, testable improvement proposals"),
            ("auto", "Intelligent automatic selection"),
        ]
        for mode_name, desc in modes:
            active_marker = f"{Fore.GREEN}* [active]{Style.RESET_ALL}" if mode_name == self.current_mode else "  "
            print(f"  {active_marker:10} {Fore.YELLOW}{mode_name:<16}{Style.RESET_ALL} {desc}")
        print(f"\n{Fore.CYAN}Usage:{Style.RESET_ALL} /mode <name> (e.g. /mode coding)\n")

    def print_attributes(self) -> None:
        """Display all available persona attributes and indicate which is active."""
        from attributes import list_attributes

        print(f"\n{Fore.CYAN}Available Attributes:{Style.RESET_ALL}")
        attrs = list_attributes()
        for attr in attrs:
            active_marker = f"{Fore.GREEN}* [active]{Style.RESET_ALL}" if attr.id == self.attribute_id else "  "
            print(f"  {active_marker:10} {Fore.YELLOW}{attr.id:<18}{Style.RESET_ALL} {attr.description}")
        print(f"\n{Fore.CYAN}Usage:{Style.RESET_ALL} /attribute <id> (e.g. /attribute coding)\n")

    def print_status(self) -> None:
        """Print detailed hardware, routing, and memory status."""
        status = self.service.get_status() or {}
        router = status.get("router_status", {}) or {}
        profile = router.get("device_profile", {}) or {}
        health = router.get("hardware_health", {}) or {}

        print(f"\n{Fore.CYAN}Hardware & Device Profile:{Style.RESET_ALL}")
        for key, value in profile.items():
            print(f"  {key}: {value}")

        print(f"\n{Fore.CYAN}Hardware Strain & Health:{Style.RESET_ALL}")
        for key, value in health.items():
            print(f"  {key}: {value}")

        print(f"\n{Fore.CYAN}Routing & Providers:{Style.RESET_ALL}")
        print(f"  Device Tier: {router.get('device_tier', 'unknown')}")
        print(f"  Online: {router.get('online', False)}")
        print(f"  Web Access: {router.get('web_access_enabled', False)}")
        print(f"  Ollama: {router.get('ollama_available', False)}")
        print(f"  Gemini: {router.get('gemini_available', False)}")
        print(f"  Claude: {router.get('claude_available', False)}")
        print(f"  OpenAI: {router.get('openai_available', False)}")
        print(f"  Groq: {router.get('groq_available', False)}")
        print(f"  DeepSeek: {router.get('deepseek_available', False)}")
        print(f"  Kimi: {router.get('kimi_available', False)}")
        print(f"  Perplexity: {router.get('perplexity_available', False)}")

        print(f"\n{Fore.CYAN}Conversation History:{Style.RESET_ALL}")
        print(f"  Active Messages: {status.get('conversation_length', 0)}\n")

    def print_metrics(self) -> None:
        """Display aggregated interaction metrics and latency stats."""
        summary = GLOBAL_METRICS.get_summary()
        print(f"\n{Fore.CYAN}Performance & Reliability Metrics:{Style.RESET_ALL}")
        print(f"  Total Requests: {summary.get('total_requests', 0)}")
        print(f"  Success Rate: {summary.get('success_rate', 1.0) * 100:.1f}%")
        print(f"  Average Latency: {summary.get('avg_latency_seconds', 0.0):.3f}s")

        breakdown = summary.get("provider_breakdown", {})
        if breakdown:
            print(f"\n{Fore.CYAN}Provider Analytics:{Style.RESET_ALL}")
            for p_name, p_data in breakdown.items():
                print(f"  {p_name}: {p_data.get('requests')} calls | {p_data.get('success_rate') * 100:.1f}% ok | {p_data.get('avg_latency')}s avg")
        print()

    def print_history(self) -> None:
        """Print conversational history."""
        history = self.service.get_history()
        if not history:
            print(f"\n{Fore.YELLOW}No messages in history yet.{Style.RESET_ALL}\n")
            return

        print(f"\n{Fore.CYAN}Conversation History:{Style.RESET_ALL}")
        for msg in history:
            role = msg["role"].upper()
            if role == "USER":
                print(f"\n{Fore.BLUE}You:{Style.RESET_ALL}")
            else:
                print(f"\n{Fore.GREEN}{self.name}:{Style.RESET_ALL}")
            print(f"  {msg['content']}")
        print()

    def _print_response(self, response: str, provider: str, metadata: Optional[dict] = None) -> None:
        """Format and print response with metadata in verbose mode."""
        print(f"{Fore.GREEN}{self.name} ({provider}):{Style.RESET_ALL}")
        print(f"  {response}\n")

        if self.verbose and metadata:
            print(f"{Fore.CYAN}[Metadata]{Style.RESET_ALL}")
            for key, value in metadata.items():
                print(f"  {key}: {value}")
            print()

    # ------------------------------------------------------------------
    # Personality, speech patterns, folder reader, and RAG commands
    # ------------------------------------------------------------------

    def _handle_personality_command(self, user_input: str) -> None:
        """Handle /personality: list presets, switch preset, or set custom."""
        from personalities import (
            PersonalityNotFoundError,
            get_custom_personality,
            list_personalities,
            save_custom_personality,
        )

        parts = user_input.split(maxsplit=2)
        if len(parts) < 2:
            print(f"\n{Fore.CYAN}Available Personalities:{Style.RESET_ALL}")
            for preset in list_personalities():
                marker = f"{Fore.GREEN}* [active]{Style.RESET_ALL}" if preset["id"] == (self.service.get_personality() or {}).get("id") else "  "
                print(f"  {marker:10} {Fore.YELLOW}{preset['id']:<16}{Style.RESET_ALL} {preset['description']}")
            custom = get_custom_personality()
            if custom:
                print(f"  {Fore.GREEN}* [saved]{Style.RESET_ALL} custom — {custom['description']}")
            print(f"\n{Fore.CYAN}Usage:{Style.RESET_ALL} /personality <id> | /personality custom <description>\n")
            return
        personality_id = parts[1].strip().lower()
        if personality_id == "custom" and len(parts) >= 3:
            try:
                record = save_custom_personality(parts[2].strip())
                self.service.set_personality(record)
                print(f"{Fore.GREEN}Custom personality saved and activated.{Style.RESET_ALL}\n")
            except ValueError as error:
                print(f"{Fore.RED}{error}{Style.RESET_ALL}\n")
            return
        try:
            message = self.service.set_personality_from_id(personality_id)
            print(f"{Fore.GREEN}{message}{Style.RESET_ALL}\n")
        except PersonalityNotFoundError as error:
            print(f"{Fore.RED}{error}{Style.RESET_ALL}\n")

    def _handle_speech_command(self, user_input: str) -> None:
        """Handle /speech: learn, list, or clear speech patterns."""
        parts = user_input.split(maxsplit=1)
        action = parts[1].strip().lower() if len(parts) > 1 else "list"

        if action == "learn":
            print(f"{Fore.GREEN}{self.service.learn_speech_patterns()}{Style.RESET_ALL}\n")
        elif action == "list":
            patterns = self.service.get_speech_patterns()
            if not patterns:
                print(f"{Fore.YELLOW}No speech patterns learned yet. Use /speech learn.{Style.RESET_ALL}\n")
                return
            print(f"\n{Fore.CYAN}Learned Speech Patterns:{Style.RESET_ALL}")
            for key, value in patterns.items():
                print(f"  {key}: {value}")
            print()
        elif action == "clear":
            print(f"{Fore.GREEN}{self.service.clear_speech_patterns()}{Style.RESET_ALL}\n")
        else:
            print(f"{Fore.RED}Usage: /speech <learn|list|clear>{Style.RESET_ALL}\n")

    def _handle_folder_command(self, user_input: str) -> None:
        """Handle /folder: register folders and read files of any format."""
        from folder_reader import FolderReader, FolderReaderError
        reader = FolderReader()
        parts = user_input.split(maxsplit=3)
        action = parts[1].strip().lower() if len(parts) > 1 else "status"

        try:
            if action == "status":
                folders = reader.list_folders()
                if not folders:
                    print(f"{Fore.YELLOW}No folders registered. Use /folder add <name> <path>.{Style.RESET_ALL}\n")
                else:
                    print(f"\n{Fore.CYAN}Registered Folders:{Style.RESET_ALL}")
                    for folder in folders:
                        state = "ok" if folder["exists"] else f"{Fore.RED}missing{Style.RESET_ALL}"
                        print(f"  {folder['name']}: {folder['path']} [{state}] ({folder['file_count']} files)")
                    print()
            elif action == "add" and len(parts) >= 4:
                resolved = reader.add_folder(parts[2], parts[3])
                print(f"{Fore.GREEN}Registered folder '{parts[2]}' -> {resolved}{Style.RESET_ALL}\n")
            elif action == "remove" and len(parts) >= 3:
                removed = reader.remove_folder(parts[2])
                print(f"{Fore.GREEN}Removed folder '{parts[2]}' ({removed}).{Style.RESET_ALL}\n")
            elif action == "list" and len(parts) >= 3:
                files = reader.list_files(parts[2])
                if not files:
                    print(f"{Fore.YELLOW}No files found in '{parts[2]}'.{Style.RESET_ALL}\n")
                else:
                    print(f"\n{Fore.CYAN}Files in '{parts[2]}':{Style.RESET_ALL}")
                    for f in files:
                        print(f"  [{f['kind']:6}] {f['path']} ({f['size']} bytes)")
                    print()
            elif action == "read" and len(parts) >= 4:
                result = reader.read_file(parts[2], parts[3])
                print(f"\n{Fore.CYAN}File: {result['path']} ({result['size']} bytes, {result['kind']}){Style.RESET_ALL}")
                print(result["content"])
                print()
            elif action == "search" and len(parts) >= 4:
                results = reader.search_files(parts[2], parts[3])
                if not results:
                    print(f"{Fore.YELLOW}No matches for '{parts[3]}' in '{parts[2]}'.{Style.RESET_ALL}\n")
                else:
                    print(f"\n{Fore.CYAN}Search results for '{parts[3]}' in '{parts[2]}':{Style.RESET_ALL}")
                    for result in results:
                        print(f"  - {result['path']}: {result['snippet']}")
                    print()
            else:
                print(f"{Fore.RED}Usage: /folder <status|add <name> <path>|remove <name>|list <name>|read <name> <file>|search <name> <query>>{Style.RESET_ALL}\n")
        except FolderReaderError as error:
            print(f"{Fore.RED}{error}{Style.RESET_ALL}\n")

    def _handle_upgrade_assistant_command(self) -> None:
        """Display assistant upgrade audit, architecture state, and active modules."""
        from connectors import CONNECTOR_REGISTRY
        from device_profile import get_device_profile, select_tier

        profile = get_device_profile()
        tier = select_tier(profile)

        print(f"\n{Fore.CYAN}{'='*64}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}Nyx Ichos — Local-First AI Assistant Architecture Status{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'='*64}{Style.RESET_ALL}")
        print(f"  Operating System : {profile.operating_system} | CPU Cores: {profile.cpu_cores}")
        print(f"  RAM Installed    : {profile.ram_gb:.1f} GB | VRAM: {profile.vram_gb:.1f} GB ({profile.gpu_name or 'No discrete GPU'})")
        print(f"  Current Tier     : {tier.name.upper()} (Model: {tier.model_tag})")
        print(f"  Concurrency Limit: {tier.max_workers} worker(s)")
        print(f"\n{Fore.YELLOW}Active Subsystems & Connectors:{Style.RESET_ALL}")
        for c in CONNECTOR_REGISTRY.list_connectors():
            status = f"{Fore.GREEN}READY{Style.RESET_ALL}" if c["available"] else f"{Fore.YELLOW}OFFLINE/DISABLED{Style.RESET_ALL}"
            print(f"  - {c['name']:<18} [{status}] (Risk: {c['risk_level']}, Write: {c['is_write']})")
        print()

    def _handle_assistant_doctor_command(self) -> None:
        """Run comprehensive self-diagnostics on providers, memory, hardware, and connectors."""
        from connectivity import is_online
        from connectors import CONNECTOR_REGISTRY
        from device_profile import get_device_profile

        print(f"\n{Fore.CYAN}--- Assistant Doctor Diagnostics ---{Style.RESET_ALL}")
        profile = get_device_profile(force_refresh=True)
        print(f"  [OK] Device Hardware Profile: {profile.ram_gb:.1f}GB RAM, {profile.vram_gb:.1f}GB VRAM")

        net = is_online()
        print(f"  [{'OK' if net else 'WARN'}] Internet Reachability: {'Online' if net else 'Offline'}")

        # Check memory store
        try:
            items = len(self.service.memory.get_important())
            print(f"  [OK] Memory Store: Healthy ({items} durable memories)")
        except Exception as e:
            print(f"  [FAIL] Memory Store Error: {e}")

        # Check connectors
        health = CONNECTOR_REGISTRY.health_status()
        print(f"  [OK] Connectors: {len(health)} registered")
        for name, h in health.items():
            st = h.get("status", "unknown")
            print(f"       • {name}: {st}")
        print(f"{Fore.GREEN}Diagnostics Complete.{Style.RESET_ALL}\n")

    def _handle_assistant_benchmark_command(self) -> None:
        """Measure local response, routing, and memory retrieval latency."""
        import time

        print(f"\n{Fore.CYAN}Running Assistant Latency & Performance Benchmark...{Style.RESET_ALL}")
        # Measure RAG lookup
        t0 = time.perf_counter()
        _ = self.service.rag_search("benchmark query")
        rag_ms = (time.perf_counter() - t0) * 1000

        # Measure Device Profile loading
        t0 = time.perf_counter()
        from device_profile import get_device_profile
        _ = get_device_profile()
        profile_ms = (time.perf_counter() - t0) * 1000

        print(f"  • RAG Retrieval Latency   : {rag_ms:.2f} ms")
        print(f"  • Device Profile Read     : {profile_ms:.2f} ms")
        print(f"  • Max Worker Allocation   : {self.service.router.profile.max_workers} worker(s)")
        print(f"{Fore.GREEN}Benchmark finished successfully.{Style.RESET_ALL}\n")

    def _handle_serious_mode_command(self) -> None:
        """Toggle or enable Serious Mode immediately."""
        self.service.set_personality_from_id("serious")
        print(f"\n{Fore.GREEN}⚡ Serious Mode Activated: High analytical rigor, zero conversational filler, structured output.{Style.RESET_ALL}\n")

    def _handle_graph_command(self, user_input: str) -> None:
        """Handle /graph-create and /graph-read."""
        from graph_engine import GraphEngine

        parts = user_input.split(maxsplit=2)
        cmd = parts[0].lower()
        if cmd == "/graph-read" and len(parts) >= 2:
            text = user_input[len(parts[0]):].strip()
            res = GraphEngine.read_graph(text)
            print(f"\n{Fore.CYAN}Parsed Graph ({res['node_count']} nodes, {res['edge_count']} edges):{Style.RESET_ALL}")
            for e in res["edges"]:
                lbl = f" ({e['label']})" if e.get("label") else ""
                print(f"  {e['from']} --> {e['to']}{lbl}")
            print()
        else:
            # Simple demo graph creation or custom nodes
            nodes = [
                {"id": "Client", "label": "Client / Frontend"},
                {"id": "Router", "label": "Evidence-Based Router"},
                {"id": "LocalModel", "label": "Ollama (Local Tier)"},
                {"id": "OnlineAPI", "label": "Online Provider (Escalate)"},
            ]
            edges = [
                {"from": "Client", "to": "Router", "label": "User Query"},
                {"from": "Router", "to": "LocalModel", "label": "Offline / Private"},
                {"from": "Router", "to": "OnlineAPI", "label": "Complex / Research"},
            ]
            res = GraphEngine.create_graph(nodes, edges)
            print(f"\n{Fore.CYAN}Created Architecture Graph:{Style.RESET_ALL}\n")
            print(res["ascii"])
            print(f"\n{Fore.MAGENTA}Mermaid Code:{Style.RESET_ALL}\n```mermaid\n{res['mermaid']}\n```\n")

    def _handle_homework_command(self, user_input: str) -> None:
        """Handle /homework-help problem decomposition."""
        from homework_helper import HomeworkHelper

        parts = user_input.split(maxsplit=1)
        if len(parts) < 2:
            print(f"{Fore.RED}Usage: /homework-help <problem text>{Style.RESET_ALL}\n")
            return
        problem = parts[1]
        analysis = HomeworkHelper.decompose_problem(problem)
        print(f"\n{Fore.CYAN}=== Homework Problem Analysis ({analysis['subject'].upper()}) ==={Style.RESET_ALL}")
        print(f"Problem: {analysis['problem']}\n")
        print(f"{Fore.YELLOW}Recommended Steps:{Style.RESET_ALL}")
        for s in analysis["recommended_steps"]:
            print(f"  {s}")
        print(f"\n{Fore.YELLOW}Hints for Independent Study:{Style.RESET_ALL}")
        for h in analysis["hints"]:
            print(f"  {h}")
    def _handle_assistant_connectors_command(self) -> None:
        """List all active and available connectors."""
        from connectors import CONNECTOR_REGISTRY

        connectors = CONNECTOR_REGISTRY.list_connectors()
        print(f"\n{Fore.CYAN}Registered Connectors & Tool Adapters ({len(connectors)}):{Style.RESET_ALL}")
        for c in connectors:
            avail = f"{Fore.GREEN}Active{Style.RESET_ALL}" if c["available"] else f"{Fore.YELLOW}Unavailable{Style.RESET_ALL}"
            perms = ", ".join(c.get("permissions", []))
            print(f"  • {Fore.YELLOW}{c['name']:<20}{Style.RESET_ALL} [{avail}]")
            print(f"    Description : {c['description']}")
            print(f"    Permissions : {perms} | Write: {c['is_write']} | Risk: {c['risk_level']}")
        print()

    def _handle_rag_command(self, user_input: str) -> None:
        """Handle /rag: retrieve relevant memory context for a query."""
        parts = user_input.split(maxsplit=1)
        if len(parts) < 2:
            print(f"{Fore.RED}Usage: /rag <query>{Style.RESET_ALL}\n")
            return
        results = self.service.rag_search(parts[1])
        if not results:
            print(f"{Fore.YELLOW}No relevant memory found for: {parts[1]}{Style.RESET_ALL}\n")
            return
        print(f"\n{Fore.CYAN}RAG results for '{parts[1]}':{Style.RESET_ALL}")
        for result in results:
            meta = result.get("metadata", {})
            label = meta.get("topic") or meta.get("key") or meta.get("kind", "memory")
            print(f"  [{label}] {result.get('text', '')} (score: {result.get('score', 0)})")
        print()

    def _handle_math_command(self, user_input: str) -> None:
        """Handle /math: evaluate expressions or solve equations."""
        from math_engine import solve_math

        parts = user_input.split(maxsplit=1)
        if len(parts) < 2:
            print(f"{Fore.RED}Usage: /math <expression|equation>{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  Examples: /math sqrt(144) + 2^5 | /math 2x + 3 = 11 | /math x² - 5x + 6 = 0{Style.RESET_ALL}\n")
            return
        print(f"\n{Fore.CYAN}{solve_math(parts[1])}{Style.RESET_ALL}\n")

    def _handle_knowledge_command(self, user_input: str) -> None:
        """Handle /knowledge: search the permanent general knowledge base."""
        parts = user_input.split(maxsplit=1)
        if len(parts) < 2:
            print(f"{Fore.RED}Usage: /knowledge <query>{Style.RESET_ALL}\n")
            return
        print(f"\n{Fore.CYAN}{self.service.search_knowledge(parts[1])}{Style.RESET_ALL}\n")

    def _handle_models_command(self) -> None:
        """List all available AI models: local (Ollama) and online (configured)."""
        from config import SETTINGS
        from providers.ollama_provider import OllamaProvider

        print(f"\n{Fore.CYAN}Local models (Ollama @ {SETTINGS.ollama_host}):{Style.RESET_ALL}")
        local = OllamaProvider().list_models()
        if not local:
            print(f"  {Fore.YELLOW}Ollama server not reachable or no models installed.{Style.RESET_ALL}")
        else:
            for model in local:
                marker = f"{Fore.GREEN} * [active]{Style.RESET_ALL}" if model == SETTINGS.ollama_model else ""
                print(f"  {model} {marker}")

        print(f"\n{Fore.CYAN}Online providers:{Style.RESET_ALL}")
        from providers.anthropic_provider import AnthropicProvider
        from providers.deepseek_provider import DeepSeekProvider
        from providers.gemini_provider import GeminiProvider
        from providers.groq_provider import GroqProvider
        from providers.kimi_provider import KimiProvider
        from providers.openai_provider import OpenAIProvider
        from providers.perplexity_provider import PerplexityProvider

        online = [
            ("claude", AnthropicProvider()),
            ("openai", OpenAIProvider()),
            ("gemini", GeminiProvider()),
            ("kimi", KimiProvider()),
            ("deepseek", DeepSeekProvider()),
            ("groq", GroqProvider()),
            ("perplexity", PerplexityProvider()),
        ]
        for name, provider in online:
            state = f"{Fore.GREEN}configured{Style.RESET_ALL}" if provider.is_available() else f"{Fore.YELLOW}no key{Style.RESET_ALL}"
            preferred = f"{Fore.GREEN} * [preferred]{Style.RESET_ALL}" if name == SETTINGS.preferred_online_provider else ""
            print(f"  {name:<12} {state} {preferred}")
        print(f"\n{Fore.CYAN}Switch with: /model <local-model-name> or /model <provider-name>{Style.RESET_ALL}\n")

    def _handle_model_command(self, user_input: str) -> None:
        """Switch the active local model or the preferred online provider."""
        from config import SETTINGS
        from providers.ollama_provider import OllamaProvider

        parts = user_input.split(maxsplit=1)
        if len(parts) < 2:
            print(f"{Fore.RED}Usage: /model <name> (local model or provider name). Try /models to list them.{Style.RESET_ALL}\n")
            return
        target = parts[1].strip()

        online_names = {"claude", "openai", "gemini", "kimi", "deepseek", "groq", "perplexity"}
        if target.lower() in online_names:
            SETTINGS.preferred_online_provider = target.lower()
            print(f"{Fore.GREEN}Preferred online provider set to: {target.lower()}{Style.RESET_ALL}\n")
            return

        local = OllamaProvider().list_models()
        match = next((m for m in local if m == target or target in m), None)
        if match:
            SETTINGS.ollama_model = match
            print(f"{Fore.GREEN}Local model set to: {match}{Style.RESET_ALL}\n")
            return

        print(
            f"{Fore.RED}No match for '{target}'. Use /models to see local models and online providers.{Style.RESET_ALL}\n"
        )

    def _handle_voice_command(self, user_input: str) -> None:
        """Handle /voice: talk back, listen, voice ID scan, and voice selection."""
        import voice

        parts = user_input.split(maxsplit=2)
        action = parts[1].lower() if len(parts) > 1 else "status"

        if action == "speak":
            if len(parts) < 3:
                print(f"{Fore.RED}Usage: /voice speak <text>{Style.RESET_ALL}\n")
                return
            print(f"\n{Fore.CYAN}{voice.speak(parts[2])}{Style.RESET_ALL}\n")
        elif action == "listen":
            timeout = 10
            if len(parts) >= 3 and parts[2].isdigit():
                timeout = int(parts[2])
            print(f"\n{Fore.YELLOW}🎤 Listening for {timeout}s...{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Heard: {voice.listen(timeout=timeout)}{Style.RESET_ALL}\n")
        elif action == "scan":
            mode = parts[2].lower() if len(parts) > 2 else "status"
            if mode == "enroll":
                print(f"\n{Fore.YELLOW}🎙️ Voice scan: say something for ~3 seconds...{Style.RESET_ALL}")
                result = voice.enroll_voice()
            elif mode == "verify":
                print(f"\n{Fore.YELLOW}🎙️ Verifying voice: say something for ~3 seconds...{Style.RESET_ALL}")
                result = voice.verify_voice()
            else:
                result = voice.voice_status()
            print(f"\n{Fore.CYAN}{result}{Style.RESET_ALL}\n")
        elif action in ("voices", "list"):
            voices = voice.list_voices()
            if not voices:
                print(f"{Fore.YELLOW}No voices installed.{Style.RESET_ALL}\n")
                return
            print(f"\n{Fore.CYAN}Installed voices ({len(voices)}):{Style.RESET_ALL}")
            active = voice.get_voice()
            for v in voices:
                marker = f"{Fore.GREEN} * [active]{Style.RESET_ALL}" if v["name"] == active else ""
                print(f"  {v['name']} ({v['gender']}, {v['culture']}) {marker}")
            print()
        elif action == "set":
            if len(parts) < 3:
                print(f"{Fore.RED}Usage: /voice set <voice-name>{Style.RESET_ALL}\n")
                return
            print(f"\n{Fore.CYAN}{voice.set_voice(parts[2])}{Style.RESET_ALL}\n")
        elif action == "status":
            status = voice.voice_status()
            state = "enrolled" if status.get("enrolled") else "not enrolled"
            print(f"\n{Fore.CYAN}Voice status:{Style.RESET_ALL}")
            print(f"  Voice ID: {state} ({', '.join(status.get('voiceprints', [])) or 'no voiceprints'})")
            print(f"  Active voice: {status.get('voice') or 'none'}")
            print(f"  Mic: {status.get('mic') or 'not found'}")
            print(f"  Voices available: {len(status.get('voices', []))}")
            print()
        else:
            print(f"{Fore.RED}Usage: /voice <speak TEXT|listen [secs]|scan [enroll|verify]|voices|set NAME|status>{Style.RESET_ALL}\n")

    def _handle_finance_command(self, user_input: str) -> None:
        """Handle /finance: live quotes, history, knowledge, advice, and market status."""
        from finance import advisor_context, get_finance_knowledge, history_text, quote_text

        parts = user_input.split(maxsplit=2)
        action = parts[1].lower() if len(parts) > 1 else "status"

        if action == "quote":
            if len(parts) < 3:
                print(f"{Fore.RED}Usage: /finance quote <SYMBOLS>{Style.RESET_ALL}\n")
                return
            print(f"\n{Fore.CYAN}{quote_text(parts[2])}{Style.RESET_ALL}\n")
        elif action == "history":
            if len(parts) < 3:
                print(f"{Fore.RED}Usage: /finance history <SYMBOL> [range]{Style.RESET_ALL}\n")
                return
            range_opt = parts[2].split()[-1] if len(parts[2].split()) > 1 else "3mo"
            symbol = parts[2].split()[0]
            print(f"\n{Fore.CYAN}{history_text(symbol, range=range_opt)}{Style.RESET_ALL}\n")
        elif action == "knowledge":
            if len(parts) < 3:
                print(f"{Fore.RED}Usage: /finance knowledge <query>{Style.RESET_ALL}\n")
                return
            print(f"\n{Fore.CYAN}{get_finance_knowledge().search_text(parts[2])}{Style.RESET_ALL}\n")
        elif action == "advice":
            if len(parts) < 3:
                print(f"{Fore.RED}Usage: /finance advice <question>{Style.RESET_ALL}\n")
                return
            question = parts[2]
            context = advisor_context(question, memory=self.service.memory)
            prompt = f"{context}\n\n{question}" if context else question
            print(f"\n{Fore.YELLOW}[Finance Advisor]{Style.RESET_ALL}")
            try:
                response, provider = self.service.chat(prompt, attribute_id="finance")
                print(f"\n{Fore.GREEN}{response}{Style.RESET_ALL}\n")
            except Exception as error:
                print(f"{Fore.RED}Advice failed: {error}{Style.RESET_ALL}\n")
        elif action == "status":
            from connectors import CONNECTOR_REGISTRY

            result = CONNECTOR_REGISTRY.execute("finance", "market_status")
            state = "OPEN" if result.get("open") else "CLOSED"
            print(f"\n{Fore.CYAN}US stock markets: {state} (Eastern Time){Style.RESET_ALL}")
            print(f"{Fore.CYAN}Finance connector: {'available' if result.get('success') else 'unavailable'}{Style.RESET_ALL}\n")
        else:
            print(f"{Fore.RED}Usage: /finance <quote SYMBOLS|history SYMBOL [range]|knowledge QUERY|advice QUESTION|status>{Style.RESET_ALL}\n")

    def _handle_think_command(self, user_input: str) -> None:
        """Handle /think: start a background thought, then report live milestones."""
        from thought_loop import BackgroundThinker

        parts = user_input.split(maxsplit=1)
        if len(parts) < 2:
            print(f"{Fore.RED}Usage: /think <task>{Style.RESET_ALL}\n")
            return
        task = parts[1]
        thinker = BackgroundThinker(self.service, task)
        thinker.start()
        print(f"\n{Fore.YELLOW}🧠 Thinking in the background (id: {thinker.thought.thought_id})...{Style.RESET_ALL}")
        seen = 0
        while True:
            status = thinker.status()
            for milestone in status["milestones"][seen:]:
                print(f"{Fore.CYAN}  • {milestone}{Style.RESET_ALL}")
            seen = len(status["milestones"])
            if status["status"] in ("complete", "error", "cancelled"):
                break
            import time

            time.sleep(0.5)
        if status["status"] == "complete":
            print(f"\n{Fore.GREEN}{status['result']}{Style.RESET_ALL}\n")
        else:
            print(f"{Fore.RED}Thought failed: {status.get('error') or status['status']}{Style.RESET_ALL}\n")

    def _handle_improve_command(self, user_input: str) -> None:
        """Handle /improve: approval-gated self-improvement scanning and proposals."""
        from self_improvement import ImprovementStore, scan_online_improvements

        parts = user_input.split(maxsplit=2)
        action = parts[1].lower() if len(parts) > 1 else "list"
        store = ImprovementStore()
        if action == "scan":
            topic = parts[2] if len(parts) > 2 else "python ai assistant"
            print(f"\n{Fore.YELLOW}Scanning the web for improvements and known issues ({topic})...{Style.RESET_ALL}")
            created = scan_online_improvements(topic)
            if not created:
                print(f"{Fore.YELLOW}No new proposals (offline or nothing found).{Style.RESET_ALL}\n")
            else:
                print(f"{Fore.GREEN}Filed {len(created)} proposal(s) — all require your approval to go live:{Style.RESET_ALL}")
                for proposal in created:
                    print(f"  {proposal.proposal_id} [{proposal.kind}] {proposal.description}")
                print()
        elif action == "list":
            print(f"\n{Fore.CYAN}{store.summary()}{Style.RESET_ALL}\n")
        elif action == "promote" and len(parts) >= 3:
            try:
                promoted = store.promote(parts[2].strip(), owner_approved=True)
                print(f"{Fore.GREEN}Promoted {promoted.proposal_id} to live.{Style.RESET_ALL}\n")
            except (PermissionError, KeyError) as error:
                print(f"{Fore.RED}{error}{Style.RESET_ALL}\n")
        else:
            print(f"{Fore.RED}Usage: /improve <scan [topic]|list|promote <id>>{Style.RESET_ALL}\n")

    def _handle_system_command(self, user_input: str) -> None:
        """Handle /system: computer controls for screenshot, clipboard, processes, lock."""
        from connectors import CONNECTOR_REGISTRY

        parts = user_input.split(maxsplit=2)
        sub = parts[1].lower() if len(parts) > 1 else "status"

        if sub == "screenshot":
            path = parts[2] if len(parts) > 2 else "screenshot.png"
            res = CONNECTOR_REGISTRY.execute("system_control", "take_screenshot", output_path=path)
            if res.get("success"):
                print(f"{Fore.GREEN}Screenshot saved to: {res['path']}{Style.RESET_ALL}\n")
            else:
                print(f"{Fore.RED}{res.get('error')}{Style.RESET_ALL}\n")
        elif sub == "clipboard":
            if len(parts) > 2:
                res = CONNECTOR_REGISTRY.execute("system_control", "set_clipboard", text=parts[2])
                print(f"{Fore.GREEN}Copied {len(parts[2])} characters to clipboard.{Style.RESET_ALL}\n")
            else:
                res = CONNECTOR_REGISTRY.execute("system_control", "get_clipboard")
                print(f"\n{Fore.CYAN}Current Clipboard Content:{Style.RESET_ALL}\n{res.get('clipboard', '')}\n")
        elif sub == "processes":
            res = CONNECTOR_REGISTRY.execute("system_control", "list_processes", limit=15)
            print(f"\n{Fore.CYAN}Active Processes (Top 15):{Style.RESET_ALL}")
            for p in res.get("processes", []):
                mem = f"({p['memory_mb']} MB)" if "memory_mb" in p else ""
                print(f"  [{p.get('pid')}] {p.get('name')} {mem}")
            print()
        elif sub == "stats" or sub == "status":
            res = CONNECTOR_REGISTRY.execute("system_control", "get_system_stats")
            print(f"\n{Fore.CYAN}Computer System Status:{Style.RESET_ALL}")
            for k, v in res.items():
                print(f"  {k}: {v}")
            print()
        else:
            print(f"{Fore.RED}Usage: /system <screenshot|clipboard [text]|processes|stats>{Style.RESET_ALL}\n")

    def _handle_google_command(self, user_input: str) -> None:
        """Handle /google: Google search, Maps, Drive, Docs."""
        from connectors import CONNECTOR_REGISTRY

        parts = user_input.split(maxsplit=2)
        if len(parts) < 2:
            print(f"{Fore.RED}Usage: /google <query|maps <loc>|drive <q>|doc>{Style.RESET_ALL}\n")
            return

        action = parts[1].lower()
        if action == "maps" and len(parts) > 2:
            res = CONNECTOR_REGISTRY.execute("google_services", "maps", location=parts[2], open_browser=True)
            print(f"{Fore.GREEN}Opened Google Maps: {res.get('url')}{Style.RESET_ALL}\n")
        elif action == "doc":
            res = CONNECTOR_REGISTRY.execute("google_services", "create_doc", doc_type="document", open_browser=True)
            print(f"{Fore.GREEN}Opened New Google Doc: {res.get('url')}{Style.RESET_ALL}\n")
        elif action == "sheet":
            res = CONNECTOR_REGISTRY.execute("google_services", "create_doc", doc_type="sheet", open_browser=True)
            print(f"{Fore.GREEN}Opened New Google Sheet: {res.get('url')}{Style.RESET_ALL}\n")
        elif action == "drive":
            q = parts[2] if len(parts) > 2 else ""
            res = CONNECTOR_REGISTRY.execute("google_services", "drive_search", query=q, open_browser=True)
            print(f"{Fore.GREEN}Opened Google Drive Search: {res.get('url')}{Style.RESET_ALL}\n")
        else:
            query = user_input[len(parts[0]):].strip()
            res = CONNECTOR_REGISTRY.execute("google_services", "search", query=query, open_browser=True)
            print(f"{Fore.GREEN}Google Search: {res.get('url')}{Style.RESET_ALL}")
            if res.get("summary"):
                print(f"\n{Fore.CYAN}Summary:{Style.RESET_ALL}\n{res.get('summary')}\n")

    def _handle_youtube_command(self, user_input: str) -> None:
        """Handle /youtube or /yt: search or play videos/music."""
        from connectors import CONNECTOR_REGISTRY

        parts = user_input.split(maxsplit=2)
        if len(parts) < 2:
            print(f"{Fore.RED}Usage: /youtube <search|play|music> <query_or_url>{Style.RESET_ALL}\n")
            return

        action = parts[1].lower()
        if action in ("play", "music") and len(parts) > 2:
            is_music = (action == "music")
            res = CONNECTOR_REGISTRY.execute("youtube", "play", query_or_url=parts[2], music=is_music)
            print(f"{Fore.GREEN}Playing on YouTube: {res.get('url')}{Style.RESET_ALL}\n")
        elif action == "search" and len(parts) > 2:
            res = CONNECTOR_REGISTRY.execute("youtube", "search", query=parts[2], open_browser=True)
            print(f"{Fore.GREEN}YouTube Search Opened: {res.get('search_url')}{Style.RESET_ALL}\n")
        else:
            # Default is play/search directly
            target = user_input[len(parts[0]):].strip()
            res = CONNECTOR_REGISTRY.execute("youtube", "play", query_or_url=target, music=False)
            print(f"{Fore.GREEN}Playing on YouTube: {res.get('url')}{Style.RESET_ALL}\n")

    def process_input(self, user_input: str) -> bool:
        """Process user message or command. Returns False if user wants to exit."""
        user_input = user_input.strip()
        if not user_input:
            return True

        if user_input.startswith("/"):
            command = user_input.lower().split()[0]

            if command in ("/quit", "/exit"):
                print(f"\n{Fore.YELLOW}Goodbye!{Style.RESET_ALL}\n")
                return False
            elif command == "/help":
                self.print_help()
                return True
            elif command == "/status":
                self.print_status()
                return True
            elif command == "/metrics":
                self.print_metrics()
                return True
            elif command in ("/attribute", "/attributes"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    self.print_attributes()
                    return True
                attribute_id = parts[1].strip()
                try:
                    self.service.add_attribute_guidance(attribute_id)
                    self.attribute_id = attribute_id
                    print(f"{Fore.GREEN}Attribute set to: {attribute_id}{Style.RESET_ALL}\n")
                except Exception as exc:
                    print(f"{Fore.RED}{exc}{Style.RESET_ALL}\n")
                return True
            elif command in ("/online", "/web"):
                parts = user_input.split(maxsplit=1)
                action = parts[1].strip().lower() if len(parts) > 1 else "status"
                if action not in {"on", "off", "status"}:
                    print(f"{Fore.RED}Usage: /web <on|off|status>{Style.RESET_ALL}\n")
                elif action == "status":
                    status = self.service.get_web_access_status()
                    state = "enabled" if status["enabled"] else "disabled"
                    network = "reachable" if status["online"] else "unreachable"
                    print(f"{Fore.CYAN}Web access: {state}; network: {network}{Style.RESET_ALL}\n")
                else:
                    print(f"{Fore.GREEN}{self.service.set_web_access(action == 'on')}{Style.RESET_ALL}\n")
                return True
            elif command == "/apikey":
                parts = user_input.split(maxsplit=2)
                if len(parts) < 2:
                    print(f"{Fore.RED}Usage: /apikey <provider> [key1,key2,...]{Style.RESET_ALL}\n")
                    return True
                from secret_store import set_keys

                provider = parts[1].upper()
                raw = parts[2] if len(parts) > 2 else getpass("API key(s), comma-separated: ")
                keys = set_keys(f"{provider}_API_KEY", raw.split(","))
                from config import reload_keys

                # SETTINGS is read at call time, so refreshing it is all that
                # stands between saving a key and using it. One shared helper
                # rather than a setattr per call site, because the same "why is
                # it still not configured?" bug is easy to reintroduce.
                reload_keys()
                print(f"{Fore.GREEN}Saved {len(keys)} key(s) for {provider}.{Style.RESET_ALL}\n")
                return True
            elif command == "/agents":
                parts = user_input.split(maxsplit=1)
                setting = parts[1].strip().lower() if len(parts) > 1 else "status"
                if setting == "status":
                    print(f"{Fore.CYAN}Agent workers: {'on' if self.multi_mode_enabled else 'off'}{Style.RESET_ALL}\n")
                elif setting in {"off", "on", "auto"} or setting.isdigit():
                    if setting == "off":
                        self.multi_mode_enabled = False
                        self.multi_chat = None
                    else:
                        from agent_pool import get_agent_pool, shutdown_pool

                        shutdown_pool()
                        count = 2 if setting in {"on", "auto"} else max(1, min(10, int(setting)))
                        self.multi_mode_enabled = True
                        self.multi_chat = get_multi_mode_chat(use_pool=True)
                        self.multi_chat.pool = get_agent_pool(count)
                    print(f"{Fore.GREEN}Agent workers configured ({setting}).{Style.RESET_ALL}\n")
                else:
                    print(f"{Fore.RED}Usage: /agents <auto|on|off|N>{Style.RESET_ALL}\n")
                return True
            elif command == "/search":
                from tools import builtin_search_web

                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"{Fore.RED}Usage: /search <query>{Style.RESET_ALL}\n")
                    return True
                print(f"\n{Fore.CYAN}{builtin_search_web(parts[1])}{Style.RESET_ALL}\n")
                return True
            elif command == "/fetch":
                from tools import builtin_fetch_webpage

                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"{Fore.RED}Usage: /fetch <url>{Style.RESET_ALL}\n")
                    return True
                print(f"\n{Fore.CYAN}{builtin_fetch_webpage(parts[1])}{Style.RESET_ALL}\n")
                return True
            elif command == "/important":
                parts = user_input.split(maxsplit=2)
                if len(parts) < 3:
                    print(f"{Fore.RED}Usage: /important <topic> <info>{Style.RESET_ALL}\n")
                    return True
                try:
                    print(f"{Fore.GREEN}{self.service.remember_important(parts[1], parts[2])}{Style.RESET_ALL}\n")
                except ValueError as error:
                    print(f"{Fore.RED}{error}{Style.RESET_ALL}\n")
                return True
            elif command == "/remember":
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2 or "=" not in parts[1]:
                    print(f"{Fore.RED}Usage: /remember key=value{Style.RESET_ALL}\n")
                    return True
                key, value = parts[1].split("=", 1)
                print(f"{Fore.GREEN}{self.service.remember(key.strip(), value.strip())}{Style.RESET_ALL}\n")
                return True
            elif command == "/memory":
                parts = user_input.split(maxsplit=3)
                action = parts[1].lower() if len(parts) > 1 else "list"
                if action == "list":
                    items = self.service.memory.get_important()
                    if not items:
                        print(f"{Fore.YELLOW}No important memories saved.{Style.RESET_ALL}\n")
                    else:
                        print(f"\n{Fore.CYAN}Important memories:{Style.RESET_ALL}")
                        for item in items:
                            print(f"  - {item['topic']}: {item['content']}")
                        print()
                elif action == "clear":
                    print(f"{Fore.GREEN}{self.service.clear_important_memory()}{Style.RESET_ALL}\n")
                elif action == "remove" and len(parts) >= 3:
                    print(f"{Fore.GREEN}{self.service.remove_important_memory(parts[2].strip())}{Style.RESET_ALL}\n")
                else:
                    print(f"{Fore.RED}Usage: /memory <list|remove <topic>|clear>{Style.RESET_ALL}\n")
                return True
            elif command in ("/mode", "/modes"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    self.print_modes()
                    return True
                mode = parts[1].strip().lower()
                valid = ["auto", "coding", "deep", "research", "quick", "super_research", "self_improve"]
                if mode in valid:
                    self.current_mode = mode
                    print(f"{Fore.GREEN}Mode set to: {mode}{Style.RESET_ALL}\n")
                else:
                    print(f"{Fore.RED}Invalid mode '{mode}'. Choose from: {', '.join(valid)}{Style.RESET_ALL}\n")
                return True
            elif command == "/pool":
                if self.multi_chat:
                    stats = self.multi_chat.get_status().get("pool", {}) or {}
                    print(f"\n{Fore.CYAN}Agent Pool Status:{Style.RESET_ALL}")
                    print(f"  Total Workers: {stats.get('total_agents', 0)}/{stats.get('max_agents', 0)}")
                    print(f"  Busy: {stats.get('busy_agents', 0)} | Idle: {stats.get('idle_agents', 0)}")
                    print(f"  Hardware Concurrency Limit: {stats.get('hardware_max_workers', 2)}")
                    agents = stats.get("agents", [])
                    if agents:
                        print(f"\n{Fore.CYAN}Worker Statistics:{Style.RESET_ALL}")
                        for a in agents:
                            print(f"  {a['agent_id']} ({a['mode']}): {a['tasks_completed']} completed | {a['avg_processing_time']:.2f}s avg")
                    print()
                return True
            elif command == "/verbose":
                self.verbose = not self.verbose
                print(f"{Fore.GREEN}Verbose mode {'enabled' if self.verbose else 'disabled'}.{Style.RESET_ALL}\n")
                return True
            elif command == "/clear":
                self.service.clear_history()
                print(f"{Fore.YELLOW}Conversation history cleared.{Style.RESET_ALL}\n")
                return True
            elif command == "/newchat":
                title = user_input.split(maxsplit=1)[1] if len(user_input.split(maxsplit=1)) > 1 else None
                chat_id = self.service.new_chat(title)
                print(f"{Fore.GREEN}Started chat {chat_id}.{Style.RESET_ALL}\n")
                return True
            elif command == "/chats":
                for chat in self.service.list_chats():
                    marker = "*" if chat["id"] == self.service.chat_id else " "
                    print(f"{marker} {chat['id']} — {chat['title']}")
                print()
                return True
            elif command == "/switch":
                parts = user_input.split(maxsplit=1)
                if len(parts) >= 2:
                    try:
                        self.service.switch_chat(parts[1].strip())
                        print(f"{Fore.GREEN}Switched to chat {parts[1].strip()}.{Style.RESET_ALL}\n")
                    except KeyError as error:
                        print(f"{Fore.RED}{error}{Style.RESET_ALL}\n")
                return True
            elif command == "/history":
                self.print_history()
                return True
            elif command in ("/personality", "/personalities"):
                self._handle_personality_command(user_input)
                return True
            elif command == "/speech":
                self._handle_speech_command(user_input)
                return True
            elif command == "/folder":
                self._handle_folder_command(user_input)
                return True
            elif command == "/rag":
                self._handle_rag_command(user_input)
                return True
            elif command in ("/math", "/maths"):
                self._handle_math_command(user_input)
                return True
            elif command in ("/knowledge", "/know"):
                self._handle_knowledge_command(user_input)
                return True
            elif command in ("/finance", "/stocks", "/invest"):
                self._handle_finance_command(user_input)
                return True
            elif command == "/models":
                self._handle_models_command()
                return True
            elif command == "/model":
                self._handle_model_command(user_input)
                return True
            elif command in ("/voice", "/talk", "/speak"):
                self._handle_voice_command(user_input)
                return True
            elif command in ("/think", "/background"):
                self._handle_think_command(user_input)
                return True
            elif command == "/improve":
                self._handle_improve_command(user_input)
                return True
            elif command in ("/upgrade-assistant", "/upgrade"):
                self._handle_upgrade_assistant_command()
                return True
            elif command in ("/assistant-status", "/status-all"):
                self._handle_upgrade_assistant_command()
                return True
            elif command in ("/assistant-doctor", "/doctor"):
                self._handle_assistant_doctor_command()
                return True
            elif command in ("/assistant-benchmark", "/benchmark"):
                self._handle_assistant_benchmark_command()
                return True
            elif command in ("/assistant-connectors", "/connectors"):
                self._handle_assistant_connectors_command()
                return True
            elif command in ("/serious-mode", "/serious"):
                self._handle_serious_mode_command()
                return True
            elif command in ("/graph-create", "/graph-read", "/graph"):
                self._handle_graph_command(user_input)
                return True
            elif command in ("/homework-help", "/homework"):
                self._handle_homework_command(user_input)
                return True
            elif command in ("/system", "/pc", "/computer"):
                self._handle_system_command(user_input)
                return True
            elif command == "/google":
                self._handle_google_command(user_input)
                return True
            elif command in ("/youtube", "/yt"):
                self._handle_youtube_command(user_input)
                return True
            else:
                print(f"{Fore.RED}Unknown command: {command}. Type /help for options.{Style.RESET_ALL}\n")
                return True

        # Process chat message
        print()
        try:
            if self.multi_mode_enabled and self.multi_chat:
                force_mode = None if self.current_mode == "auto" else self.current_mode
                response, provider, metadata = self.multi_chat.chat(
                    user_input,
                    attribute_id=self.attribute_id,
                    verbose=self.verbose,
                    force_mode=force_mode,
                    approach=self.approach,
                )
                self._print_response(response, provider, metadata)
            else:
                response, provider = self.service.chat(user_input)
                self._print_response(response, provider)
        except ProviderError as error:
            print(f"{Fore.RED}Provider Error: {error}{Style.RESET_ALL}\n")
        except Exception as error:
            print(f"{Fore.RED}Error: {error}{Style.RESET_ALL}\n")

        return True

    def run(self) -> None:
        """Run the interactive CLI loop."""
        self.running = True
        self.print_welcome()
        self.print_help()

        try:
            while self.running:
                try:
                    user_input = input(f"{Fore.BLUE}You:{Style.RESET_ALL} ").strip()
                    if not self.process_input(user_input):
                        break
                except KeyboardInterrupt:
                    print(f"\n{Fore.YELLOW}Interrupted. Type /quit to exit.{Style.RESET_ALL}\n")
                except EOFError:
                    print()
                    break
        except Exception as error:
            print(f"\n{Fore.RED}Fatal error: {error}{Style.RESET_ALL}\n")
            raise


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Nyx Ichos — High-Quality Local-First AI Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("message", nargs="?", default=None, help="Optional single message for non-interactive execution")
    parser.add_argument("--name", default="Nyx Ichos", help="Display name for the assistant")
    parser.add_argument("--attribute", dest="attribute_id", default=None, help="Optional attribute ID (e.g. coding, debugging)")
    parser.add_argument("--no-multimode", action="store_true", default=False, help="Disable multi-mode agent pool")
    parser.add_argument("--verbose", action="store_true", default=False, help="Enable verbose diagnostics and metadata")
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    try:
        cli = CLI(
            name=args.name,
            attribute_id=args.attribute_id,
            multi_mode=not args.no_multimode,
            verbose=args.verbose,
        )
    except AttributeNotFoundError as exc:
        print(f"{Fore.RED}{exc}{Style.RESET_ALL}")
        raise SystemExit(2)

    if args.message:
        print()
        cli.process_input(args.message)
    else:
        cli.run()


if __name__ == "__main__":
    main()
