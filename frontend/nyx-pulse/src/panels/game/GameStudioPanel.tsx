/** Game Studio — design, play and export 2D and 3D games (Request H5).
 *
 * The owner's words: "make a game studio tab to make games in 3d and 2d. Similar to making hollow knight
 * and more it can import to unity."
 *
 * A game is a validated spec from `game_studio.py`: rooms of tiles, enemies, abilities and numbers. This
 * tab edits the spec, plays it with `engine.ts`, and asks the server to write a Unity folder from it.
 * Nothing the AI writes is ever run — it only fills in the spec.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";
import { Toasts } from "../../components/chat";
import { dismissToast, pushToast, useToasts } from "../../state/toastStore";
import { Play2D } from "./Play2D";
import { Play3D } from "./Play3D";
import { RoomEditor } from "./RoomEditor";
import { TEMPLATE_TEXT, type EnemyKind, type GameSpec, type GameSummary, type Room } from "./types";
import "./game.css";

type View = "design" | "play" | "unity";

const BEHAVIOURS = ["patrol", "chaser", "flyer", "jumper", "turret"];
const GIVES: { id: string; label: string }[] = [
  { id: "double_jump", label: "Double jump" }, { id: "dash", label: "Dash" }, { id: "wall_jump", label: "Wall jump" },
  { id: "attack", label: "Attack" }, { id: "speed", label: "Speed" }, { id: "none", label: "Story only" },
];

function blankRoom(index: number): Room {
  const width = 32;
  const rows = [
    ...Array.from({ length: 10 }, (_, y) => "#" + (y === 7 ? "..P" + ".".repeat(width - 5) : ".".repeat(width - 2)) + "#"),
    "#".repeat(width),
  ];
  return { id: `room${index + 1}-${Date.now().toString(36).slice(-4)}`, name: `Room ${index + 1}`, tiles: rows,
    width, height: rows.length, spawns: [], items: [], doors: [], note: "" };
}

function Slider({ label, value, min, max, step = 1, suffix = "", onChange }: {
  label: string; value: number; min: number; max: number; step?: number; suffix?: string; onChange: (value: number) => void;
}) {
  return (
    <label className="games__stat">
      <span>{label} <output>{value}{suffix}</output></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

export function GameStudioPanel() {
  const [summaries, setSummaries] = useState<GameSummary[]>([]);
  const [game, setGame] = useState<GameSpec | null>(null);
  const [view, setView] = useState<View>("design");
  const [roomId, setRoomId] = useState("");
  const [busy, setBusy] = useState("");
  const [saveState, setSaveState] = useState<"saved" | "saving" | "unsaved" | "error">("saved");
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<"2d" | "3d">("2d");
  const [template, setTemplate] = useState("metroidvania");
  const [brief, setBrief] = useState("");
  const [roomBrief, setRoomBrief] = useState("");
  const [redesign, setRedesign] = useState("");
  const [folder, setFolder] = useState("");
  const [unityFiles, setUnityFiles] = useState<{ path: string; bytes: number }[]>([]);
  const [playAs, setPlayAs] = useState<"2d" | "3d">("2d");
  const toasts = useToasts();
  const saveTimer = useRef<number | undefined>(undefined);
  const editCount = useRef(0);

  const loadList = useCallback(async () => {
    const result = await api.get<{ games: GameSummary[] }>("/api/games");
    if (result.ok) setSummaries(result.data.games);
  }, []);

  const open = useCallback(async (gameId: string) => {
    const result = await api.get<{ game: GameSpec }>(`/api/games/${gameId}`);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setGame(result.data.game);
    setRoomId(result.data.game.rooms[0]?.id || "");
    setPlayAs(result.data.game.kind);
    setSaveState("saved");
  }, []);

  useEffect(() => { void loadList(); }, [loadList]);

  useEffect(() => {
    if (view !== "unity" || !game) return;
    void api.get<{ files: { path: string; bytes: number }[] }>(`/api/games/${game.id}/unity`)
      .then((result) => { if (result.ok) setUnityFiles(result.data.files); });
  }, [view, game]);

  /** Every edit shows at once and saves after a short pause; the server's validated copy wins when no newer edit is waiting. */
  function edit(next: GameSpec) {
    setGame(next);
    setSaveState("unsaved");
    editCount.current += 1;
    const mine = editCount.current;
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(async () => {
      setSaveState("saving");
      const result = await api.patch<{ game: GameSpec }>(`/api/games/${next.id}`, { changes: next });
      if (!result.ok) { setSaveState("error"); pushToast(result.error, "warn"); return; }
      if (editCount.current === mine) {
        setGame(result.data.game);
        setSaveState("saved");
        void loadList();
      }
    }, 700);
  }

  useEffect(() => () => window.clearTimeout(saveTimer.current), []);

  async function createGame() {
    if (!title.trim()) return;
    setBusy(brief.trim() ? "Nyx is designing your game — this can take a minute…" : "Setting up…");
    const result = await api.post<{ game: GameSpec }>("/api/games",
      { title: title.trim(), kind, template, brief: brief.trim() }, 200_000);
    setBusy("");
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setGame(result.data.game);
    setRoomId(result.data.game.rooms[0]?.id || "");
    setPlayAs(result.data.game.kind);
    setView("design");
    setTitle(""); setBrief("");
    void loadList();
    pushToast(`${result.data.game.title} is ready — press Play to try it.`, "ok");
  }

  async function aiAction(label: string, path: string, body: unknown) {
    if (!game) return;
    window.clearTimeout(saveTimer.current);
    setBusy(label);
    const result = await api.post<{ game: GameSpec }>(path, body, 200_000);
    setBusy("");
    if (!result.ok) { pushToast(result.error, "warn"); return false; }
    setGame(result.data.game);
    setSaveState("saved");
    void loadList();
    return result.data.game;
  }

  async function deleteGame() {
    if (!game) return;
    if (!window.confirm(`Delete ${game.title}? This cannot be undone.`)) return;
    const result = await api.del(`/api/games/${game.id}`);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setGame(null);
    void loadList();
  }

  async function exportUnity() {
    if (!game || !folder.trim()) return;
    setBusy("Writing the Unity files…");
    const result = await api.post<{ folder: string; files: string[] }>(`/api/games/${game.id}/unity`, { folder: folder.trim() }, 60_000);
    setBusy("");
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast(`${result.data.files.length} Unity files written into ${result.data.folder}.`, "ok", {
      label: "Open in Code",
      onClick: () => window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "code" } })),
    });
  }

  const room = useMemo(() => game?.rooms.find((entry) => entry.id === roomId) || game?.rooms[0], [game, roomId]);

  function setRoom(next: Room) {
    if (!game) return;
    edit({ ...game, rooms: game.rooms.map((entry) => (entry.id === next.id ? { ...next, width: next.tiles[0]?.length || next.width, height: next.tiles.length } : entry)) });
  }

  function setEnemy(index: number, changes: Partial<EnemyKind>) {
    if (!game) return;
    edit({ ...game, enemies: game.enemies.map((enemy, i) => (i === index ? { ...enemy, ...changes } : enemy)) });
  }

  const saveText = { saved: "✓ Saved", saving: "Saving…", unsaved: "Unsaved changes", error: "⚠ Not saved" }[saveState];

  return (
    <div className="games">
      <aside className="games__side">
        <span className="label">New game</span>
        <label className="games__field">
          Name
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Hollow Depths"
            onKeyDown={(e) => { if (e.key === "Enter") void createGame(); }} />
        </label>
        <div className="segmented" role="group" aria-label="2D or 3D">
          <button aria-pressed={kind === "2d"} onClick={() => setKind("2d")}>2D</button>
          <button aria-pressed={kind === "3d"} onClick={() => setKind("3d")}>3D</button>
        </div>
        <label className="games__field">
          Kind of game
          <select value={template} onChange={(e) => setTemplate(e.target.value)}>
            {Object.keys(TEMPLATE_TEXT).map((id) => <option key={id} value={id}>{id[0].toUpperCase() + id.slice(1)}</option>)}
          </select>
        </label>
        <p className="games__hint">{TEMPLATE_TEXT[template]}</p>
        <label className="games__field">
          <span>Describe it <span className="muted">(optional — Nyx designs it)</span></span>
          <textarea rows={4} value={brief} onChange={(e) => setBrief(e.target.value)}
            placeholder="A silent knight in a flooded underground kingdom. Starts weak, finds a dash, then wall jumps to reach the old city." />
        </label>
        <button className="btn btn-primary" disabled={!title.trim() || !!busy} onClick={() => void createGame()}>
          {brief.trim() ? "Design it with Nyx" : "Start with a sample level"}
        </button>

        <span className="label" style={{ marginTop: 8 }}>Your games</span>
        {summaries.length === 0 && <p className="games__hint">None yet.</p>}
        <ul className="games__list">
          {summaries.map((item) => (
            <li key={item.id}>
              <button className={game?.id === item.id ? "is-active" : ""} onClick={() => void open(item.id)}>
                <b>{item.title}</b>
                <small>{item.kind.toUpperCase()} · {item.template} · {item.counts.rooms} room{item.counts.rooms === 1 ? "" : "s"}</small>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <main className="games__main">
        {busy && <p className="games__busy" role="status">◌ {busy}</p>}
        {!game && (
          <div className="games__empty">
            <h2>Make a game</h2>
            <p>
              Name it, pick 2D or 3D, and either start from a small playable level or describe the game and let
              Nyx design the rooms, enemies and abilities. Paint rooms tile by tile, play it right here, and send it
              to Unity when you want to take it further.
            </p>
          </div>
        )}

        {game && (
          <>
            <header className="games__head">
              <div>
                <span className="games__save" aria-live="polite">{saveText}</span>
                <h1>{game.title}</h1>
                <span className="muted" style={{ fontSize: 12.5 }}>{game.kind.toUpperCase()} · {game.template}</span>
              </div>
              <div className="games__actions">
                <div className="segmented" role="group" aria-label="Studio view">
                  <button aria-pressed={view === "design"} onClick={() => setView("design")}>Design</button>
                  <button aria-pressed={view === "play"} onClick={() => setView("play")}>▶ Play</button>
                  <button aria-pressed={view === "unity"} onClick={() => setView("unity")}>Unity</button>
                </div>
                <button className="btn btn-danger" onClick={() => void deleteGame()}>Delete</button>
              </div>
            </header>

            {view === "play" && (
              <>
                <div className="segmented" role="group" aria-label="Play in 2D or 3D" style={{ justifySelf: "start" }}>
                  <button aria-pressed={playAs === "2d"} onClick={() => setPlayAs("2d")}>2D view</button>
                  <button aria-pressed={playAs === "3d"} onClick={() => setPlayAs("3d")}>3D view</button>
                </div>
                {game.rooms.length === 0
                  ? <p className="muted">Add a room first.</p>
                  : playAs === "3d"
                    ? <Play3D key={`3d-${game.updated_at}`} game={game} onExit={() => setView("design")} />
                    : <Play2D key={`2d-${game.updated_at}`} game={game} onExit={() => setView("design")} />}
              </>
            )}

            {view === "unity" && (
              <section className="games__section">
                <h2>Take it to Unity</h2>
                <p className="games__hint" style={{ fontSize: 13 }}>
                  Nyx writes a folder you drop into a Unity project's Assets: the game as a JSON level, four C# scripts
                  that read it, and a README with the exact steps. Nyx does not open or run Unity. The folder has to be
                  one you opened in the Code tab.
                </p>
                <ul className="games__files">
                  {unityFiles.map((file) => <li key={file.path}>{file.path} <span className="muted">· {(file.bytes / 1024).toFixed(1)} KB</span></li>)}
                </ul>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <input className="games__input" style={{ flex: 1, minWidth: 220 }} value={folder}
                    onChange={(e) => setFolder(e.target.value)} placeholder="C:\Users\you\UnityProjects\MyGame" aria-label="Folder" />
                  <button className="btn btn-primary" disabled={!folder.trim() || !!busy} onClick={() => void exportUnity()}>Write Unity files</button>
                </div>
              </section>
            )}

            {view === "design" && (
              <>
                <section className="games__section">
                  <h2>Rooms</h2>
                  <div className="games__rooms" role="group" aria-label="Rooms">
                    {game.rooms.map((entry) => (
                      <button key={entry.id} className="chip-button" aria-pressed={room?.id === entry.id} onClick={() => setRoomId(entry.id)}>
                        {entry.name}
                      </button>
                    ))}
                    <button className="btn btn-secondary btn-sm" onClick={() => {
                      const made = blankRoom(game.rooms.length);
                      edit({ ...game, rooms: [...game.rooms, made] });
                      setRoomId(made.id);
                    }}>+ Empty room</button>
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <input className="games__input" style={{ flex: 1, minWidth: 200 }} value={roomBrief} onChange={(e) => setRoomBrief(e.target.value)}
                      placeholder="Ask Nyx for a room — e.g. a tall shaft with spikes and a wall-jump climb" aria-label="Room idea" />
                    <button className="btn btn-secondary" disabled={!!busy} onClick={async () => {
                      const grown = await aiAction("Nyx is building a room…", `/api/games/${game.id}/rooms`, { brief: roomBrief });
                      if (grown) { setRoomId(grown.rooms[grown.rooms.length - 1].id); setRoomBrief(""); }
                    }}>Add a room with Nyx</button>
                  </div>
                  {room && (
                    <>
                      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                        <label className="games__field" style={{ flex: 1, minWidth: 180 }}>
                          Room name
                          <input value={room.name} onChange={(e) => setRoom({ ...room, name: e.target.value })} />
                        </label>
                        <button className="btn btn-secondary btn-sm" disabled={game.rooms.length <= 1} style={{ alignSelf: "end" }}
                          onClick={() => {
                            const rest = game.rooms.filter((entry) => entry.id !== room.id)
                              .map((entry) => ({ ...entry, doors: entry.doors.filter((door) => door.to !== room.id) }));
                            edit({ ...game, rooms: rest });
                            setRoomId(rest[0]?.id || "");
                          }}>Remove room</button>
                      </div>
                      <RoomEditor game={game} room={room} onChange={setRoom} />
                    </>
                  )}
                </section>

                <section className="games__section">
                  <h2>Redesign with Nyx</h2>
                  <p className="games__hint">Describe what to change and Nyx rewrites the whole game — rooms, enemies, abilities and numbers.</p>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <input className="games__input" style={{ flex: 1, minWidth: 200 }} value={redesign} onChange={(e) => setRedesign(e.target.value)}
                      placeholder="Darker, harder, three bosses, and a double jump hidden behind a locked door" aria-label="What to change" />
                    <button className="btn btn-secondary" disabled={!redesign.trim() || !!busy} onClick={async () => {
                      const made = await aiAction("Nyx is redesigning the game…", `/api/games/${game.id}/design`, { brief: redesign });
                      if (made) { setRoomId(made.rooms[0]?.id || ""); setRedesign(""); }
                    }}>Redesign</button>
                  </div>
                </section>

                <section className="games__section">
                  <h2>The player</h2>
                  <div className="games__stats">
                    <label className="games__field">Name<input value={game.player.name} onChange={(e) => edit({ ...game, player: { ...game.player, name: e.target.value } })} /></label>
                    <Slider label="Run speed" value={game.player.speed} min={2} max={20} step={0.5} onChange={(v) => edit({ ...game, player: { ...game.player, speed: v } })} />
                    <Slider label="Jump" value={game.player.jump} min={6} max={30} step={0.5} onChange={(v) => edit({ ...game, player: { ...game.player, jump: v } })} />
                    <Slider label="Jumps in a row" value={game.player.max_jumps} min={1} max={3} onChange={(v) => edit({ ...game, player: { ...game.player, max_jumps: v } })} />
                    <Slider label="Hearts" value={game.player.health} min={1} max={12} onChange={(v) => edit({ ...game, player: { ...game.player, health: v } })} />
                    <Slider label="Gravity" value={game.world.gravity} min={10} max={90} onChange={(v) => edit({ ...game, world: { ...game.world, gravity: v } })} />
                    <Slider label="Air control" value={Math.round(game.world.air_control * 100)} min={0} max={100} suffix="%" onChange={(v) => edit({ ...game, world: { ...game.world, air_control: v / 100 } })} />
                  </div>
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                    <label className="games__toggle"><input type="checkbox" checked={game.player.dash} onChange={(e) => edit({ ...game, player: { ...game.player, dash: e.target.checked } })} />Dash from the start</label>
                    <label className="games__toggle"><input type="checkbox" checked={game.player.wall_jump} onChange={(e) => edit({ ...game, player: { ...game.player, wall_jump: e.target.checked } })} />Wall jump from the start</label>
                    <label className="games__toggle"><input type="checkbox" checked={game.player.attack} onChange={(e) => edit({ ...game, player: { ...game.player, attack: e.target.checked } })} />Can attack</label>
                    <label className="games__toggle"><input type="color" value={game.player.colour} onChange={(e) => edit({ ...game, player: { ...game.player, colour: e.target.value } })} aria-label="Player colour" />Colour</label>
                  </div>
                </section>

                <section className="games__section">
                  <h2>Enemies</h2>
                  <div className="games__rows">
                    {game.enemies.map((enemy, index) => (
                      <div key={enemy.id} className="games__row">
                        <label className="games__field">Name<input value={enemy.name} onChange={(e) => setEnemy(index, { name: e.target.value })} /></label>
                        <label className="games__field">Moves
                          <select value={enemy.behaviour} onChange={(e) => setEnemy(index, { behaviour: e.target.value })}>
                            {BEHAVIOURS.map((b) => <option key={b} value={b}>{b}</option>)}
                          </select>
                        </label>
                        <label className="games__field">Speed<input type="number" min={0} max={20} step={0.5} value={enemy.speed} onChange={(e) => setEnemy(index, { speed: Number(e.target.value) })} /></label>
                        <label className="games__field">Hits to beat<input type="number" min={1} max={200} value={enemy.health} onChange={(e) => setEnemy(index, { health: Number(e.target.value) })} /></label>
                        <label className="games__field">Damage<input type="number" min={0} max={50} value={enemy.damage} onChange={(e) => setEnemy(index, { damage: Number(e.target.value) })} /></label>
                        <label className="games__field">Colour<input type="color" value={enemy.colour} onChange={(e) => setEnemy(index, { colour: e.target.value })} /></label>
                        <button className="btn btn-secondary btn-sm" onClick={() => edit({ ...game, enemies: game.enemies.filter((_, i) => i !== index) })}>Remove</button>
                      </div>
                    ))}
                  </div>
                  <button className="btn btn-secondary btn-sm" style={{ justifySelf: "start" }} disabled={game.enemies.length >= 12}
                    onClick={() => edit({ ...game, enemies: [...game.enemies, { id: `enemy${Date.now().toString(36).slice(-5)}`, name: "New enemy", behaviour: "patrol", speed: 3, health: 2, damage: 1, colour: "#ff6b6b", size: 1, note: "" }] })}>
                    + Enemy
                  </button>
                </section>

                <section className="games__section">
                  <h2>Abilities</h2>
                  <p className="games__hint">Place an ability in a room with its tool in the room editor. A door can stay locked until the player has one.</p>
                  <div className="games__rows">
                    {game.abilities.map((ability, index) => (
                      <div key={ability.id} className="games__row">
                        <label className="games__field">Name<input value={ability.name} onChange={(e) => edit({ ...game, abilities: game.abilities.map((a, i) => (i === index ? { ...a, name: e.target.value } : a)) })} /></label>
                        <label className="games__field">What it does
                          <select value={ability.gives} onChange={(e) => edit({ ...game, abilities: game.abilities.map((a, i) => (i === index ? { ...a, gives: e.target.value } : a)) })}>
                            {GIVES.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
                          </select>
                        </label>
                        <label className="games__field">Line shown on pickup<input value={ability.note} onChange={(e) => edit({ ...game, abilities: game.abilities.map((a, i) => (i === index ? { ...a, note: e.target.value } : a)) })} /></label>
                        <button className="btn btn-secondary btn-sm" onClick={() => edit({ ...game, abilities: game.abilities.filter((_, i) => i !== index) })}>Remove</button>
                      </div>
                    ))}
                  </div>
                  <button className="btn btn-secondary btn-sm" style={{ justifySelf: "start" }} disabled={game.abilities.length >= 10}
                    onClick={() => edit({ ...game, abilities: [...game.abilities, { id: `ability${Date.now().toString(36).slice(-5)}`, name: "New ability", gives: "double_jump", note: "" }] })}>
                    + Ability
                  </button>
                </section>

                <section className="games__section">
                  <h2>Story and colours</h2>
                  <label className="games__field">Opening line (shown when the game starts)
                    <textarea rows={2} value={game.story.opening} onChange={(e) => edit({ ...game, story: { ...game.story, opening: e.target.value } })} />
                  </label>
                  <label className="games__field">The goal
                    <input value={game.story.goal} onChange={(e) => edit({ ...game, story: { ...game.story, goal: e.target.value } })} />
                  </label>
                  <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                    {(["bg", "ground", "platform", "hazard", "accent"] as const).map((key) => (
                      <label key={key} className="games__toggle">
                        <input type="color" value={game.palette[key]} onChange={(e) => edit({ ...game, palette: { ...game.palette, [key]: e.target.value } })} />
                        {{ bg: "Background", ground: "Ground", platform: "Platforms", hazard: "Hazards", accent: "Doors & pickups" }[key]}
                      </label>
                    ))}
                  </div>
                </section>
              </>
            )}
          </>
        )}
      </main>
      <Toasts items={toasts} onDismiss={dismissToast} />
    </div>
  );
}
