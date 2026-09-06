/** Nyx Ichos workspace shell.
 *
 * Header with the avatar and host pill, a horizontal tab bar beneath it, and the
 * active panel filling the rest. The tab bar was a 206px left rail in the first
 * build; it moved to the top so panels get the full window width — Strands in
 * particular is a canvas that wants every pixel.
 *
 * The old Rail/Strip switch is now a density control (see components/TopTabs).
 */

import { useCallback, useEffect, useState } from "react";
import "./theme.css";
import {
  api,
  auth,
  endpoints,
  getToken,
  loadChatHistory,
  setToken,
  setUnauthorizedHandler,
  type AccountUser,
  type ChatMessage,
} from "./api";
import { JoinScreen, LoginScreen } from "./components/AuthScreen";
import { NyxAvatar, type AvatarState } from "./components/NyxAvatar";
import { visibleTabs, type ShellLayout, type TabId } from "./tabs";
import { ChatPanel } from "./panels/ChatPanel";
import { DashboardPanel } from "./panels/DashboardPanel";
import { ModelsPanel } from "./panels/ModelsPanel";
import { SettingsPanel } from "./panels/SettingsPanel";
import { ConnectorsPanel } from "./panels/ConnectorsPanel";
import { WorkPanel } from "./panels/WorkPanel";
import { AgentsPanel } from "./panels/AgentsPanel";
import { StrandsPanel } from "./panels/StrandsPanel";
import { PowerPanel } from "./panels/PowerPanel";
import { AdminPanel } from "./panels/AdminPanel";
import { DynamicTab, type TabSpec } from "./panels/DynamicTab";
import { TabFinder } from "./components/TabFinder";
import { TopTabs } from "./components/TopTabs";
import { StorePanel } from "./panels/StorePanel";

const LAYOUT_KEY = "nyx.layout";
const CHAT_KEY = "nyx.chat.transcript";
const PROVIDER_KEY = "nyx.chat.provider";

function readStoredTranscript(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(CHAT_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? (parsed as ChatMessage[]) : [];
  } catch {
    return [];
  }
}

export default function App() {
  const [active, setActive] = useState<TabId>("chat");
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
    const ping = async () => {
      const result = await endpoints.health();
      if (!alive) return;
      setOnline(result.ok);
      if (result.ok) setClaimed(Boolean(result.data.claimed));
    };
    void ping();
    const timer = setInterval(ping, 10_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const signOut = useCallback(async () => {
    await auth.logout();
    setToken(null);
    setSignedIn(false);
    setUser(null);
  }, []);

  const onActivity = useCallback((s: AvatarState) => setAvatar(s), []);

  // The conversation lives here, not in ChatPanel.
  //
  // ChatPanel is unmounted every time another tab is selected, so anything it
  // held in its own state vanished on the first tab switch — the "chats
  // disappear" bug. App outlives every panel, so the transcript survives.
  //
  // A page reload is a separate problem: App unmounts too. The backend keeps
  // each ChatService's history in memory but exposes no route that returns it
  // (`/api/chats` lists chat ids only), so the transcript is mirrored to
  // localStorage and re-read on boot. `loadChatHistory` still asks the server
  // first and wins when a backend that does serve transcripts appears — the
  // local mirror is the fallback, not the source of truth.
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>(readStoredTranscript);
  const [chatDraft, setChatDraft] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatRestored, setChatRestored] = useState<"server" | "local" | null>(() =>
    readStoredTranscript().length > 0 ? "local" : null,
  );
  const [provider, setProvider] = useState<string>(() => {
    try {
      return localStorage.getItem(PROVIDER_KEY) ?? "";
    } catch {
      return "";
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(CHAT_KEY, JSON.stringify(chatMessages.slice(-200)));
    } catch {
      /* private browsing — the transcript still survives tab switches */
    }
  }, [chatMessages]);

  useEffect(() => {
    try {
      localStorage.setItem(PROVIDER_KEY, provider);
    } catch {
      /* private browsing — the choice simply will not persist */
    }
  }, [provider]);

  useEffect(() => {
    let alive = true;
    void loadChatHistory().then((history) => {
      // Only a non-empty server transcript replaces what is on screen. An empty
      // one would silently wipe a conversation the user can still see.
      if (!alive || !history || history.length === 0) return;
      setChatMessages(history);
      setChatRestored("server");
    });
    return () => {
      alive = false;
    };
  }, []);

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
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Presentation only — the server enforces the real boundary on every request.
  const tabs = visibleTabs(user?.role);
  const activeUserTab = userTabs.find((t) => t.id === active);

  async function deleteUserTab(tabId: string) {
    await api.del(`/api/tabs/${tabId}`);
    setActive("strands");
    await loadUserTabs();
  }

  const hostTone =
    online === null ? "var(--color-neutral-600)" : online ? "var(--color-ok)" : "var(--color-warn)";
  const hostLabel = online === null ? "Connecting" : online ? "Local" : "Backend offline";

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
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: "10px 16px",
          background: "linear-gradient(180deg,#1b1e2f,#161826)",
          boxShadow: "inset 0 -1px 0 var(--color-divider)",
          flex: "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <NyxAvatar state={avatar} size={30} />
          <div style={{ lineHeight: 1 }}>
            <div style={{ fontFamily: "var(--font-heading)", fontWeight: 500, fontSize: 15, letterSpacing: ".02em" }}>
              Nyx Ichos
            </div>
            <div style={{ fontSize: 9, letterSpacing: ".16em", textTransform: "uppercase", color: "var(--color-neutral-500)", marginTop: 3 }}>
              Created by Shagnik
            </div>
          </div>
        </div>

        <div
          className="btn btn-secondary"
          title={online ? "Backend reachable" : "Start the backend with uvicorn"}
          style={{ cursor: "default", flex: "none" }}
        >
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: hostTone, display: "inline-block" }} />
          {hostLabel}
        </div>

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <div
            style={{ display: "flex", background: "var(--color-neutral-900)", borderRadius: "var(--radius)", padding: 2 }}
            title="How much room each tab takes in the bar"
          >
            {(["rail", "strip"] as ShellLayout[]).map((l) => (
              <button
                key={l}
                onClick={() => setLayout(l)}
                className="btn"
                aria-pressed={layout === l}
                style={{
                  padding: "5px 12px",
                  fontSize: 12,
                  background: layout === l ? "var(--color-neutral-800)" : "transparent",
                  color: layout === l ? "var(--color-text)" : "var(--color-neutral-500)",
                }}
              >
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
        {active === "strands" && <StrandsPanel state={avatar} onActivity={onActivity} />}
        {active === "chat" && (
          <ChatPanel
            onActivity={onActivity}
            messages={chatMessages}
            onMessages={(update) => setChatMessages(update)}
            draft={chatDraft}
            onDraft={setChatDraft}
            busy={chatBusy}
            onBusy={setChatBusy}
            provider={provider}
            onProvider={setProvider}
            restored={chatRestored}
          />
        )}
        {active === "dashboard" && <DashboardPanel />}
        {active === "work" && <WorkPanel />}
        {active === "models" && <ModelsPanel />}
        {active === "agents" && <AgentsPanel />}
        {active === "connectors" && <ConnectorsPanel />}
        {active === "store" && <StorePanel />}
        {active === "power" && <PowerPanel />}
        {active === "admin" && <AdminPanel />}
        {active === "settings" && <SettingsPanel />}
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
