/** The shape of a game spec, mirroring `game_studio.validate_game` (Request H5). */

export interface Ability { id: string; name: string; gives: string; note: string }

export interface EnemyKind {
  id: string; name: string; behaviour: string; speed: number; health: number;
  damage: number; colour: string; size: number; note: string;
}

export interface Room {
  id: string; name: string; tiles: string[]; width: number; height: number;
  spawns: { enemy: string; x: number; y: number }[];
  items: { kind: string; ability: string; x: number; y: number; needs: string }[];
  doors: { to: string; x: number; y: number; spawn_x: number; spawn_y: number; needs: string }[];
  note: string;
}

export interface GameSpec {
  id: string; title: string; kind: "2d" | "3d"; template: string;
  created_at: number; updated_at: number;
  story: { opening: string; goal: string };
  world: { gravity: number; tile: number; air_control: number; terminal_velocity: number };
  player: {
    name: string; speed: number; jump: number; max_jumps: number;
    dash: boolean; wall_jump: boolean; attack: boolean; health: number; colour: string;
  };
  palette: { bg: string; ground: string; platform: string; hazard: string; accent: string };
  abilities: Ability[];
  enemies: EnemyKind[];
  rooms: Room[];
  notes: string;
}

export interface GameSummary {
  id: string; title: string; kind: string; template: string; updated_at: number;
  counts: { rooms: number; enemies: number; abilities: number };
}

/** The characters a room is drawn with, in the order the editor offers them. */
export const BRUSHES: { tile: string; label: string; hint: string }[] = [
  { tile: ".", label: "Air", hint: "Empty space" },
  { tile: "#", label: "Solid", hint: "Wall, floor, ceiling" },
  { tile: "=", label: "Platform", hint: "You can jump up through it" },
  { tile: "^", label: "Hazard", hint: "Takes a heart" },
  { tile: "P", label: "Start", hint: "Where the player appears" },
  { tile: "D", label: "Door", hint: "Pair it with a door in the room's list" },
  { tile: "A", label: "Pickup", hint: "A coin, or an ability if one is placed here" },
];

export const TEMPLATE_TEXT: Record<string, string> = {
  metroidvania: "Rooms that lock until you find the move that opens them — Hollow Knight's shape.",
  platformer: "Run and jump, room after room.",
  topdown: "Seen from above; gravity barely matters.",
  runner: "Always moving forward.",
  puzzle: "Think first, then move.",
  arena: "One room, waves of enemies.",
};
