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
import { visibleTabs, type ShellLayout, type TabId } from "./tabs";
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
import { startVoicePlayer } from "./voice/voicePlayer";
import { FileDropOverlay } from "./files/FileDropOverlay";
import { VoiceListener } from "./voice/VoiceListener";
import { ProtoVoiceDock } from "./components/voice/ProtoVoiceDock";
import { VoiceTopBar } from "./components/voice/VoiceTopBar";

// Every tab is its own chunk (2026-09-16). The shell used to import all of them up front,
// three.js and the chart and code views included, so the first paint downloaded ~1.2 MB
// before anything could show. Now only the open tab is fetched.
const NyxPanel = lazy(() => import("./panels/NyxPanel").then((m) => ({ default: m.NyxPanel })));
const LearnPanel = lazy(() => import("./panels/LearnPanel").then((m) => ({ default: m.LearnPanel })));
const NotesPanel = lazy(() => import("./panels/notes/NotesPanel").then((m) => ({ default: m.NotesPanel })));
const CodePanel = lazy(() => import("./panels/code/CodePanel").then((m) => ({ default: m.CodePanel })));
const SubAgentsPanel = lazy(() => import("./panels/SubAgentsPanel").then((m) => ({ default: m.SubAgentsPanel })));
const CollabPanel = lazy(() => import("./panels/CollabPanel").then((m) => ({ default: m.CollabPanel })));
const TradingPanel = lazy(() => import("./panels/trading/TradingPanel").then((m) => ({ default: m.TradingPanel })));
const GameStudioPanel = lazy(() => import("./panels/game/GameStudioPanel").then((m) => ({ default: m.GameStudioPanel })));
const ResearchPanel = lazy(() => import("./panels/research/ResearchPanel").then((m) => ({ default: m.ResearchPanel })));
const DashboardPanel = lazy(() => import("./panels/DashboardPanel").then((m) => ({ default: m.DashboardPanel })));
const ModelsPanel = lazy(() => import("./panels/ModelsPanel").then((m) => ({ default: m.ModelsPanel })));
const KeysPanel = lazy(() => import("./panels/KeysPanel").then((m) => ({ default: m.KeysPanel })));
const SettingsPanel = lazy(() => import("./panels/SettingsPanel").then((m) => ({ default: m.SettingsPanel })));
const ConnectorsPanel = lazy(() => import("./panels/ConnectorsPanel").then((m) => ({ default: m.ConnectorsPanel })));
const WorkPanel = lazy(() => import("./panels/WorkPanel").then((m) => ({ default: m.WorkPanel })));
const AgentsPanel = lazy(() => import("./panels/AgentsPanel").then((m) => ({ default: m.AgentsPanel })));
const StrandsPanel = lazy(() => import("./panels/StrandsPanel").then((m) => ({ default: m.StrandsPanel })));
const PowerPanel = lazy(() => import("./panels/PowerPanel").then((m) => ({ default: m.PowerPanel })));
const ImprovePanel = lazy(() => import("./panels/ImprovePanel").then((m) => ({ default: m.ImprovePanel })));
const AbsorbPanel = lazy(() => import("./panels/absorb/AbsorbPanel").then((m) => ({ default: m.AbsorbPanel })));
const ScreenSharePanel = lazy(() => import("./panels/screen/ScreenSharePanel").then((m) => ({ default: m.ScreenSharePanel })));
const ApplyPanel = lazy(() => import("./panels/apply/ApplyPanel").then((m) => ({ default: m.ApplyPanel })));
const FreeWillPanel = lazy(() => import("./panels/freewill/FreeWillPanel").then((m) => ({ default: m.FreeWillPanel })));
const KahunaPanel = lazy(() => import("./panels/kahuna/KahunaPanel").then((m) => ({ default: m.KahunaPanel })));
const OwnComputerPanel = lazy(() => import("./panels/computer/OwnComputerPanel").then((m) => ({ default: m.OwnComputerPanel })));
const OfficePanel = lazy(() => import("./panels/office/OfficePanel").then((m) => ({ default: m.OfficePanel })));
const AdminPanel = lazy(() => import("./panels/AdminPanel").then((m) => ({ default: m.AdminPanel })));
const StorePanel = lazy(() => import("./panels/StorePanel").then((m) => ({ default: m.StorePanel })));

const LAYOUT_KEY = "nyx.layout";
const PROVIDER_KEY = "nyx.chat.provider";

export default function App() {
  const [active, setActiveRaw] = useState<TabId>("nyx");
  // Chat and the brain live together now; old links to either land on the Nyx tab.
  const setActive = useCallback((tab: TabId) => setActiveRaw(tab === "chat" ? "nyx" : tab), []);
  const [layout, setLayout] = useState<ShellLayout>(() => {
    try {
      return (localStorage.getItem(LAYOUT_KEY) as ShellLayout) || "rail";
    } catch {
      return "rail";
    }
  });
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

  useEffect(() => {
    try {
      localStorage.setItem(LAYOUT_KEY, layout);
    } catch {
      /* private browsing — layout simply will not persist */
    }
  }, [layout]);

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
  const [nextTab, setNextTab] = useState<{ tab: string; confidence: number } | null>(null);
  useEffect(() => {
    let alive = true;
    void api.post("/api/presence", { tab: active }).then(() =>
      api.get<{ next_tab: { tab: string; confidence: number } | null }>("/api/predict").then((result) => {
        if (alive && result.ok) setNextTab(result.data.next_tab);
      }),
    );
    return () => { alive = false; };
  }, [active]);

  // User-defined tabs (ROADMAP CC). Loaded from the server and appended to the
  // shipped set, so someone's own tabs sit alongside the built-in ones.
  const [userTabs, setUserTabs] = useState<TabSpec[]>([]);
  const [finderOpen, setFinderOpen] = useState(false);

  const loadUserTabs = useCallback(async () => {
    const result = await api.get<{ tabs: TabSpec[] }>("/api/tabs");
    if (result.ok) setUserTabs(result.data.tabs);
  }, []);

  useEffect(() => { void loadUserTabs(); }, [loadUserTabs]);

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
      if (hit) setActive(hit.id as TabId);
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
          onClick={() => setActive("settings")}
          title={online ? "Nyx's engine is running on this computer — engine settings" : "Nyx's engine is off"}
        >
          <span className="shell-host__dot" style={{ background: hostTone, boxShadow: `0 0 8px ${hostTone}` }} />
          {hostLabel}
        </button>

        {nextTab && nextTab.tab !== active && nextTab.confidence >= 0.4 && tabs.some((t) => t.id === nextTab.tab) && (
          <button className="shell-host" onClick={() => setActive(nextTab.tab as TabId)}
            title={`You usually go here next (${Math.round(nextTab.confidence * 100)}% of the time)`}>
            Next: {tabs.find((t) => t.id === nextTab.tab)?.label} →
          </button>
        )}

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <div className="segmented" title="How much room each tab takes in the bar">
            {(["rail", "strip"] as ShellLayout[]).map((l) => (
              <button key={l} onClick={() => setLayout(l)} aria-pressed={layout === l}>
                {l === "rail" ? "Comfortable" : "Compact"}
              </button>
            ))}
          </div>
          <button className="btn btn-primary" onClick={() => setActive("store")}>
            + Add capability
          </button>
          {user && (
            <button
              className="btn btn-secondary"
              onClick={() => void signOut()}
              title={`Signed in as ${user.email} (${user.role})`}
            >
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
        density={layout}
        onSelect={(id) => setActive(id as TabId)}
        onNewTab={() => setFinderOpen(true)}
      />

      <main style={{ flex: 1, minWidth: 0, minHeight: 0, background: "var(--color-bg)" }}>
        <TabBoundary key={active} name={tabs.find((t) => t.id === active)?.label ?? "This"}>
        <Suspense fallback={<div className="tab-loading" role="status"><span className="tab-loading__dot" />Opening…</div>}>
        {active === "nyx" && (
          <NyxPanel onActivity={onActivity} provider={provider} onProvider={setProvider} onOpenTab={(tab) => setActive(tab as TabId)} />
        )}
        {active === "learn" && <LearnPanel />}
        {active === "notes" && <NotesPanel />}
        {active === "code" && <CodePanel />}
        {active === "subagents" && <SubAgentsPanel />}
        {active === "collab" && <CollabPanel />}
        {active === "trading" && <TradingPanel />}
        {active === "build" && <BuildPanel />}
        {active === "games" && <GameStudioPanel />}
        {active === "research" && <ResearchPanel />}
        {active === "strands" && <StrandsPanel state={avatar} onActivity={onActivity} />}
        {active === "dashboard" && <DashboardPanel />}
        {active === "work" && <WorkPanel />}
        {active === "models" && <ModelsPanel />}
        {active === "keys" && <KeysPanel />}
        {active === "agents" && <AgentsPanel />}
        {active === "connectors" && <ConnectorsPanel />}
        {active === "store" && <StorePanel />}
        {active === "power" && <PowerPanel />}
        {active === "improve" && <ImprovePanel />}
        {active === "absorb" && <AbsorbPanel />}
        {active === "screen" && <ScreenSharePanel />}
        {active === "apply" && <ApplyPanel />}
        {active === "freewill" && <FreeWillPanel />}
        {active === "kahuna" && <KahunaPanel />}
        {active === "office" && <OfficePanel />}
        {active === "computer" && <OwnComputerPanel />}
        {active === "admin" && <AdminPanel />}
        {active === "settings" && <SettingsPanel />}
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
