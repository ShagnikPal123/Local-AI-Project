/** The engine that plays a game spec (Request H5).
 *
 * The spec is data — rooms of tile characters, enemies, abilities, numbers. This
 * file interprets it; nothing here is generated or evaluated, which is what lets
 * a game the AI designed run safely inside the tab (AGENTS.md invariant 2).
 *
 * Units are tiles and seconds. x grows right, y grows *down*, matching the way
 * the tile rows are written, so row index and y are the same number.
 */

import type { GameSpec, Room } from "./types";

export interface Input { left: boolean; right: boolean; jump: boolean; dash: boolean; attack: boolean }

export interface LiveEnemy {
  key: string; id: string; name: string; behaviour: string;
  x: number; y: number; vx: number; vy: number; health: number; damage: number;
  size: number; colour: string; speed: number; cooldown: number;
}

export interface LiveItem { key: string; kind: string; ability: string; x: number; y: number; taken: boolean }

export interface State {
  roomId: string;
  x: number; y: number; vx: number; vy: number;
  facing: 1 | -1;
  health: number; maxHealth: number;
  jumpsLeft: number; coyote: number; buffer: number;
  dashTime: number; dashCooldown: number; invuln: number; attackTime: number;
  onGround: boolean; onWall: 0 | 1 | -1;
  abilities: Record<string, boolean>;
  enemies: LiveEnemy[];
  items: LiveItem[];
  coins: number; deaths: number;
  message: string; messageFor: number;
  spawn: { room: string; x: number; y: number };
}

const WIDTH = 0.72;
const HEIGHT = 0.92;
const MAX_STEP = 1 / 30;

export function roomOf(game: GameSpec, roomId: string): Room | undefined {
  return game.rooms.find((room) => room.id === roomId);
}

function tileAt(room: Room, x: number, y: number): string {
  if (y < 0 || y >= room.tiles.length) return y >= room.tiles.length ? "#" : ".";
  const row = room.tiles[y];
  if (x < 0 || x >= row.length) return "#";
  return row[x] || ".";
}

function playerStart(room: Room): { x: number; y: number } {
  for (let y = 0; y < room.tiles.length; y += 1) {
    const x = room.tiles[y].indexOf("P");
    if (x >= 0) return { x: x + 0.5, y: y + 0.5 };
  }
  return { x: 2.5, y: 2.5 };
}

/** Everything that lives in a room: enemies from spawns, pickups from items and "A" tiles. */
function populate(game: GameSpec, room: Room): { enemies: LiveEnemy[]; items: LiveItem[] } {
  const enemies: LiveEnemy[] = room.spawns.map((spawn, index) => {
    const kind = game.enemies.find((enemy) => enemy.id === spawn.enemy);
    return {
      key: `${room.id}:${index}`,
      id: spawn.enemy, name: kind?.name || spawn.enemy, behaviour: kind?.behaviour || "patrol",
      x: spawn.x + 0.5, y: spawn.y + 0.5, vx: 0, vy: 0,
      health: kind?.health ?? 2, damage: kind?.damage ?? 1,
      size: kind?.size ?? 1, colour: kind?.colour || "#ff6b6b", speed: kind?.speed ?? 3, cooldown: 0,
    };
  });
  const items: LiveItem[] = room.items.map((item, index) => ({
    key: `${room.id}:i${index}`, kind: item.kind, ability: item.ability,
    x: item.x + 0.5, y: item.y + 0.5, taken: false,
  }));
  room.tiles.forEach((row, y) => {
    for (let x = 0; x < row.length; x += 1) {
      if (row[x] === "A" && !items.some((item) => Math.abs(item.x - x - 0.5) < 0.6 && Math.abs(item.y - y - 0.5) < 0.6)) {
        items.push({ key: `${room.id}:t${x}-${y}`, kind: "coin", ability: "", x: x + 0.5, y: y + 0.5, taken: false });
      }
    }
  });
  return { enemies, items };
}

export function createState(game: GameSpec, roomId?: string): State {
  const room = roomOf(game, roomId || game.rooms[0]?.id) || game.rooms[0];
  const start = room ? playerStart(room) : { x: 2.5, y: 2.5 };
  const live = room ? populate(game, room) : { enemies: [], items: [] };
  const granted: Record<string, boolean> = {};
  // Abilities the player already has because the spec says so, not because they found one.
  if (game.player.dash) granted.dash = true;
  if (game.player.wall_jump) granted.wall_jump = true;
  if (game.player.max_jumps > 1) granted.double_jump = true;
  if (game.player.attack) granted.attack = true;
  return {
    roomId: room?.id || "",
    x: start.x, y: start.y, vx: 0, vy: 0, facing: 1,
    health: game.player.health, maxHealth: game.player.health,
    jumpsLeft: Math.max(0, game.player.max_jumps - 1), coyote: 0, buffer: 0,
    dashTime: 0, dashCooldown: 0, invuln: 0, attackTime: 0,
    onGround: false, onWall: 0,
    abilities: granted,
    enemies: live.enemies, items: live.items,
    coins: 0, deaths: 0,
    message: game.story.opening || "", messageFor: game.story.opening ? 5 : 0,
    spawn: { room: room?.id || "", x: start.x, y: start.y },
  };
}

function enterRoom(game: GameSpec, state: State, roomId: string, x: number, y: number) {
  const room = roomOf(game, roomId);
  if (!room) return;
  const live = populate(game, room);
  state.roomId = room.id;
  state.x = x + 0.5;
  state.y = y + 0.5;
  state.vx = 0;
  state.vy = 0;
  state.enemies = live.enemies;
  state.items = live.items;
  state.spawn = { room: room.id, x: state.x, y: state.y };
  state.message = room.name;
  state.messageFor = 2.2;
}

function solid(room: Room, x: number, y: number): boolean {
  return tileAt(room, x, y) === "#";
}

/** Move one axis and stop at the first wall; one-way platforms only stop a fall. */
function moveX(room: Room, state: State, dx: number) {
  state.x += dx;
  const top = Math.floor(state.y - HEIGHT / 2 + 0.02);
  const bottom = Math.floor(state.y + HEIGHT / 2 - 0.02);
  state.onWall = 0;
  for (let y = top; y <= bottom; y += 1) {
    if (dx > 0) {
      const edge = Math.floor(state.x + WIDTH / 2);
      if (solid(room, edge, y)) { state.x = edge - WIDTH / 2 - 0.001; state.vx = 0; state.onWall = 1; }
    } else if (dx < 0) {
      const edge = Math.floor(state.x - WIDTH / 2);
      if (solid(room, edge, y)) { state.x = edge + 1 + WIDTH / 2 + 0.001; state.vx = 0; state.onWall = -1; }
    }
  }
}

function moveY(room: Room, state: State, dy: number) {
  const wasBottom = state.y + HEIGHT / 2;
  state.y += dy;
  const left = Math.floor(state.x - WIDTH / 2 + 0.02);
  const right = Math.floor(state.x + WIDTH / 2 - 0.02);
  state.onGround = false;
  for (let x = left; x <= right; x += 1) {
    if (dy > 0) {
      const edge = Math.floor(state.y + HEIGHT / 2);
      const tile = tileAt(room, x, edge);
      const landsOnPlatform = tile === "=" && wasBottom <= edge + 0.05;
      if (tile === "#" || landsOnPlatform) {
        state.y = edge - HEIGHT / 2 - 0.001;
        state.vy = 0;
        state.onGround = true;
      }
    } else if (dy < 0) {
      const edge = Math.floor(state.y - HEIGHT / 2);
      if (solid(room, x, edge)) {
        state.y = edge + 1 + HEIGHT / 2 + 0.001;
        state.vy = 0;
      }
    }
  }
}

/** A door's lock names a move (dash) or an ability id (wings); either one opens it. */
function hasMove(game: GameSpec, state: State, need: string): boolean {
  if (!need) return true;
  if (state.abilities[need]) return true;
  const ability = game.abilities.find((entry) => entry.id === need);
  return !!(ability && ability.gives !== "none" && state.abilities[ability.gives]);
}

/** Jumps available once you leave the ground: the spec's extra jumps, plus one if a pickup gave it. */
function extraJumps(game: GameSpec, state: State): number {
  const base = Math.max(0, game.player.max_jumps - 1);
  return state.abilities.double_jump ? Math.max(1, base) : base;
}

function hurt(state: State, amount: number, fromX: number) {
  if (state.invuln > 0 || amount <= 0) return;
  state.health -= amount;
  state.invuln = 1.1;
  state.vx = state.x < fromX ? -7 : 7;
  state.vy = -8;
  state.message = state.health > 0 ? `Hit — ${state.health} left` : "Down you go";
  state.messageFor = 1.4;
}

function respawn(game: GameSpec, state: State) {
  state.deaths += 1;
  state.health = state.maxHealth;
  state.invuln = 1.4;
  const room = roomOf(game, state.spawn.room);
  const live = room ? populate(game, room) : { enemies: [], items: [] };
  state.roomId = state.spawn.room;
  state.x = state.spawn.x;
  state.y = state.spawn.y;
  state.vx = 0;
  state.vy = 0;
  state.enemies = live.enemies;
  state.items = live.items;
}

/** One frame. `dt` is clamped, so a background tab cannot teleport anyone through a wall. */
export function step(game: GameSpec, state: State, input: Input, rawDt: number): State {
  const dt = Math.min(MAX_STEP, Math.max(0.001, rawDt));
  const room = roomOf(game, state.roomId);
  if (!room) return state;
  const player = game.player;
  const world = game.world;

  state.coyote = Math.max(0, state.coyote - dt);
  state.invuln = Math.max(0, state.invuln - dt);
  state.dashCooldown = Math.max(0, state.dashCooldown - dt);
  state.attackTime = Math.max(0, state.attackTime - dt);
  state.messageFor = Math.max(0, state.messageFor - dt);

  const wanted = (input.right ? 1 : 0) - (input.left ? 1 : 0);
  if (wanted !== 0) state.facing = wanted > 0 ? 1 : -1;

  if (state.dashTime > 0) {
    state.dashTime -= dt;
    state.vx = state.facing * player.speed * 2.4;
    state.vy = 0;
  } else {
    const control = state.onGround ? 1 : world.air_control;
    const target = wanted * player.speed;
    const ease = state.onGround ? 24 : 24 * control;
    state.vx += (target - state.vx) * Math.min(1, ease * dt);
    if (wanted === 0 && state.onGround) state.vx *= 0.82;
    state.vy = Math.min(world.terminal_velocity, state.vy + world.gravity * dt);
    // Sliding down a wall is slower, and is what makes a wall jump feel possible.
    if (state.abilities.wall_jump && state.onWall !== 0 && !state.onGround && state.vy > 4) state.vy = 4;
  }

  state.buffer = input.jump ? Math.max(state.buffer, 0.12) : Math.max(0, state.buffer - dt);
  const canWallJump = state.abilities.wall_jump && state.onWall !== 0 && !state.onGround;
  if (state.buffer > 0 && (state.onGround || state.coyote > 0 || state.jumpsLeft > 0 || canWallJump)) {
    if (canWallJump && !state.onGround) {
      state.vx = -state.onWall * player.speed * 1.1;
      state.facing = state.onWall > 0 ? -1 : 1;
    } else {
      state.jumpsLeft = Math.max(0, state.jumpsLeft - (state.onGround || state.coyote > 0 ? 0 : 1));
    }
    state.vy = -player.jump;
    state.buffer = 0;
    state.coyote = 0;
    state.onGround = false;
  }
  if (input.dash && state.abilities.dash && state.dashCooldown <= 0 && state.dashTime <= 0) {
    state.dashTime = 0.17;
    state.dashCooldown = 0.55;
  }
  if (input.attack && state.abilities.attack && state.attackTime <= 0) state.attackTime = 0.22;

  moveX(room, state, state.vx * dt);
  moveY(room, state, state.vy * dt);
  if (state.onGround) {
    state.coyote = 0.11;
    state.jumpsLeft = extraJumps(game, state);
  }

  // Hazards, doors and the bottom of the world.
  const footTile = tileAt(room, Math.floor(state.x), Math.floor(state.y + HEIGHT / 2 - 0.1));
  const bodyTile = tileAt(room, Math.floor(state.x), Math.floor(state.y));
  if (footTile === "^" || bodyTile === "^") hurt(state, 1, state.x + state.facing);
  if (state.y > room.tiles.length + 4) hurt(state, state.maxHealth, state.x);
  if (state.health <= 0) respawn(game, state);

  for (const door of room.doors) {
    if (!hasMove(game, state, door.needs)) {
      if (Math.abs(state.x - door.x - 0.5) < 0.9 && Math.abs(state.y - door.y - 0.5) < 1.2 && state.messageFor <= 0) {
        const ability = game.abilities.find((entry) => entry.id === door.needs || entry.gives === door.needs);
        state.message = `Locked — you need ${ability?.name || door.needs}`;
        state.messageFor = 1.5;
      }
      continue;
    }
    if (Math.abs(state.x - door.x - 0.5) < 0.9 && Math.abs(state.y - door.y - 0.5) < 1.2) {
      enterRoom(game, state, door.to, door.spawn_x, door.spawn_y);
      return state;
    }
  }

  for (const item of state.items) {
    if (item.taken) continue;
    if (Math.abs(state.x - item.x) > 0.8 || Math.abs(state.y - item.y) > 0.9) continue;
    item.taken = true;
    if (item.kind === "ability" && item.ability) {
      const ability = game.abilities.find((entry) => entry.id === item.ability);
      if (ability && ability.gives !== "none") state.abilities[ability.gives] = true;
      state.message = ability ? `${ability.name} — ${ability.note || "new move"}` : "New move";
      state.messageFor = 3.2;
    } else if (item.kind === "health") {
      state.health = Math.min(state.maxHealth, state.health + 1);
      state.message = "Patched up";
      state.messageFor = 1.6;
    } else {
      state.coins += 1;
    }
  }

  for (const enemy of state.enemies) {
    if (enemy.health <= 0) continue;
    enemy.cooldown = Math.max(0, enemy.cooldown - dt);
    const toPlayer = state.x - enemy.x;
    if (enemy.behaviour === "flyer") {
      const dy = state.y - enemy.y;
      const length = Math.hypot(toPlayer, dy) || 1;
      enemy.x += (toPlayer / length) * enemy.speed * dt;
      enemy.y += (dy / length) * enemy.speed * dt;
    } else if (enemy.behaviour === "chaser") {
      enemy.x += Math.sign(toPlayer) * enemy.speed * dt;
      enemy.y = Math.min(room.tiles.length - 1.5, enemy.y + 12 * dt);
      while (solid(room, Math.floor(enemy.x), Math.floor(enemy.y + 0.5))) enemy.y -= 0.05;
    } else if (enemy.behaviour === "jumper") {
      enemy.vy += world.gravity * dt;
      enemy.y += enemy.vy * dt;
      if (solid(room, Math.floor(enemy.x), Math.floor(enemy.y + 0.5))) {
        enemy.y = Math.floor(enemy.y + 0.5) - 0.5;
        enemy.vy = -enemy.speed * 2.2;
      }
    } else if (enemy.behaviour === "patrol") {
      if (enemy.vx === 0) enemy.vx = enemy.speed;
      const ahead = enemy.x + Math.sign(enemy.vx) * 0.6;
      if (solid(room, Math.floor(ahead), Math.floor(enemy.y)) ||
          !solid(room, Math.floor(ahead), Math.floor(enemy.y + 1))) {
        enemy.vx = -enemy.vx;
      }
      enemy.x += enemy.vx * dt;
    }
    // "turret" stays put.

    const close = Math.abs(state.x - enemy.x) < 0.5 + enemy.size * 0.4 &&
      Math.abs(state.y - enemy.y) < 0.55 + enemy.size * 0.4;
    if (close) hurt(state, enemy.damage, enemy.x);
    if (state.attackTime > 0) {
      const inFront = (enemy.x - state.x) * state.facing;
      if (inFront > -0.4 && inFront < 1.5 && Math.abs(enemy.y - state.y) < 1.1) {
        enemy.health -= 1;
        enemy.cooldown = 0.3;
        if (enemy.health <= 0) { state.coins += 1; state.message = `${enemy.name} down`; state.messageFor = 1.2; }
        state.attackTime = 0;
      }
    }
  }
  state.enemies = state.enemies.filter((enemy) => enemy.health > 0);
  if (state.health <= 0) respawn(game, state);
  return state;
}

/** Keyboard → Input, kept here so the 2D and 3D views read the same keys. */
export function inputFrom(keys: Set<string>): Input {
  return {
    left: keys.has("ArrowLeft") || keys.has("a"),
    right: keys.has("ArrowRight") || keys.has("d"),
    jump: keys.has(" ") || keys.has("ArrowUp") || keys.has("w"),
    dash: keys.has("Shift") || keys.has("k"),
    attack: keys.has("j") || keys.has("x") || keys.has("Enter"),
  };
}
