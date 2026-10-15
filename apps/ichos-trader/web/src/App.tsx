// The shell: the glass frame with the icon rail, the top bar, the sign-in screen and the five views.
import { useCallback, useEffect, useState } from "react";
import { api, type Dashboard, type Me } from "./api";
import { Icon, Tag } from "./ui";
import Overview from "./views/Overview";
import Markets from "./views/Markets";
import Team from "./views/Team";
import Tuning from "./views/Tuning";
import Connectors from "./views/Connectors";
import Setup from "./views/Setup";

const VIEWS = [
  { id: "home", title: "Overview", icon: "home" },
  { id: "markets", title: "Markets", icon: "markets" },
  { id: "team", title: "Team", icon: "team" },
  { id: "tune", title: "Tuning", icon: "tune" },
  { id: "plug", title: "Connectors", icon: "plug" },
  { id: "setup", title: "Setup", icon: "wand" },
] as const;
type View = (typeof VIEWS)[number]["id"];

const STATE_TONE: Record<string, string> = { trading: "good", learning: "info", paused: "warn", shutdown: "bad", off: "" };

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>(() => {
    const asked = location.hash.slice(1);  // a link like /#tune opens that view
    if (VIEWS.some((v) => v.id === asked)) return asked as View;
    try { return (localStorage.getItem("ichos.view") as View) || "home"; } catch { return "home"; }
  });
  const [busy, setBusy] = useState(false);
  const [wantMode, setWantMode] = useState<"practice" | "real" | undefined>();

  const refresh = useCallback(async () => {
    try {
      setDash(await api.dashboard());
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => { api.me().then(setMe).catch((e) => setError(e.message)); }, []);
  // First open: the owner lands on Setup until it has been saved once.
  useEffect(() => {
    if (me?.user?.role === "owner") api.setup().then((s) => { if (!s.done) setView("setup"); }).catch(() => {});
  }, [me]);
  useEffect(() => {
    if (!me?.signed_in) return;
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [me, refresh]);
  useEffect(() => {
    history.replaceState(null, "", `#${view}`);
    try { localStorage.setItem("ichos.view", view); } catch { /* private window */ }
  }, [view]);

  // The trader's colours: accent and light/dark come from Tuning, so the page follows them.
  useEffect(() => {
    const theme = dash?.theme;
    if (!theme) return;
    document.documentElement.style.setProperty("--accent", theme.accent);
    const dark = theme.mode === "system" ? matchMedia("(prefers-color-scheme: dark)").matches : theme.mode !== "light";
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dash?.theme]);

  if (!me) return <div className="splash">{error || "Opening the trader…"}</div>;
  if (!me.signed_in) return <SignIn me={me} onDone={() => api.me().then(setMe)} />;

  const owner = me.user?.role === "owner";
  const running = dash ? !["off", "shutdown"].includes(dash.state) : false;
  // The Practice / Real switch, like the old Trading tab's: going real opens Setup (keys, budget,
  // confirmation); going back to practice is one click, and stops the bots first.
  const switchMode = async (to: "practice" | "real") => {
    if (!dash || to === dash.money_kind) return;
    if (to === "real") { setWantMode("real"); setView("setup"); return; }
    if (!confirm("Switch back to practice money? The trader stops first; your real positions stay in Alpaca.")) return;
    setBusy(true);
    try { await api.realMoneyOff(); await refresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const press = async (what: "start" | "stop" | "cycle") => {
    setBusy(true);
    try { await api.control(what); await refresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="frame">
      <nav className="rail glass">
        <div className="logo" title="Ichos Trader">ι</div>
        {VIEWS.map((v) => (
          <button key={v.id} className={view === v.id ? "on" : ""} onClick={() => setView(v.id)} title={v.title} aria-label={v.title}>
            <Icon name={v.icon} />
          </button>
        ))}
        <div className="grow" />
        {me.auth_mode !== "local" && (
          <button title="Sign out" aria-label="Sign out" onClick={() => api.logout().then(() => api.me().then(setMe))}><Icon name="out" /></button>
        )}
      </nav>
      <main>
        <header className="top">
          <div>
            <h1>{VIEWS.find((v) => v.id === view)?.title}</h1>
            <p className="muted">
              {dash ? dash.state_words : "Loading…"}
            </p>
          </div>
          <div className="top-right">
            {dash && <Tag tone={STATE_TONE[dash.state]}>{dash.state}</Tag>}
            {dash && (owner ? (
              <div className={`mode-switch ${dash.money_kind}`} role="radiogroup" aria-label="Money">
                <button role="radio" aria-checked={dash.money_kind === "practice"} disabled={busy} onClick={() => switchMode("practice")}>Practice</button>
                <button role="radio" aria-checked={dash.money_kind === "real"} disabled={busy} onClick={() => switchMode("real")}>Real money</button>
              </div>
            ) : <Tag tone={dash.money_kind === "practice" ? "info" : "bad"}>{dash.money_kind === "practice" ? "Practice money" : "REAL MONEY"}</Tag>)}
            {dash?.market_source === "simulated" && <Tag tone="warn">Simulated market</Tag>}
            <span className="date">{new Date().toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}</span>
            {owner && (
              <>
                <button className="ghost" disabled={busy} onClick={() => press("cycle")} title="Run one cycle now"><Icon name="bolt" size={16} /> Cycle</button>
                <button className={running ? "danger" : "primary"} disabled={busy || !dash} onClick={() => press(running ? "stop" : "start")}>
                  <Icon name={running ? "stop" : "play"} size={16} /> {running ? "Stop" : "Start"}
                </button>
              </>
            )}
            <span className="who" title={me.user?.email || me.user?.name}>{(me.user?.name || "?").slice(0, 1)}<small>{owner ? "owner" : "viewer"}</small></span>
          </div>
        </header>
        {error && <div className="banner bad">{error}</div>}
        {!owner && <div className="banner info">You are a viewer: you can see how the trader is set up, but not change it or use its keys.</div>}
        {dash?.broker_error && <div className="banner bad">{dash.broker}: {dash.broker_error}</div>}
        {dash?.state === "shutdown" && <div className="banner bad">{dash.stopped_reason} Press Start when you are ready.</div>}
        {!dash ? <div className="splash small">Loading the dashboard…</div> : (
          <>
            {view === "home" && <Overview d={dash} />}
            {view === "markets" && <Markets d={dash} />}
            {view === "team" && <Team d={dash} />}
            {view === "tune" && <Tuning d={dash} owner={owner} onChange={refresh} />}
            {view === "plug" && <Connectors owner={owner} />}
            {view === "setup" && <Setup key={wantMode ?? "saved"} want={wantMode} owner={owner} onDone={() => { setWantMode(undefined); refresh(); setView("home"); }} />}
          </>
        )}
      </main>
    </div>
  );
}

function SignIn({ me, onDone }: { me: Me; onDone: () => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  return (
    <div className="signin">
      <div className="glass card">
        <div className="logo big">ι</div>
        <h1>Ichos Trader</h1>
        <p className="muted">Sign in to see the trader. Only its owner can change anything.</p>
        {me.providers.map((p) => (
          <a key={p} className="primary wide" href={`/api/auth/login/${p}`}>Sign in with {p === "github" ? "GitHub" : "Google"}</a>
        ))}
        {(me.auth_mode === "passcode" || me.providers.length === 0) && (
          <form onSubmit={(e) => { e.preventDefault(); api.passcode(code).then(onDone).catch((x) => setError(x.message)); }}>
            <input type="password" placeholder="Passcode" value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
            <button className="primary wide" type="submit">Unlock</button>
          </form>
        )}
        {me.auth_mode === "local" && <p className="muted">This trader only answers to the computer it runs on. Open it at http://127.0.0.1:8100.</p>}
        {error && <p className="bad-text">{error}</p>}
      </div>
    </div>
  );
}
