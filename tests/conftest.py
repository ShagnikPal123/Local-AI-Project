"""Shared test fixtures.

Isolates on-disk state so the suite cannot write into the user's real data.

Before this existed, any test constructing a bare ``ChatService`` fell through to
the default ``chats.json`` / ``memory.json`` in the project root and appended to
them. A single run added ~50 assistant messages to real chat history, and the
accumulated junk made ``test_chat_sessions`` fail intermittently depending on
what previous runs had left behind.
"""

import os
from pathlib import Path

import pytest

import chat_sessions
import memory
import paths
import provider_specs


def pytest_configure(config: pytest.Config) -> None:
    """Give each pytest process its own temp folder under ``local_pytest_tmp``.

    Several sessions (and several people) run the suite at the same time on this machine. They all
    got ``--basetemp=./local_pytest_tmp`` from ``pytest.ini``, and each run began by deleting that
    folder — including the one another run was using, which failed with "directory is not empty" or
    took a test's files away mid-run.
    """
    base = getattr(config.option, "basetemp", None)
    if base and Path(str(base)).name == "local_pytest_tmp":
        config.option.basetemp = Path(str(base)) / f"pid{os.getpid()}"


@pytest.fixture(autouse=True)
def isolate_persistent_stores(tmp_path, monkeypatch):
    """Point the default chat, memory and provider-spec files at a temp directory.

    Tests that pass an explicit path or store are unaffected; this only replaces
    the fallback used when nothing is supplied.

    The provider store is here for a different reason than the other two. It is
    read-only in tests, so nothing was being corrupted — but the router builds
    its fallback order from whatever specs exist, so a developer who had added
    one real provider on their own machine saw ``test_router`` fail on an order
    that was correct. Test outcomes must not depend on the machine's config.
    """
    original_memory_init = memory.MemoryStore.__init__
    original_chat_init = chat_sessions.ChatSessionStore.__init__
    original_spec_init = provider_specs.ProviderSpecStore.__init__

    def memory_init(self, path=None):
        if path is None:
            path = tmp_path / "memory.json"
        original_memory_init(self, path=path)

    def chat_init(self, path=None, memory_store=None):
        if path is None:
            path = tmp_path / "chats.json"
        original_chat_init(self, path=path, memory_store=memory_store)

    def spec_init(self, path=None):
        if path is None:
            path = tmp_path / "provider_specs.json"
        original_spec_init(self, path=path)

    monkeypatch.setattr(memory.MemoryStore, "__init__", memory_init)
    monkeypatch.setattr(chat_sessions.ChatSessionStore, "__init__", chat_init)
    monkeypatch.setattr(provider_specs.ProviderSpecStore, "__init__", spec_init)

    # The class patch cannot reach PROVIDER_SPECS: it is a module-level singleton
    # built at import time, long before any fixture runs. `build_custom_providers`
    # resolves it through the module at call time, so replacing the attribute is
    # what actually isolates the router.
    monkeypatch.setattr(
        provider_specs,
        "PROVIDER_SPECS",
        provider_specs.ProviderSpecStore(tmp_path / "provider_specs.json"),
    )

    # Key health and the owner's saved model pick (Requests H6/H8/H11): a fake
    # provider named "gemini" must never mark the owner's real Gemini key failed.
    import key_pool
    import model_choice

    monkeypatch.setattr(key_pool, "_path", lambda: tmp_path / "key_health.json")
    monkeypatch.setattr(model_choice, "_path", lambda: tmp_path / "model_choice.json")

    # The owner's swarm size (Update 1): a test that saves 2 must not shrink their real swarm.
    import swarm

    monkeypatch.setattr(swarm, "_path", lambda: tmp_path / "swarm.json")

    # Where Nyx may work (Update 1, U49): a test that sets "never" must not lock the owner's real screen setting.
    import own_computer

    monkeypatch.setattr(own_computer, "_path", lambda: tmp_path / "own_computer.json")

    # Which Google apps each address allowed (Update 1, connectors): the sign-in tests use a made-up owner@gmail.com,
    # which landed in the real data folder before this.
    import google_oauth

    monkeypatch.setattr(google_oauth, "_granted_path", lambda: tmp_path / "google_granted.json")

    # Turns run in tests must not teach the owner's real learner or fill the real
    # response cache (both are wired into every streamed turn).
    try:
        import learning
        import learning_hooks
        import response_cache
        import routes_learning

        learner = learning.Learner(
            turns_path=tmp_path / "learning" / "turns.jsonl",
            models_path=tmp_path / "learning" / "models.json",
            feedback_path=tmp_path / "learning" / "feedback.jsonl",
        )
        cache = response_cache.ResponseCache(path=tmp_path / "learning" / "cache.json")
        # routes_learning imported its own references at import time; without it
        # here, /api/feedback and /api/cache/clear in tests hit the real stores.
        for module in (learning, learning_hooks, routes_learning):
            monkeypatch.setattr(module, "LEARNER", learner, raising=False)
        for module in (response_cache, learning_hooks, routes_learning):
            monkeypatch.setattr(module, "RESPONSE_CACHE", cache, raising=False)
    except Exception:
        pass

    # The prompt optimizer would call a real model on every test turn; tests get an
    # isolated, switched-off copy (tests of the optimizer build their own).
    try:
        import json as _json

        import prompt_optimizer

        settings_file = tmp_path / "prompt_optimizer.json"
        settings_file.write_text(_json.dumps({"enabled": False, "online": False}), encoding="utf-8")

        def _offline(*_args, **_kwargs):
            raise RuntimeError("tests are offline")

        monkeypatch.setattr(prompt_optimizer, "OPTIMIZER",
                            prompt_optimizer.PromptOptimizer(settings_path=settings_file, model_fn=_offline))
    except Exception:
        pass

    # The Command Zone's usage rollup and inbox (ideas, tab suggestions, its chat id) are the owner's.
    try:
        import command_zone

        monkeypatch.setattr(command_zone, "USAGE", command_zone.UsageRollup(
            tmp_path / "command_zone_usage.json", turns_path=tmp_path / "learning" / "turns.jsonl"))
        monkeypatch.setattr(command_zone, "INBOX", command_zone.Inbox(tmp_path / "command_zone.json"))
    except Exception:
        pass

    # The owner's mods reach every prompt and can block tools; a mod's theme writes the owner's look.
    try:
        import mods
        import ui_state

        monkeypatch.setattr(mods, "MOD_STORE", mods.ModStore(tmp_path / "mods.json"))
        monkeypatch.setattr(ui_state, "UI_STATE", ui_state.UiState(tmp_path / "ui_state.json"))
    except Exception:
        pass

    # The owner's accounts (local_accounts) reach every prompt as "## This account", the fast
    # path included, so a named Main with a purpose on this PC made test_fast_response count a
    # third message that only exists on his machine. Tests start in a bare Main with no index;
    # a test that points DATA_DIR at its own folder (test_local_accounts) keeps the index there.
    real_data_dir = paths.DATA_DIR
    real_index_path = paths.accounts_index_path

    def accounts_index_path():
        if paths.DATA_DIR == real_data_dir:
            return tmp_path / "accounts" / "index.json"
        return real_index_path()

    monkeypatch.setattr(paths, "accounts_index_path", accounts_index_path)
    monkeypatch.setattr(paths, "ACTIVE_ACCOUNT", paths.MAIN_ACCOUNT)

    # Tab-visit predictions and presence are per-owner state; tests get their own.
    try:
        import predictor
        import presence

        monkeypatch.setattr(predictor, "PREDICTOR", predictor.Predictor(tmp_path / "predictions.json"))
        presence.reset()
    except Exception:
        pass

    # Benched (recently failing or retired) models are process-wide; each test starts with none.
    try:
        import model_roles

        monkeypatch.setattr(model_roles, "_OUTAGE_COOLDOWN", {})
    except Exception:
        pass

    # Super brain and Nyx Core learn from every turn; tests get throwaway copies.
    try:
        import nyx_core
        import super_brain

        monkeypatch.setattr(super_brain, "BRAIN", super_brain.SuperBrain(tmp_path / "brain" / "brain.db", background=False))
        monkeypatch.setattr(nyx_core, "CORE", nyx_core.NyxCore(tmp_path / "core"))
        monkeypatch.setattr(nyx_core, "observe_async", lambda **_turn: None)
    except Exception:
        pass

    # Agents created in tests (POST /api/agents, create_agent) must not join the
    # owner's real team file.
    try:
        import agent_runtime

        monkeypatch.setattr(agent_runtime, "_custom_agents_path", lambda: tmp_path / "custom_agents.json")
    except Exception:
        pass

    # Identity 0 (Big Kahuna) gets a throwaway store and is OFF unless a test turns it on, so every
    # router test sees the chain it was written for; tests of Identity 0 enable it themselves.
    try:
        from identity0 import competence, experience, members, state as kahuna_state

        kahuna_state.use_directory(tmp_path / "kahuna")
        kahuna_state.write_json("settings.json", {"enabled": False, "ollama_autostart": False})
        competence.reset_cache()
        experience.reset_cache()
        members.forget_cache()
    except Exception:
        pass
    yield
    try:
        from identity0 import competence as _competence, state as _kahuna_state

        _kahuna_state.use_directory(None)
        _competence.reset_cache()
    except Exception:
        pass
