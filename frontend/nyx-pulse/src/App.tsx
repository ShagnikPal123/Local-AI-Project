/** Nyx Ichos workspace shell.
 *
 * Header with the avatar and host pill, a horizontal tab bar beneath it, and the
 * active panel filling the rest. The tab bar was a 206px left rail in the first
 * build; it moved to the top so panels get the full window width — Strands in
 * particular is a canvas that wants every pixel.
 *
 * The old Rail/Strip switch is now a density control (see components/TopTabs).
 */

import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { BackgroundLayer } from "./components/BackgroundLayer";
import { ClapListener } from "./components/clap/ClapListener";
import "./theme.css";
import {
  api,
  auth,
  endpoints,
  getToken,
  setToken,
  setUnauthorizedHandler,
  type AccountUser,
} from "./api";
import { JoinScreen, LoginScreen } from "./components/AuthScreen";
import { NyxAvatar, type AvatarState } from "./components/NyxAvatar";
import { REDIRECTS, visibleTabs, type TabId } from "./tabs";
import { HubPanel, openSection } from "./components/HubPanel";
import { SettingsWindow, type SettingsPage } from "./components/settings/SettingsWindow";
import { QuitButton } from "./components/QuitButton";
import { AccountsButton } from "./components/accounts/AccountsButton";
import { BuildPanel } from "./panels/BuildPanel";
import { DynamicTab, type TabSpec } from "./panels/DynamicTab";
import { TabFinder } from "./components/TabFinder";
import { EngineGate } from "./components/EngineGate";
import { ComputerBanner } from "./components/ComputerBanner";
import { Companion, KahunaBarButton } from "./components/kahuna/Companion";
import { TopTabs } from "./components/TopTabs";
import { TabBoundary } from "./components/TabBoundary";
import { onWorkspaceEvent } from "./state/workspaceEvents";
import { startMods } from "./state/modsStore";
import { startVoicePlayer } from "./voice/voicePlayer";
import { FileDropOverlay } from "./files/FileDropOverlay";
import { VoiceListener } from "./voice/VoiceListener";
import { ProtoVoiceDock } from "./components/voice/ProtoVoiceDock";
import { VoiceTopBar } from "./components/voice/VoiceTopBar";
import { NotchBridge } from "./components/voice/notchBridge";
import { ParticleField } from "./style/ParticleField";

// Every tab is its own chunk (2026-09-16). The shell used to import all of them up front,
// three.js and the chart and code views included, so the first paint downloaded ~1.2 MB
// before anything could show. Now only the open tab is fetched.
const ChatHome = lazy(() => import("./panels/ChatHome").then((m) => ({ default: m.ChatHome })));
const LearnPanel = lazy(() => import("./panels/LearnPanel").then((m) => ({ default: m.LearnPanel })));
const NotesPanel = lazy(() => import("./panels/notes/NotesPanel").then((m) => ({ default: m.NotesPanel })));
const CodePanel = lazy(() => import("./panels/code/CodePanel").then((m) => ({ default: m.CodePanel })));
const SubAgentsPanel = lazy(() => import("./panels/SubAgentsPanel").then((m) => ({ default: m.SubAgentsPanel })));
const CollabPanel = lazy(() => import("./panels/CollabPanel").then((m) => ({ default: m.CollabPanel })));
const TradingPanel = lazy(() => import("./panels/trading/TradingPanel").then((m) => ({ default: m.TradingPanel })));
const ResearchPanel = lazy(() => import("./panels/research/ResearchPanel").then((m) => ({ default: m.ResearchPanel })));
const ModelsPanel = lazy(() => import("./panels/ModelsPanel").then((m) => ({ default: m.ModelsPanel })));
const KeysPanel = lazy(() => import("./panels/KeysPanel").then((m) => ({ default: m.KeysPanel })));
const ConnectorsPanel = lazy(() => import("./panels/ConnectorsPanel").then((m) => ({ default: m.ConnectorsPanel })));
const AgentsPanel = lazy(() => import("./panels/AgentsPanel").then((m) => ({ default: m.AgentsPanel })));
const ImprovePanel = lazy(() => import("./panels/ImprovePanel").then((m) => ({ default: m.ImprovePanel })));
const AbsorbPanel = lazy(() => import("./panels/absorb/AbsorbPanel").then((m) => ({ default: m.AbsorbPanel })));
const ScreenSharePanel = lazy(() => import("./panels/screen/ScreenSharePanel").then((m) => ({ default: m.ScreenSharePanel })));
const ApplyPanel = lazy(() => import("./panels/apply/ApplyPanel").then((m) => ({ default: m.ApplyPanel })));
const FreeWillPanel = lazy(() => import("./panels/freewill/FreeWillPanel").then((m) => ({ default: m.FreeWillPanel })));
const KahunaPanel = lazy(() => import("./panels/kahuna/KahunaPanel").then((m) => ({ default: m.KahunaPanel })));
const OwnComputerPanel = lazy(() => import("./panels/computer/OwnComputerPanel").then((m) => ({ default: m.OwnComputerPanel })));
const OfficeWorldPanel = lazy(() => import("./panels/OfficeWorldPanel").then((m) => ({ default: m.OfficeWorldPanel })));
const EqualizePanel = lazy(() => import("./panels/equalize/EqualizePanel").then((m) => ({ default: m.EqualizePanel })));
const AdminPanel = lazy(() => import("./panels/AdminPanel").then((m) => ({ default: m.AdminPanel })));
const StorePanel = lazy(() => import("./panels/StorePanel").then((m) => ({ default: m.StorePanel })));

const PROVIDER_KEY = "nyx.chat.provider";

export default function App() {
  const [active, setActiveRaw] = useState<TabId>("nyx");
  // Settings is a window now, opened from the gear in the top bar (redesign 2026-10-10).
  const [settings, setSettings] = useState<{ open: boolean; page?: SettingsPage }>({ open: false });
  // Tabs that were merged or removed land in their new home: a section of a merged tab, a Settings page, or a
  // window in the chat (src/tabs.ts REDIRECTS).
  const setActive = useCallback((tab: TabId) => {
    const moved = REDIRECTS[tab];
    if (!moved) { setActiveRaw(tab); return; }
    if (moved.kind === "settings") { setSettings({ open: true, page: moved.page }); return; }
    if (moved.kind === "window") {
      setActiveRaw("nyx");
      window.setTimeout(() => window.dispatchEvent(new CustomEvent("ichos:open-window", { detail: { kind: moved.window } })), 0);
      return;
    }
    if (moved.section) openSection(moved.tab, moved.section);
    setActiveRaw(moved.tab);
  }, []);
  useEffect(() => {
    const onOpen = (event: Event) => setSettings({ open: true, page: (event as CustomEvent<{ page?: SettingsPage }>).detail?.page });
    window.addEventListener("ichos:open-settings", onOpen);
    return () => window.removeEventListener("ichos:open-settings", onOpen);
  }, []);
  const [avatar, setAvatar] = useState<AvatarState>("idle");
  const [online, setOnline] = useState<boolean | null>(null);

  // Auth gate. `claimed` comes from the backend: false means a fresh local
  // install with no owner account, which works without a login.
  const [claimed, setClaimed] = useState<boolean | null>(null);
  const [user, setUser] = useState<AccountUser | null>(null);
  const [signedIn, setSignedIn] = useState<boolean>(() => Boolean(getToken()));
  const [invite, setInvite] = useState<string>(() => {
    try {
      return new URLSearchParams(window.location.search).get("invite") ?? "";
    } catch {
      return "";
    }
  });

  // A 401 anywhere means the session died — most often a backend restart, since
  // sessions are in-memory by design. Drop straight back to the login screen.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setSignedIn(false);
      setUser(null);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  // Confirm a stored token is still valid before trusting it.
  useEffect(() => {
    if (!getToken()) return;
    let alive = true;
    void auth.me().then((result) => {
      if (!alive) return;
      if (result.ok) {
        setUser(result.data.user);
        setSignedIn(true);
      } else {
        setSignedIn(false);
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    let timer = 0;
    // One failed ping is not "off": a restart takes a second or two, and a
    // gate that flashes up and away again reads as a crash. Confirm with a quick
    // second look before showing the Turn on screen.
    const ping = async (confirming = false) => {
      const result = await endpoints.health();
      if (!alive) return;
      if (result.ok) {
        setOnline(true);
        setClaimed(Boolean(result.data.claimed));
      } else if (confirming) {
        setOnline(false);
      } else {
        timer = window.setTimeout(() => void ping(true), 1500);
        return;
      }
      timer = window.setTimeout(() => void ping(false), 5000);
    };
    void ping();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, []);

  const signOut = useCallback(async () => {
    await auth.logout();
    setToken(null);
    setSignedIn(false);
    setUser(null);
  }, []);

  const onActivity = useCallback((s: AvatarState) => setAvatar(s), []);

  // The conversation no longer lives here: turns live in the module turn
  // store and transcripts in the ChatPanel's per-chat map, both of which
  // outlive every remount. App keeps only the provider choice.
  const [provider, setProvider] = useState<string>(() => {
    try {
      return localStorage.getItem(PROVIDER_KEY) ?? "";
    } catch {
      return "";
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(PROVIDER_KEY, provider);
    } catch {
      /* private browsing — the choice simply will not persist */
    }
  }, [provider]);

  // One live workspace connection for the whole shell: toasts, cross-window
  // turn summaries, theme/tab/agent events. The hook itself reconnects with
  // backoff; this effect just ties its lifetime to the app's.
  useEffect(() => onWorkspaceEvent(() => {}), []);
  // Mods, and the assistant's live theme and tab changes (state/modsStore.ts).
  useEffect(() => startMods(), []);
  // Nyx's `speak` tool broadcasts `voice.say`; one open window plays it.
  useEffect(() => { startVoicePlayer(); }, []);

  // Presence: a heartbeat on real input (at most once a minute) and on every tab change.
  // It tells the engine when the owner is away (quiet work) and teaches next-tab predictions.
  useEffect(() => {
    let last = 0;
    const ping = () => {
      const now = Date.now();
      if (now - last < 60_000) return;
      last = now;
      void api.post("/api/presence", {});
    };
    const events = ["pointerdown", "keydown", "wheel"] as const;
    events.forEach((name) => window.addEventListener(name, ping, { passive: true }));
    return () => events.forEach((name) => window.removeEventListener(name, ping));
  }, []);
  // The tab still teaches presence (quiet work while away); the "Next:" guess button is gone (owner, 2026-10-10).
  useEffect(() => { void api.post("/api/presence", { tab: active }); }, [active]);

  // User-defined tabs (ROADMAP CC). Loaded from the server and appended to the
  // shipped set, so someone's own tabs sit alongside the built-in ones.
  const [userTabs, setUserTabs] = useState<TabSpec[]>([]);
  const [finderOpen, setFinderOpen] = useState(false);

  const loadUserTabs = useCallback(async () => {
    const result = await api.get<{ tabs: TabSpec[] }>("/api/tabs");
    if (result.ok) setUserTabs(result.data.tabs);
  }, []);

  useEffect(() => { void loadUserTabs(); }, [loadUserTabs]);
  // A tab Nyx made, edited or deleted (ui_create_tab and friends) shows up without a reload.
  useEffect(() => {
    const onChanged = () => void loadUserTabs();
    window.addEventListener("nyx:tabs-changed", onChanged);
    return () => window.removeEventListener("nyx:tabs-changed", onChanged);
  }, [loadUserTabs]);

  // Cmd/Ctrl-K opens find-or-create, the way every other workspace does it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setFinderOpen(true);
      }
      // F7 is caret browsing in Chrome and Edge: it puts a blinking caret in
      // text nobody can type into. One stray press made the app look broken,
      // so the key does nothing here (Project Null N101).
      if (e.key === "F7" && !e.ctrlKey && !e.metaKey && !e.altKey) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Presentation only — the server enforces the real boundary on every request.
  const tabs = visibleTabs(user?.role);

  // "/tab learn", "Create a skill instead": open a tab by id or by its label.
  useEffect(() => {
    const onOpen = (event: Event) => {
      const wanted = String((event as CustomEvent<{ tab?: string }>).detail?.tab ?? "").trim().toLowerCase();
      const all = [...tabs.map((t) => ({ id: t.id as string, label: t.label })), ...userTabs.map((t) => ({ id: t.id, label: t.label || t.id }))];
      const hit = all.find((t) => t.id === wanted || t.label.toLowerCase() === wanted)
        ?? all.find((t) => wanted && (t.label.toLowerCase().startsWith(wanted) || t.id.startsWith(wanted)));
      if (hit) { setActive(hit.id as TabId); return; }
      // A tab made a moment ago (Create's Make It a Tab, Apply) is not in the list yet: read it again, then open.
      void api.get<{ tabs: TabSpec[] }>("/api/tabs").then((result) => {
        if (!result.ok) return;
        setUserTabs(result.data.tabs);
        const fresh = result.data.tabs.find((t) => t.id === wanted || (t.label || "").toLowerCase() === wanted);
        if (fresh) setActive(fresh.id as TabId);
      });
    };
    window.addEventListener("nyx:open-tab", onOpen);
    return () => window.removeEventListener("nyx:open-tab", onOpen);
  }, [tabs, userTabs]);
  const activeUserTab = userTabs.find((t) => t.id === active);

  async function deleteUserTab(tabId: string) {
    await api.del(`/api/tabs/${tabId}`);
    setActive("nyx");
    await loadUserTabs();
  }

  const hostTone =
    online === null ? "var(--color-neutral-600)" : online ? "var(--color-ok)" : "var(--color-warn)";
  const hostLabel = online === null ? "Connecting" : online ? "Running on this PC" : "Off";

  // When the engine is off, nothing on the page can work, so the fix gets the
  // whole screen (EngineGate) rather than a badge. Coming back from off reloads
  // the page: tabs, chats and settings were all unreachable while it was down.
  const offlineNow = online === false;
  const engineCameBack = useCallback(() => window.location.reload(), []);

  // An invite link takes priority over everything: the recipient has no account yet.
  if (invite) {
    return (
      <JoinScreen
        invite={invite}
        onJoined={() => {
          window.history.replaceState({}, "", window.location.pathname);
          setInvite("");
        }}
      />
    );
  }

  // Only gate once the backend has actually told us it is claimed. Gating on an
  // unknown state would lock the user out whenever the backend is briefly down.
  if (claimed === true && !signedIn) {
    return (
      <LoginScreen
        onSignedIn={(account) => {
          setUser(account);
          setSignedIn(true);
        }}
      />
    );
  }

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <BackgroundLayer />
      <ParticleField />
      {/* Listens for the sounds you taught it when you are away or offline (N86). */}
      <ClapListener />
      {/* Voice is on (its name, a clap, or Talk): what you are saying and that it is listening (Update 1, U26). */}
      <VoiceTopBar />
      <header className="shell-bar">
        <div className="shell-brand">
          <NyxAvatar state={avatar} size={28} />
          <div style={{ lineHeight: 1 }}>
            <div className="shell-brand__name">NYX ICHOS</div>
            <div className="shell-brand__by">Created by Shagnik</div>
          </div>
        </div>

        <button
          className="shell-host"
          onClick={() => setSettings({ open: true, page: "status" })}
          title={online ? "The engine is running on this computer — open its status" : "The engine is off"}
        >
          <span className="shell-host__dot" style={{ background: hostTone, boxShadow: `0 0 8px ${hostTone}` }} />
          <span className="shell-host__label">{hostLabel}</span>
        </button>

        <div className="shell-actions">
          <button
            type="button"
            className="shell-icon-btn"
            onClick={() => setSettings({ open: true })}
            aria-expanded={settings.open}
            aria-haspopup="dialog"
            title="Settings — status, power, sessions & memory and more"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
            Settings
          </button>
          <span className="shell-sep" aria-hidden="true" />
          {user && (
            <button className="shell-icon-btn" onClick={() => void signOut()} title={`Signed in as ${user.email} (${user.role})`}>
              {user.role === "owner" ? "Owner" : user.role} · Sign out
            </button>
          )}
          {/* Big Kahuna's chat opens from here, not from a button floating over the chat (Update 1, U15). */}
          <KahunaBarButton />
          {/* Accounts sit next to Log Out: separate spaces on this PC, each with its own files (owner, 2026-09-26). */}
          {(!user || user.role === "owner") && <AccountsButton />}
          {(!user || user.role === "owner" || user.role === "admin") && <QuitButton signedIn={Boolean(user)} />}
        </div>
      </header>

      <TopTabs
        tabs={tabs}
        userTabs={userTabs}
        active={active}
        onSelect={(id) => setActive(id as TabId)}
        onNewTab={() => setFinderOpen(true)}
      />

      <main style={{ flex: 1, minWidth: 0, minHeight: 0, background: "var(--color-bg)" }}>
        <TabBoundary key={active} name={tabs.find((t) => t.id === active)?.label ?? "This"}>
        <Suspense fallback={<div className="tab-loading" role="status"><span className="tab-loading__dot" />Opening…</div>}>
        {active === "nyx" && <ChatHome onActivity={onActivity} provider={provider} onProvider={setProvider} />}
        {active === "learn" && <LearnPanel />}
        {active === "notes" && <NotesPanel />}
        {active === "code" && <CodePanel />}
        {active === "collab" && <CollabPanel />}
        {active === "trading" && <TradingPanel />}
        {active === "build" && <BuildPanel />}
        {active === "research" && (
          <HubPanel id="research" title="Research Lab" sections={[
            { id: "research", label: "Research", purpose: "Deep research on any question, with sources you can check.", render: () => <ResearchPanel /> },
            { id: "absorb", label: "Absorb", purpose: "Ichos studies documents and keeps what you approve.", render: () => <AbsorbPanel /> },
            { id: "apply", label: "Apply", purpose: "Describe a change to Ichos itself; each step applies only when you press it.", render: () => <ApplyPanel /> },
          ]} />
        )}
        {active === "agents" && (
          <HubPanel id="agents" title="Agents" sections={[
            { id: "agents", label: "Team", purpose: "Every agent Ichos can call, how they connect, and what each is for.", render: () => <AgentsPanel /> },
            { id: "subagents", label: "Sub-agents", purpose: "Your own helpers: make one, give it a job, run it.", render: () => <SubAgentsPanel /> },
          ]} />
        )}
        {active === "computer" && (
          <HubPanel id="computer" title="Computer" sections={[
            { id: "computer", label: "Ichos Computer", purpose: "A sandboxed desktop of Ichos's own — it works there, never on yours unasked.", render: () => <OwnComputerPanel /> },
            { id: "screen", label: "Screen Share", purpose: "Share a screen or a window; Ichos helps one approved step at a time.", render: () => <ScreenSharePanel /> },
          ]} />
        )}
        {active === "connectors" && (
          <HubPanel id="connectors" title="Connections" sections={[
            { id: "connectors", label: "Connectors", purpose: "Accounts and services Ichos can use for you.", render: () => <ConnectorsPanel /> },
            { id: "keys", label: "Keys & models", purpose: "API keys, and which model does which job.", render: () => <KeysPanel /> },
            { id: "models", label: "Models", purpose: "Every model Ichos can reach, local and online.", render: () => <ModelsPanel /> },
            { id: "store", label: "Add capability", purpose: "Skills, tools and connectors you can add.", render: () => <StorePanel /> },
          ]} />
        )}
        {active === "improve" && <ImprovePanel />}
        {active === "freewill" && <FreeWillPanel />}
        {active === "kahuna" && <KahunaPanel />}
        {active === "office" && <OfficeWorldPanel />}
        {active === "equalize" && <EqualizePanel />}
        {active === "admin" && <AdminPanel />}
        </Suspense>
        </TabBoundary>
        {activeUserTab && (
          <DynamicTab
            spec={activeUserTab}
            onChanged={(updated) =>
              setUserTabs((tabs) => tabs.map((t) => (t.id === updated.id ? updated : t)))
            }
            onDelete={() => void deleteUserTab(activeUserTab.id)}
          />
        )}
      </main>

      {offlineNow && <EngineGate onOnline={engineCameBack} />}
      <ComputerBanner />
      <Companion />
      <FileDropOverlay />
      <VoiceListener />
      <ProtoVoiceDock />
      <NotchBridge />

      {settings.open && <SettingsWindow initial={settings.page} onClose={() => setSettings({ open: false })} />}

      {finderOpen && (
        <TabFinder
          onOpen={(tabId) => setActive(tabId as TabId)}
          onCreated={async (spec) => {
            await loadUserTabs();
            setActive(spec.id as TabId);
            setFinderOpen(false);
          }}
          onClose={() => setFinderOpen(false)}
        />
      )}
    </div>
  );
}
