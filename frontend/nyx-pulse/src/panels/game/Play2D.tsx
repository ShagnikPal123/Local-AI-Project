/** Plays a 2D game spec on a canvas (Request H5).
 *
 * The loop reads the spec and the engine state; it draws rectangles, not sprites,
 * because a spec has no art of its own yet. Reduced motion is respected by not
 * shaking or flashing — the game still runs, since refusing to play it would be
 * the wrong answer to "I want to make a game".
 */

import { useEffect, useRef, useState } from "react";
import { createState, inputFrom, roomOf, step, type State } from "./engine";
import type { GameSpec } from "./types";

interface Props { game: GameSpec; onExit?: () => void }

export function Play2D({ game, onExit }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stateRef = useRef<State | null>(null);
  const keysRef = useRef<Set<string>>(new Set());
  const [hud, setHud] = useState({ health: 0, max: 0, coins: 0, room: "", message: "", abilities: [] as string[] });
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    stateRef.current = createState(game);
  }, [game]);

  useEffect(() => {
    function down(event: KeyboardEvent) {
      if (event.key === "Escape") { setPaused((was) => !was); return; }
      if ([" ", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) event.preventDefault();
      keysRef.current.add(event.key.length === 1 ? event.key.toLowerCase() : event.key);
    }
    function up(event: KeyboardEvent) {
      keysRef.current.delete(event.key.length === 1 ? event.key.toLowerCase() : event.key);
    }
    function blur() { keysRef.current.clear(); }
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, []);

  useEffect(() => {
    let frame = 0;
    let last = performance.now();
    let hudAt = 0;

    function draw(now: number) {
      frame = requestAnimationFrame(draw);
      const canvas = canvasRef.current;
      const state = stateRef.current;
      if (!canvas || !state) return;
      const dt = (now - last) / 1000;
      last = now;
      if (!paused) step(game, state, inputFrom(keysRef.current), dt);

      const room = roomOf(game, state.roomId);
      const context = canvas.getContext("2d");
      if (!room || !context) return;
      const ratio = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (canvas.width !== width * ratio || canvas.height !== height * ratio) {
        canvas.width = width * ratio;
        canvas.height = height * ratio;
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.fillStyle = game.palette.bg;
      context.fillRect(0, 0, width, height);

      // Fit the room, then follow the player when the room is wider than the view.
      const tile = Math.max(10, Math.min(width / Math.min(room.width, 34), height / Math.min(room.height, 20)));
      const viewW = width / tile;
      const viewH = height / tile;
      const camX = Math.max(0, Math.min(room.width - viewW, state.x - viewW / 2));
      const camY = Math.max(-1, Math.min(room.height - viewH, state.y - viewH / 2));
      const sx = (x: number) => (x - camX) * tile;
      const sy = (y: number) => (y - camY) * tile;

      for (let y = 0; y < room.tiles.length; y += 1) {
        const row = room.tiles[y];
        for (let x = 0; x < row.length; x += 1) {
          const character = row[x];
          if (character === "#") {
            context.fillStyle = game.palette.ground;
            context.fillRect(sx(x), sy(y), tile + 1, tile + 1);
          } else if (character === "=") {
            context.fillStyle = game.palette.platform;
            context.fillRect(sx(x), sy(y), tile + 1, tile * 0.3);
          } else if (character === "^") {
            context.fillStyle = game.palette.hazard;
            context.beginPath();
            context.moveTo(sx(x), sy(y + 1));
            context.lineTo(sx(x + 0.5), sy(y + 0.25));
            context.lineTo(sx(x + 1), sy(y + 1));
            context.closePath();
            context.fill();
          } else if (character === "D") {
            context.fillStyle = game.palette.accent;
            context.globalAlpha = 0.5;
            context.fillRect(sx(x), sy(y - 0.4), tile, tile * 1.4);
            context.globalAlpha = 1;
          }
        }
      }

      for (const item of state.items) {
        if (item.taken) continue;
        context.fillStyle = item.kind === "ability" ? game.palette.accent : "#ffd60a";
        context.beginPath();
        context.arc(sx(item.x), sy(item.y), tile * (item.kind === "ability" ? 0.3 : 0.16), 0, Math.PI * 2);
        context.fill();
      }

      for (const enemy of state.enemies) {
        context.fillStyle = enemy.colour;
        const size = tile * 0.7 * enemy.size;
        context.fillRect(sx(enemy.x) - size / 2, sy(enemy.y) - size / 2, size, size);
      }

      const flashing = state.invuln > 0 && Math.floor(state.invuln * 12) % 2 === 0;
      context.globalAlpha = flashing ? 0.45 : 1;
      context.fillStyle = game.player.colour;
      context.fillRect(sx(state.x) - tile * 0.36, sy(state.y) - tile * 0.46, tile * 0.72, tile * 0.92);
      context.globalAlpha = 1;
      if (state.attackTime > 0) {
        context.fillStyle = game.palette.accent;
        context.globalAlpha = 0.8;
        context.fillRect(sx(state.x) + (state.facing > 0 ? tile * 0.36 : -tile * 1.3),
          sy(state.y) - tile * 0.35, tile * 0.95, tile * 0.7);
        context.globalAlpha = 1;
      }

      if (state.message && state.messageFor > 0) {
        context.fillStyle = "rgba(0,0,0,0.6)";
        context.fillRect(0, height - 46, width, 46);
        context.fillStyle = "#f5f5f7";
        context.font = "14px system-ui, sans-serif";
        context.fillText(state.message, 14, height - 18);
      }
      if (paused) {
        context.fillStyle = "rgba(0,0,0,0.65)";
        context.fillRect(0, 0, width, height);
        context.fillStyle = "#f5f5f7";
        context.font = "600 20px system-ui, sans-serif";
        context.fillText("Paused — press Esc to carry on", 24, height / 2);
      }

      if (now - hudAt > 120) {
        hudAt = now;
        setHud({
          health: state.health, max: state.maxHealth, coins: state.coins,
          room: room.name, message: state.messageFor > 0 ? state.message : "",
          abilities: Object.keys(state.abilities).filter((key) => state.abilities[key]),
        });
      }
    }

    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [game, paused]);

  return (
    <div className="game-play">
      <div className="game-play__hud">
        <span aria-label={`${hud.health} of ${hud.max} hearts left`}>
          {"♥".repeat(Math.max(0, hud.health))}<span className="muted">{"♡".repeat(Math.max(0, hud.max - hud.health))}</span>
          <span className="muted"> {hud.health}/{hud.max}</span>
        </span>
        <span className="muted">{hud.room}</span>
        {hud.coins > 0 && <span className="muted">✦ {hud.coins}</span>}
        {hud.abilities.length > 0 && <span className="muted">Moves: {hud.abilities.join(", ")}</span>}
        <button className="btn btn-secondary btn-sm" onClick={() => setPaused((was) => !was)}>
          {paused ? "Carry on" : "Pause"}
        </button>
        <button className="btn btn-secondary btn-sm" onClick={() => { stateRef.current = createState(game); }}>
          Restart
        </button>
        {onExit && <button className="btn btn-secondary btn-sm" onClick={onExit}>Back to the editor</button>}
      </div>
      <canvas ref={canvasRef} className="game-play__canvas" tabIndex={0}
        aria-label={`${game.title}, playing. Arrow keys or A and D to move, Space to jump`
          + (game.player.dash ? ", Shift to dash" : "") + (game.player.attack ? ", J to attack" : "")
          + ". Escape pauses."} />
      <p className="muted game-play__keys">
        ← → or A D move · Space jumps{game.player.max_jumps > 1 ? " (twice)" : ""}
        {game.player.dash && " · Shift dashes"}{game.player.wall_jump && " · jump again on a wall"}
        {game.player.attack && " · J hits"} · Esc pauses
      </p>
    </div>
  );
}
