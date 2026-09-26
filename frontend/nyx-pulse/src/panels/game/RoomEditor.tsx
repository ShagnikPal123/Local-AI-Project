/** Paint a room tile by tile (Request H5).
 *
 * Choose a brush, then click or drag across the grid. Enemies and pickups are
 * placed with their own tools because they are listed on the room, not written
 * into its tiles. Every change goes back through the server's validator, so
 * whatever the editor sends is still only data.
 */

import { useRef, useState } from "react";
import { BRUSHES, type GameSpec, type Room } from "./types";

interface Props {
  game: GameSpec;
  room: Room;
  onChange: (room: Room) => void;
}

type Tool = { kind: "tile"; tile: string } | { kind: "enemy"; id: string } | { kind: "ability"; id: string } | { kind: "erase-thing" };

const TILE_INK = (game: GameSpec, tile: string): string => {
  switch (tile) {
    case "#": return game.palette.ground;
    case "=": return game.palette.platform;
    case "^": return game.palette.hazard;
    case "D": return game.palette.accent;
    case "P": return game.player.colour;
    case "A": return "#ffd60a";
    default: return "transparent";
  }
};

export function RoomEditor({ game, room, onChange }: Props) {
  const [tool, setTool] = useState<Tool>({ kind: "tile", tile: "#" });
  const painting = useRef(false);
  /** The last cell a stroke touched, so a quick drag fills the cells in between instead of leaving gaps. */
  const lastCell = useRef<[number, number] | null>(null);
  const draft = useRef<Room>(room);
  draft.current = room;

  const cell = Math.max(10, Math.min(22, Math.floor(760 / Math.max(room.width, 1))));

  function paintAt(x: number, y: number) {
    const current = draft.current;
    if (tool.kind === "tile") {
      const rows = current.tiles.slice();
      const tile = tool.tile;
      if (rows[y][x] === tile) return;
      // Only one start per room: painting a new one clears the old.
      if (tile === "P") {
        for (let row = 0; row < rows.length; row += 1) rows[row] = rows[row].replace(/P/g, ".");
      }
      const line = rows[y];
      rows[y] = line.slice(0, x) + tile + line.slice(x + 1);
      const next = { ...current, tiles: rows };
      draft.current = next;
      onChange(next);
    } else if (tool.kind === "enemy") {
      onChange({ ...current, spawns: [...current.spawns, { enemy: tool.id, x, y }] });
    } else if (tool.kind === "ability") {
      onChange({ ...current, items: [...current.items, { kind: "ability", ability: tool.id, x, y, needs: "" }] });
    } else {
      onChange({
        ...current,
        spawns: current.spawns.filter((spawn) => spawn.x !== x || spawn.y !== y),
        items: current.items.filter((item) => item.x !== x || item.y !== y),
      });
    }
  }

  /** Paint every cell on the straight line from the last one to this one. */
  function strokeTo(x: number, y: number) {
    const from = lastCell.current;
    lastCell.current = [x, y];
    if (!from) { paintAt(x, y); return; }
    const steps = Math.max(Math.abs(x - from[0]), Math.abs(y - from[1]));
    for (let i = 1; i <= steps; i += 1) {
      paintAt(Math.round(from[0] + ((x - from[0]) * i) / steps), Math.round(from[1] + ((y - from[1]) * i) / steps));
    }
  }

  function resize(dw: number, dh: number) {
    const width = Math.max(8, Math.min(80, room.width + dw));
    const height = Math.max(6, Math.min(48, room.height + dh));
    let rows = room.tiles.map((row) => (row + ".".repeat(80)).slice(0, width));
    if (height > rows.length) {
      const floor = rows[rows.length - 1];
      rows = [...rows.slice(0, -1), ...Array.from({ length: height - rows.length }, () => "#" + ".".repeat(width - 2) + "#"), floor];
    } else {
      rows = [...rows.slice(0, height - 1), rows[rows.length - 1]];
    }
    onChange({ ...room, tiles: rows.map((row) => row.slice(0, width)), width, height });
  }

  const doorsHere = room.doors;

  return (
    <div className="room-editor">
      <div className="room-editor__tools" role="toolbar" aria-label="Room tools">
        {BRUSHES.map((brush) => {
          const active = tool.kind === "tile" && tool.tile === brush.tile;
          return (
            <button key={brush.tile} className={`room-editor__tool${active ? " is-active" : ""}`}
              aria-pressed={active} title={brush.hint} onClick={() => setTool({ kind: "tile", tile: brush.tile })}>
              <span className="room-editor__swatch" style={{ background: TILE_INK(game, brush.tile) }} aria-hidden="true">
                {brush.tile === "." ? "" : brush.tile}
              </span>
              {brush.label}
            </button>
          );
        })}
        {game.enemies.map((enemy) => {
          const active = tool.kind === "enemy" && tool.id === enemy.id;
          return (
            <button key={`e-${enemy.id}`} className={`room-editor__tool${active ? " is-active" : ""}`} aria-pressed={active}
              title={`Place a ${enemy.name} (${enemy.behaviour})`} onClick={() => setTool({ kind: "enemy", id: enemy.id })}>
              <span className="room-editor__swatch" style={{ background: enemy.colour }} aria-hidden="true">E</span>
              {enemy.name}
            </button>
          );
        })}
        {game.abilities.map((ability) => {
          const active = tool.kind === "ability" && tool.id === ability.id;
          return (
            <button key={`a-${ability.id}`} className={`room-editor__tool${active ? " is-active" : ""}`} aria-pressed={active}
              title={`Place the ${ability.name} pickup`} onClick={() => setTool({ kind: "ability", id: ability.id })}>
              <span className="room-editor__swatch" style={{ background: game.palette.accent }} aria-hidden="true">★</span>
              {ability.name}
            </button>
          );
        })}
        <button className={`room-editor__tool${tool.kind === "erase-thing" ? " is-active" : ""}`}
          aria-pressed={tool.kind === "erase-thing"} title="Remove an enemy or pickup"
          onClick={() => setTool({ kind: "erase-thing" })}>
          <span className="room-editor__swatch" aria-hidden="true">✕</span>Remove thing
        </button>
      </div>

      <div className="room-editor__grid-wrap">
        <div className="room-editor__grid" role="grid" aria-label={`${room.name}, ${room.width} by ${room.height} tiles`}
          style={{ gridTemplateColumns: `repeat(${room.width}, ${cell}px)`, background: game.palette.bg }}
          onPointerLeave={() => { painting.current = false; lastCell.current = null; }}
          onPointerUp={() => { painting.current = false; lastCell.current = null; }}>
          {room.tiles.map((row, y) =>
            Array.from(row).map((tile, x) => {
              const spawn = room.spawns.find((item) => item.x === x && item.y === y);
              const item = room.items.find((entry) => entry.x === x && entry.y === y);
              const enemy = spawn ? game.enemies.find((entry) => entry.id === spawn.enemy) : undefined;
              return (
                <div key={`${x}-${y}`} role="gridcell" className="room-editor__cell"
                  style={{ width: cell, height: cell, background: TILE_INK(game, tile) }}
                  aria-label={`${x}, ${y}: ${BRUSHES.find((brush) => brush.tile === tile)?.label || "Air"}${enemy ? `, ${enemy.name}` : ""}${item ? `, ${item.ability || item.kind} pickup` : ""}`}
                  onPointerDown={(event) => { event.preventDefault(); painting.current = tool.kind === "tile"; lastCell.current = [x, y]; paintAt(x, y); }}
                  onPointerEnter={() => { if (painting.current) strokeTo(x, y); }}>
                  {enemy && <span className="room-editor__thing" style={{ background: enemy.colour }} />}
                  {item && <span className="room-editor__thing room-editor__thing--item" />}
                </div>
              );
            }),
          )}
        </div>
      </div>

      <div className="room-editor__foot">
        <span className="muted">{room.width} × {room.height} tiles</span>
        <button className="btn btn-secondary btn-sm" onClick={() => resize(4, 0)}>Wider</button>
        <button className="btn btn-secondary btn-sm" onClick={() => resize(-4, 0)} disabled={room.width <= 8}>Narrower</button>
        <button className="btn btn-secondary btn-sm" onClick={() => resize(0, 2)}>Taller</button>
        <button className="btn btn-secondary btn-sm" onClick={() => resize(0, -2)} disabled={room.height <= 6}>Shorter</button>
      </div>

      {room.tiles.some((row) => row.includes("D")) && (
        <div className="room-editor__doors">
          <span className="label">Doors in this room</span>
          {room.tiles.flatMap((row, y) => Array.from(row).map((tile, x) => ({ tile, x, y })))
            .filter((spot) => spot.tile === "D")
            .map((spot) => {
              const door = doorsHere.find((entry) => entry.x === spot.x && entry.y === spot.y);
              return (
                <label key={`${spot.x}-${spot.y}`} className="room-editor__door">
                  <span>Door at {spot.x}, {spot.y} leads to</span>
                  <select value={door?.to || ""} onChange={(event) => {
                    const to = event.target.value;
                    const target = game.rooms.find((entry) => entry.id === to);
                    let spawnX = 2;
                    let spawnY = 2;
                    if (target) {
                      target.tiles.forEach((row, y) => { const x = row.indexOf("D"); if (x >= 0) { spawnX = Math.max(1, x + (x > target.width / 2 ? -2 : 2)); spawnY = y; } });
                    }
                    const others = room.doors.filter((entry) => entry.x !== spot.x || entry.y !== spot.y);
                    onChange({ ...room, doors: to ? [...others, { to, x: spot.x, y: spot.y, spawn_x: spawnX, spawn_y: spawnY, needs: door?.needs || "" }] : others });
                  }}>
                    <option value="">Nowhere yet</option>
                    {game.rooms.filter((entry) => entry.id !== room.id).map((entry) => (
                      <option key={entry.id} value={entry.id}>{entry.name}</option>
                    ))}
                  </select>
                  {game.abilities.length > 0 && door && (
                    <select value={door.needs} aria-label="Locked until the player has"
                      onChange={(event) => onChange({ ...room, doors: room.doors.map((entry) =>
                        entry === door ? { ...entry, needs: event.target.value } : entry) })}>
                      <option value="">Always open</option>
                      {game.abilities.map((ability) => (
                        <option key={ability.id} value={ability.gives}>Needs {ability.name}</option>
                      ))}
                    </select>
                  )}
                </label>
              );
            })}
        </div>
      )}
    </div>
  );
}
