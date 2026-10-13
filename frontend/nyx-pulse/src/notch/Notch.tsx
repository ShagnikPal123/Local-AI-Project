/** The Equalize notch: Coucou's island with Io, Ichos's agents, files, timers and sound.
 *
 * Modes (Coucou SPEC §2–§3): hidden → peek (pointer at the top centre, Io waves) → expanded after 650 ms; compact
 * while agents work; expanded views 640 wide. Ichos adds the **trio** — when things build up the bar splits into
 * three small notches: a pinned app's work on the left, the clock and timers in the middle, the sound playing on the
 * right (owner, 2026-10-11). Header: Home · Chat · New on the left; on the right Settings, Sound (click mutes, hover
 * shows the slider), Back to chat and Close, with the camera gap kept in the middle.
 *
 * Two hosts: the desktop window (notch_window.py: transparent, always on top, click-through outside the island) and
 * the Equalize tab, which shows the same notch over a little desktop as a live preview.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { uploadFile } from "../api";
import { useTurns } from "../hooks/useTurns";
import { outputLevels, onSpeakingChange } from "../voice/voicePlayer";
import { IoView, MiniIo } from "./IoView";
import type { IoEmote, IoState } from "./io";
import {
  notchApi, type AssistantSettings, type CatalogAgent, type FileRead, type NotchAgent, type Work, type WorkStep,
} from "./notchApi";
import { play, setSfxVolume } from "./sfx";
import {
  AgentsView, AppView, ChatView, ChooseView, DropView, EmptyView, HomeView, Icon, MailView, NoteView, SettingsView,
  SoundView, TimerView, UploadingView, WorkView, agentIoState, formatLeft, type ChatEntry,
} from "./views";
import "./notch.css";

type Mode = "hidden" | "peek" | "compact" | "trio" | "expanded";
type View = "home" | "empty" | "chat" | "drop" | "uploading" | "choose" | "mail" | "note" | "work" | "agents"
  | "settings" | "timer" | "sound" | "app";
type Tab = "home" | "chat" | "new";

const NOTCH_W = 184, NOTCH_H = 32, COMPACT_W = 288, PEEK_W = NOTCH_W + 64, EXPANDED_W = 640;
const HEIGHTS: Record<View, number> = {
  home: 160, empty: 150, chat: 176, drop: 176, uploading: 150, choose: 176, mail: 248, note: 136, work: 256,
  agents: 240, settings: 280, timer: 184, sound: 176, app: 210,
};
const TAB_OF: Partial<Record<View, Tab>> = { home: "home", empty: "home", work: "home", agents: "home", app: "home",
  timer: "home", sound: "home", chat: "chat", drop: "new", uploading: "new", choose: "new", mail: "new", note: "new" };

interface HostApi {
  set_hit?: (x: number, y: number, w: number, h: number) => void;
  open_app?: (tab: string) => void;
  hide?: () => void;
}
const host = (): HostApi | null => (window as unknown as { pywebview?: { api?: HostApi } }).pywebview?.api ?? null;

export function Notch({ embedded = false }: { embedded?: boolean }) {
  const [settings, setSettings] = useState<AssistantSettings | null>(null);
  const [agents, setAgents] = useState<NotchAgent[]>([]);
  const [catalog, setCatalog] = useState<CatalogAgent[]>([]);
  const [open, setOpen] = useState(embedded);
  const [peeking, setPeeking] = useState(false);
  const [view, setView] = useState<View>("home");
  const [focusId, setFocusId] = useState("ichos");
  const [work, setWork] = useState<Work | null>(null);
  const [appId, setAppId] = useState("");
  const [now, setNow] = useState(Date.now());
  const [idleLeft, setIdleLeft] = useState(0);
  const [volHover, setVolHover] = useState(false);
  const [emote, setEmote] = useState<{ name: IoEmote; at: number } | null>(null);
  const [voiceState, setVoiceState] = useState<IoState>("idle");
  const [soundBars, setSoundBars] = useState<number[]>(Array(14).fill(0));
  const [soundAt, setSoundAt] = useState(0);
  // chat
  const [chatId, setChatId] = useState("");
  const [log, setLog] = useState<ChatEntry[]>([]);
  const { send, runningTurn, sending } = useTurns(chatId);
  // files
  const [files, setFiles] = useState<{ id: string; name: string }[]>([]);
  const [progress, setProgress] = useState(0);
  const [fileRead, setFileRead] = useState<FileRead | null>(null);
  const [dragHot, setDragHot] = useState(false);
  const [draft, setDraft] = useState({ to: "", subject: "", body: "" });
  const [mailState, setMailState] = useState({ sending: false, error: "" });
  const [note, setNote] = useState<{ text: string; tone: "good" | "bad" | "plain" }>({ text: "", tone: "plain" });

  const lastActivity = useRef(Date.now());
  const hoverOpened = useRef(false);
  const timers = useRef<number[]>([]);
  const clicks = useRef<number[]>([]);
  const prevStates = useRef<Record<string, string>>({});
  const islandRef = useRef<HTMLDivElement>(null);

  const later = (fn: () => void, ms: number) => timers.current.push(window.setTimeout(fn, ms));
  const clearLater = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  const touch = useCallback(() => { lastActivity.current = Date.now(); hoverOpened.current = false; }, []);

  // ── data ──────────────────────────────────────────────────────────────────
  const refresh = useCallback(async () => {
    const result = await notchApi.state();
    if (!result.ok) return;
    setSettings(result.data.settings);
    setAgents(result.data.agents);
  }, []);
  useEffect(() => {
    void refresh();
    void notchApi.agents().then((r) => { if (r.ok) setCatalog(r.data.catalog); });
    const poll = window.setInterval(refresh, open ? 1500 : 4000);
    return () => window.clearInterval(poll);
  }, [refresh, open]);
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);
  useEffect(() => {
    if (settings) setSfxVolume(settings.sound.volume, settings.sound.muted);
  }, [settings]);

  const save = useCallback(async (changes: Partial<AssistantSettings>) => {
    setSettings((s) => (s ? { ...s, ...changes } as AssistantSettings : s));
    const result = await notchApi.save(changes);
    if (result.ok) setSettings(result.data);
  }, []);

  // Agents finishing → a short "finished" note, like Coucou's finished view.
  useEffect(() => {
    for (const a of agents) {
      const before = prevStates.current[a.id];
      if (before === "working" && a.state === "finished") {
        play("finish");
        setEmote({ name: "proud", at: Date.now() });
        if (!open || view === "home" || view === "empty") {
          showNote(`${a.name} finished — ${a.step}`, "good");
        }
      }
      if (before && before !== "error" && a.state === "error") play("error");
      prevStates.current[a.id] = a.state;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents]);

  const focus = agents.find((a) => a.id === focusId) ?? agents[0] ?? {
    id: "ichos", name: "Io", kind: "ichos", color: "#A594FF", state: "idle", step: "",
  } as NotchAgent;
  const working = agents.filter((a) => a.state === "working");
  const pinned = settings?.pinned ?? [];
  const activeTimers = (settings?.timers ?? []).filter((t) => t.ends * 1000 > now - 1500);
  const ioName = settings?.avatar.name || "Io";
  const ioImage = settings?.avatar.image ? `/api/uploads/${settings.avatar.image}` : "";

  // Live work for the focused agent / the pinned app.
  useEffect(() => {
    if (!open || (view !== "work" && view !== "app")) return;
    const id = view === "app" ? agents.find((a) => a.app === appId)?.id ?? "" : focus.id;
    if (!id) { setWork(null); return; }
    let alive = true;
    const load = async () => {
      const result = await notchApi.work(id);
      if (alive && result.ok) setWork(result.data);
    };
    void load();
    const poll = window.setInterval(load, 800);
    return () => { alive = false; window.clearInterval(poll); };
  }, [open, view, focus.id, appId, agents]);

  // ── Ichos's own voice and the sound notch ───────────────────────────────
  useEffect(() => onSpeakingChange((text) => setVoiceState(text ? "speaking" : "idle")), []);
  useEffect(() => {
    // In the desktop window the voice plays in the app's page; it reports to /api/notch, which we read.
    if (embedded) return;
    const poll = window.setInterval(async () => {
      const r = await (await import("../api")).api.get<{ state: string }>("/api/notch", 2000);
      if (r.ok) setVoiceState(r.data.state === "speaking" ? "speaking" : r.data.state === "listening" ? "listening" : "idle");
    }, 700);
    return () => window.clearInterval(poll);
  }, [embedded]);
  const bands = useRef(new Float32Array(16));
  const voiceLevels = useCallback(() => {
    outputLevels(bands.current);
    return Array.from(bands.current);
  }, []);
  useEffect(() => {
    const mode = settings?.sound.mode ?? "ai";
    const id = window.setInterval(async () => {
      let level = 0;
      if (mode === "system") {
        const r = await notchApi.sound();
        level = r.ok ? r.data.peak : 0;
      } else if (voiceState === "speaking") {
        const peak = outputLevels(bands.current);
        level = peak || 0.35 + Math.random() * 0.4;
      }
      if (level > 0.02) setSoundAt(Date.now());
      setSoundBars((old) => [...old.slice(1), Math.min(1, level * (0.7 + Math.random() * 0.6))]);
    }, 120);
    return () => window.clearInterval(id);
  }, [settings?.sound.mode, voiceState]);
  const soundPlaying = now - soundAt < 4000;

  // ── mode ──────────────────────────────────────────────────────────────────
  const trioOn = (settings?.notch.trio ?? true) && (pinned.length > 0 || activeTimers.length > 0 || soundPlaying);
  const rest: Mode = trioOn ? "trio" : (working.length || embedded) ? "compact" : "hidden";
  const mode: Mode = open ? "expanded" : peeking ? "peek" : rest;

  const openView = useCallback((next: View) => {
    clearLater();
    if (!open) play("open");
    setOpen(true);
    setPeeking(false);
    setView(next);
    lastActivity.current = Date.now();
    setEmote({ name: null, at: Date.now() });
  }, [open]);

  const close = useCallback(() => {
    if (embedded) { setView("home"); return; }
    clearLater();
    if (open) play("close");
    setOpen(false);
    setPeeking(false);
    hoverOpened.current = false;
  }, [embedded, open]);

  const homeView = (): View => (agents.length <= 1 && !pinned.length ? "empty" : "home");

  // Hover: peek, then open (Coucou rules 2 and 4). Leaving folds it again unless the owner clicked or typed inside.
  const onEnter = () => {
    clearLater();
    if (open || !(settings?.notch.open_on_hover ?? true)) return;
    if (mode === "hidden") {
      setPeeking(true);
      play("peek");
      setEmote({ name: "happy", at: Date.now() });
      later(() => { hoverOpened.current = true; openView(homeView()); }, 650);
    } else {
      later(() => { hoverOpened.current = true; openView(homeView()); }, 200);
    }
  };
  const onLeave = () => {
    clearLater();
    if (embedded) return;
    if (peeking && !open) later(() => setPeeking(false), 600);
    else if (open && hoverOpened.current) later(close, 1200);
  };

  // Inactivity: fold after N seconds, with Coucou's 2 pt countdown in the last ten.
  useEffect(() => {
    if (!open || embedded) { setIdleLeft(0); return; }
    const limit = (settings?.notch.autoclose_s ?? 60) * 1000;
    const id = window.setInterval(() => {
      const left = limit - (Date.now() - lastActivity.current);
      setIdleLeft(left < 10_000 ? Math.max(0, left) : 0);
      if (left <= 0 && !mailState.sending && !(runningTurn && view === "chat")) close();
    }, 250);
    return () => window.clearInterval(id);
  }, [open, embedded, settings?.notch.autoclose_s, close, mailState.sending, runningTurn, view]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      touch();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close, touch]);

  // Timers ringing.
  useEffect(() => {
    for (const t of settings?.timers ?? []) {
      const left = t.ends * 1000 - now;
      if (left <= 0 && left > -1100) {
        play("timer");
        showNote(`${t.label} — time's up`, "good");
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [now]);

  const showNote = (text: string, tone: "good" | "bad" | "plain" = "plain") => {
    setNote({ text, tone });
    openView("note");
    later(() => setView((v) => (v === "note" ? homeView() : v)), 2400);
  };

  // The global shortcut (notch_window.py registers it) opens the chat.
  useEffect(() => {
    (window as unknown as { __notchHotkey?: () => void }).__notchHotkey = () => { touch(); openView("chat"); };
  }, [openView, touch]);

  // ── island size, and the click-through hit box for the desktop host ──────
  const chatHeight = Math.min(300, HEIGHTS.chat + Math.max(0, log.length - 1) * 30);
  const size = mode === "expanded" ? { w: EXPANDED_W, h: view === "chat" ? chatHeight : HEIGHTS[view] }
    : mode === "peek" ? { w: PEEK_W, h: NOTCH_H }
      : mode === "compact" ? { w: COMPACT_W, h: NOTCH_H }
        : mode === "trio" ? { w: 0, h: 0 } : { w: NOTCH_W, h: 0 };
  // Sent again twice a second: the bridge appears a moment after the page, and a lost report would leave the window
  // the wrong size.
  const hit = useRef({ w: 240, h: 6 });
  useEffect(() => {
    if (mode === "trio") {
      const box = document.querySelector(".nx-trio")?.getBoundingClientRect();
      hit.current = box ? { w: Math.ceil(box.width) + 8, h: Math.ceil(box.bottom) + 6 } : { w: 360, h: 44 };
    } else if (mode === "hidden") hit.current = { w: 240, h: 6 };
    else hit.current = { w: size.w + 28, h: size.h + (volHover ? 50 : 6) };
    host()?.set_hit?.(0, 0, hit.current.w, hit.current.h);
  }, [mode, size.w, size.h, volHover, pinned.length, activeTimers.length, soundPlaying]);
  useEffect(() => {
    if (embedded) return;
    const id = window.setInterval(() => host()?.set_hit?.(0, 0, hit.current.w, hit.current.h), 500);
    return () => window.clearInterval(id);
  }, [embedded]);

  // ── the big Io: clicks are slaps, three quick ones make it dizzy ─────────
  const ioState: IoState = view === "chat" && (sending || runningTurn) ? "thinking"
    : voiceState !== "idle" ? voiceState : working.length ? "working" : "idle";
  const slap = () => {
    const t = Date.now();
    clicks.current = [...clicks.current.filter((c) => t - c < 1700), t];
    if (clicks.current.length >= 3) {
      clicks.current = [];
      play("dizzy");
      setEmote({ name: "surprised", at: t });
      showNote("Too many pokes at once. 💫", "plain");
    } else {
      play("annoyed");
      setEmote({ name: "annoyed", at: t });
    }
  };

  // ── chat ─────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!runningTurn) {
      setLog((old) => old.map((m, i) => (i === old.length - 1 && m.role === "assistant" && !m.done ? { ...m, done: true } : m)));
      return;
    }
    setLog((old) => {
      const copy = [...old];
      const last = copy[copy.length - 1];
      if (last?.role === "assistant" && !last.done) {
        copy[copy.length - 1] = { ...last, text: runningTurn.answer, steps: runningTurn.steps.map((s) => s.label ?? s.name) };
      }
      return copy;
    });
  }, [runningTurn, runningTurn?.answer, runningTurn?.steps.length]);

  const sendChat = async (text: string) => {
    touch();
    if (!text) return;
    // Things the notch does itself: timers, "send it to …" with a file, Ultra Fast desktop commands.
    const intent = await notchApi.intent(text, files.length > 0);
    if (intent.ok && intent.data.action === "timer" && intent.data.seconds) {
      await notchApi.addTimer(intent.data.seconds, intent.data.label ?? "Timer");
      play("approve");
      void refresh();
      showNote(`Timer set — ${formatLeft(intent.data.seconds * 1000)}`, "good");
      return;
    }
    if (intent.ok && intent.data.action === "email") {
      setDraft({ to: intent.data.to ?? "", subject: intent.data.subject || files.map((f) => f.name).join(", "),
        body: fileRead?.summary ? `${fileRead.summary}\n` : "" });
      openView("mail");
      return;
    }
    if (settings?.ultrafast) {
      const fast = await notchApi.ultrafast(text);
      if (fast.ok && fast.data.handled) {
        play("approve");
        setLog((old) => [...old, { role: "user", text }, { role: "assistant", text: `${fast.data.reply} · ${fast.data.ms} ms`, done: true }]);
        return;
      }
    }
    let id = chatId;
    if (!id) {
      const created = await notchApi.newChat("Equalize");
      if (!created.ok) { showNote("Couldn't start a chat — is the engine running?", "bad"); return; }
      id = created.data.chat.id;
      setChatId(id);
    }
    play("send");
    setLog((old) => [...old, { role: "user", text }, { role: "assistant", text: "", done: false }]);
    const personalityText = settings?.personality.source === "avatar" ? settings.avatar.personality
      : settings?.personality.source === "custom" ? settings.personality.text : "";
    await send({ message: text, chatId: id, attachmentIds: files.map((f) => f.id), personalityText,
      mode: settings?.ultrafast ? "ultrafast" : "normal" });
    setFiles([]);
  };

  const newChat = () => {
    setChatId("");
    setLog([]);
    setFiles([]);
    setFileRead(null);
    openView("drop");
  };

  // ── files: drop anywhere on the notch ────────────────────────────────────
  const takeFiles = async (list: File[]) => {
    if (!list.length) return;
    touch();
    play("gulp");
    setEmote({ name: "happy", at: Date.now() });
    openView("uploading");
    setProgress(4);
    const done: { id: string; name: string }[] = [];
    for (let i = 0; i < list.length; i++) {
      const tick = window.setInterval(() => setProgress((p) => Math.min(92, p + 6)), 90);
      const result = await uploadFile(list[i]);
      window.clearInterval(tick);
      if (result.ok) done.push({ id: result.data.id, name: result.data.name });
      setProgress(Math.round(((i + 1) / list.length) * 100));
      play("tick");
    }
    if (!done.length) { showNote("That file didn't upload.", "bad"); return; }
    setFiles(done);
    const read = await notchApi.readFile(done[0].id);
    setFileRead(read.ok ? read.data : null);
    play("approve");
    setView("choose");
  };
  const onDragOver = (e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    if (!dragHot) {
      setDragHot(true);
      if (!open || (view !== "drop")) openView("drop");
    }
  };
  const onDrop = (e: React.DragEvent) => {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    setDragHot(false);
    void takeFiles(Array.from(e.dataTransfer.files));
  };

  const sendMail = async () => {
    setMailState({ sending: true, error: "" });
    const result = await notchApi.mail({ ...draft, upload_ids: files.map((f) => f.id) });
    setMailState({ sending: false, error: result.ok ? "" : result.error });
    if (result.ok) {
      play("send");
      setFiles([]);
      showNote(result.data.sent ? `Email sent to ${result.data.to.join(", ")}.` : result.data.note ?? "Draft opened.", "good");
    }
  };

  // ── tasks ────────────────────────────────────────────────────────────────
  const giveTask = async (text: string, agentId = focus.id, extra: { new_name?: string; app?: string } = {}) => {
    touch();
    const result = await notchApi.task({ agent: agentId, task: text, ...extra });
    if (!result.ok) { showNote(result.error, "bad"); return; }
    play("send");
    setWork(result.data);
    setFocusId(result.data.agent?.id ?? agentId);
    void refresh();
    if (!extra.app) setView("work");
  };

  const goBackToChat = () => {
    play("blip");
    if (embedded) window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "chat" } }));
    else if (host()?.open_app) host()!.open_app!("chat");
    else void notchApi.openApp();
  };
  const openSetup = () => {
    if (embedded) document.getElementById("eq-setup")?.scrollIntoView({ behavior: "smooth" });
    else if (host()?.open_app) host()!.open_app!("equalize");
  };
  const closeNotch = () => {
    play("close");
    if (embedded) { setView(homeView()); return; }
    if (host()?.hide) host()!.hide!();
    else close();
  };

  const tab: Tab = TAB_OF[view] ?? "home";
  const recent: WorkStep | null = null;
  const focusApp = pinned.find((p) => p.id === appId) ?? pinned[0];
  const left = activeTimers[0] ? activeTimers[0].ends * 1000 - now : 0;
  const clock = new Date(now).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const bars = useMemo(() => soundBars.slice(-7), [soundBars]);

  // ── render ───────────────────────────────────────────────────────────────
  const island = (
    <div ref={islandRef}
      className={`nx-island ${mode === "expanded" ? "expanded" : ""} ${mode === "hidden" || mode === "trio" ? "hidden" : ""}`}
      style={{ width: size.w, height: size.h }}
      onMouseEnter={onEnter} onMouseLeave={onLeave} onMouseMove={touch} onMouseDown={touch}
      onDragOver={onDragOver} onDragLeave={() => setDragHot(false)} onDrop={onDrop}>
      <div className="nx-clip">
        {(mode === "compact" || mode === "peek") && (
          <div className="nx-compact" onClick={() => openView(homeView())}>
            <IoView size={mode === "peek" ? 18 : 20} state={ioState} emote={emote} image={ioImage} details={false} levels={voiceLevels} />
            {mode === "compact" && (
              <span className="nx-minigrid">
                {agents.filter((a) => a.id !== "ichos").slice(0, 4).map((a) => (
                  <MiniIo key={a.id} color={a.color} size={13} state={agentIoState(a)} />
                ))}
              </span>
            )}
          </div>
        )}
        {mode === "expanded" && settings && (
          <div className="nx-content">
            <div className="nx-header">
              <div className="nx-tabs" role="tablist">
                <button className={`nx-tab ${tab === "home" ? "on" : ""}`} onClick={() => { play("blip"); openView(homeView()); }} aria-label="Home" title="Home">{Icon.home()}</button>
                <button className={`nx-tab ${tab === "chat" ? "on" : ""}`} onClick={() => { play("blip"); openView("chat"); }} aria-label="Chat" title="Chat">{Icon.chat()}</button>
                <button className={`nx-tab ${tab === "new" ? "on" : ""}`} onClick={() => { play("blip"); newChat(); }} aria-label="New chat or drop files" title="New chat · drop files">{Icon.plus()}</button>
              </div>
              <span className="nx-cam" aria-hidden="true" />
              <div className="nx-actions">
                <button className={`nx-act ${view === "settings" ? "on" : ""}`} onClick={() => { play("blip"); openView(view === "settings" ? homeView() : "settings"); }} aria-label="Assistant settings" title="Assistant settings">{Icon.gear()}</button>
                <span className="nx-vol" onMouseEnter={() => setVolHover(true)} onMouseLeave={() => setVolHover(false)}>
                  <button className={`nx-act ${settings.sound.muted ? "" : "on"}`} aria-label={settings.sound.muted ? "Unmute" : "Mute"} title="Click to mute · hover for volume"
                    onClick={() => void save({ sound: { ...settings.sound, muted: !settings.sound.muted } })}>{Icon.sound(settings.sound.muted)}</button>
                  {volHover && (
                    <span className="nx-vol-pop">
                      <input type="range" min={0} max={100} value={Math.round(settings.sound.volume * 100)} aria-label="Volume"
                        style={{ ["--fill" as string]: `${settings.sound.volume * 100}%` }}
                        onChange={(e) => void save({ sound: { ...settings.sound, volume: Number(e.target.value) / 100, muted: false } })} />
                      <span>{Math.round(settings.sound.volume * 100)}</span>
                    </span>
                  )}
                </span>
                <button className="nx-act" onClick={goBackToChat} aria-label="Back to chat" title="Back to the chat">{Icon.back()}</button>
                <button className="nx-act close" onClick={closeNotch} aria-label="Close" title="Close">{Icon.close()}</button>
              </div>
            </div>
            <div className="nx-views" key={view}>
              {view === "home" && (
                <HomeView agents={agents} focus={focus} pinned={pinned} ioImage={ioImage} ioName={ioName} ioState={ioState}
                  clock={clock} recent={recent}
                  onFocus={(id) => {
                    play("blip");
                    if (id.startsWith("pin:")) { setAppId(id.slice(4)); openView("app"); return; }
                    if (id === focus.id) { openView("work"); return; }
                    setFocusId(id);
                  }}
                  onOpenWork={() => openView("work")} onAdd={() => openView("agents")} onAsk={() => openView("chat")}
                  onDropAgent={(id) => { play("gulp"); void notchApi.drop(id).then(refresh); }} />
              )}
              {view === "empty" && <EmptyView ioState={ioState} ioImage={ioImage} onClick={() => openView("chat")} />}
              {view === "chat" && (
                <ChatView log={log} busy={Boolean(sending || runningTurn)} ultrafast={settings.ultrafast} files={files} ioState={ioState}
                  ioImage={ioImage} ioName={ioName} onSend={(t) => void sendChat(t)} onActivity={touch} levels={voiceLevels}
                  onToggleUltra={() => void save({ ultrafast: !settings.ultrafast })} />
              )}
              {view === "drop" && <DropView hot={dragHot} onFiles={(list) => void takeFiles(list)} />}
              {view === "uploading" && <UploadingView name={files[0]?.name ?? "file"} percent={progress} />}
              {view === "choose" && (
                <ChooseView read={fileRead} names={files.length > 1 ? `${files.length} files` : files[0]?.name ?? "The file"}
                  onAsk={() => openView("chat")}
                  onEmail={() => { setDraft({ to: "", subject: files[0]?.name ?? "", body: fileRead?.summary ?? "" }); openView("mail"); }} />
              )}
              {view === "mail" && (
                <MailView fileName={files.map((f) => f.name).join(", ")} draft={draft} sending={mailState.sending} error={mailState.error}
                  onChange={(d) => { setDraft(d); touch(); }} onSend={() => void sendMail()} onCancel={() => openView(files.length ? "choose" : homeView())} />
              )}
              {view === "note" && <NoteView text={note.text} tone={note.tone} ioImage={ioImage} />}
              {view === "work" && (
                <WorkView agent={focus} work={work} onTask={(t) => void giveTask(t)}
                  onStop={() => { if (work?.id) void notchApi.stop(work.id).then(refresh); }} />
              )}
              {view === "agents" && (
                <AgentsView catalog={catalog}
                  onPick={(id) => { play("gulp"); void notchApi.drop(id).then(refresh); setFocusId(id); openView("work"); }}
                  onNew={(name, task) => void giveTask(task, "ichos", { new_name: name })} />
              )}
              {view === "settings" && <SettingsView settings={settings} onSave={(c) => void save(c)} onOpenSetup={openSetup} />}
              {view === "timer" && (
                <TimerView timers={activeTimers} now={now}
                  onAdd={(s, l) => void notchApi.addTimer(s, l).then(refresh)} onRemove={(id) => void notchApi.removeTimer(id).then(refresh)} />
              )}
              {view === "sound" && (
                <SoundView bars={soundBars} mode={settings.sound.mode} volume={settings.sound.volume} muted={settings.sound.muted}
                  onMode={(m) => void save({ sound: { ...settings.sound, mode: m } })}
                  onVolume={(v) => void save({ sound: { ...settings.sound, volume: v } })} />
              )}
              {view === "app" && focusApp && (
                <AppView app={focusApp} work={work} onOpenWork={() => {
                  const a = agents.find((x) => x.app === focusApp.id);
                  if (a) { setFocusId(a.id); openView("work"); }
                }} onTask={(t) => void giveTask(t, "claude", { app: focusApp.id })} />
              )}
            </div>
          </div>
        )}
      </div>
      {idleLeft > 0 && <span className="nx-countdown" style={{ width: (idleLeft / 10_000) * 160 }} />}
    </div>
  );

  const appWorking = focusApp ? agents.find((a) => a.app === focusApp.id && a.state === "working") : undefined;
  const trio = mode === "trio" && (
    <div className="nx-trio" onMouseEnter={() => clearLater()} onDragOver={onDragOver} onDrop={onDrop}>
      {focusApp ? (
        <button className="nx-pill-top round" title={`${focusApp.name}${appWorking ? " — working" : ""}`}
          onClick={() => { setAppId(focusApp.id); openView("app"); }} aria-label={focusApp.name}>
          <MiniIo color={focusApp.color} size={16} state={appWorking ? "working" : "idle"} />
        </button>
      ) : working[0] ? (
        <button className="nx-pill-top round" onClick={() => { setFocusId(working[0].id); openView("work"); }} aria-label={working[0].name}>
          <MiniIo color={working[0].color} size={16} state="working" />
        </button>
      ) : null}
      <button className="nx-pill-top" onClick={() => openView("timer")} aria-label="Clock and timers">
        <span>{clock}</span>
        {activeTimers.length ? <><span className="sep" /><span>{formatLeft(left)}</span></> : null}
      </button>
      <button className="nx-pill-top" onClick={() => openView(soundPlaying ? "sound" : homeView())} aria-label="Sound playing">
        <IoView size={15} state={voiceState === "speaking" ? "speaking" : "idle"} image={ioImage} details={false} levels={voiceLevels} />
        <span className="nx-wave">{bars.map((b, i) => <i key={i} style={{ height: `${3 + b * 11}px` }} />)}</span>
      </button>
    </div>
  );

  return (
    <div className={`nx ${embedded ? "embedded" : "desktop"}`}>
      {!embedded && mode === "hidden" && <div className="nx-wake" onMouseEnter={onEnter} onDragOver={onDragOver} />}
      {trio}
      {island}
      <IoClickCatcher onSlap={slap} islandRef={islandRef} />
    </div>
  );
}

/** Clicking the big Io in an open view is a slap (Coucou §8); the views own their own clicks otherwise. */
function IoClickCatcher({ onSlap, islandRef }: { onSlap: () => void; islandRef: React.RefObject<HTMLDivElement | null> }) {
  useEffect(() => {
    const el = islandRef.current;
    if (!el) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest(".nx-focus .nx-io, .nx-work-side .nx-io, .nx-split > .nx-io")) onSlap();
    };
    el.addEventListener("click", handler);
    return () => el.removeEventListener("click", handler);
  }, [onSlap, islandRef]);
  return null;
}
