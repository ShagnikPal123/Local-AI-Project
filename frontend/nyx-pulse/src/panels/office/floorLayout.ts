/** Where every room and every desk sits on the floor.
 *
 * Deliberately deterministic and outside React: the same office always draws the same way, a new agent simply
 * appears at the next desk instead of shuffling everyone, and the layout can be unit-reasoned about without a
 * renderer. Rooms flow left to right and wrap, exactly like desks inside a room.
 */

import type { OfficeAgent, OfficeSection } from "./types";

export const DESK_W = 78;
export const DESK_H = 70;
export const ROOM_PAD = 16;
export const ROOM_HEADER = 30;
export const ROOM_GAP = 26;
export const MAX_DESK_COLS = 6;
export const ROW_WIDTH = 1240;

export interface DeskSpot {
  agent: OfficeAgent;
  x: number;
  y: number;
}

export interface Room {
  section: OfficeSection;
  x: number;
  y: number;
  width: number;
  height: number;
  desks: DeskSpot[];
}

export interface FloorPlan {
  rooms: Room[];
  width: number;
  height: number;
  byAgent: Record<string, { x: number; y: number }>;
}

function deskGrid(count: number): { cols: number; rows: number } {
  const cols = Math.max(1, Math.min(MAX_DESK_COLS, Math.ceil(Math.sqrt(Math.max(1, count)))));
  return { cols, rows: Math.max(1, Math.ceil(Math.max(1, count) / cols)) };
}

export function layout(sections: OfficeSection[], agents: OfficeAgent[]): FloorPlan {
  const ordered = [...sections].sort((a, b) => a.order - b.order);
  const byAgent: Record<string, { x: number; y: number }> = {};
  const rooms: Room[] = [];
  let cursorX = 0;
  let cursorY = 0;
  let lineHeight = 0;

  for (const section of ordered) {
    const staff = agents
      .filter((a) => a.section_id === section.id)
      .sort((a, b) => a.desk - b.desk || a.name.localeCompare(b.name));
    const { cols, rows } = deskGrid(staff.length);
    const width = ROOM_PAD * 2 + cols * DESK_W;
    const height = ROOM_HEADER + ROOM_PAD * 2 + rows * DESK_H;

    if (cursorX > 0 && cursorX + width > ROW_WIDTH) {
      cursorX = 0;
      cursorY += lineHeight + ROOM_GAP;
      lineHeight = 0;
    }

    const desks: DeskSpot[] = staff.map((agent, index) => {
      const x = cursorX + ROOM_PAD + (index % cols) * DESK_W + DESK_W / 2;
      const y = cursorY + ROOM_HEADER + ROOM_PAD + Math.floor(index / cols) * DESK_H + DESK_H / 2;
      byAgent[agent.id] = { x, y };
      return { agent, x, y };
    });

    rooms.push({ section, x: cursorX, y: cursorY, width, height, desks });
    cursorX += width + ROOM_GAP;
    lineHeight = Math.max(lineHeight, height);
  }

  const width = Math.max(...rooms.map((r) => r.x + r.width), 320) + ROOM_GAP;
  const height = (rooms.length ? cursorY + lineHeight : 200) + ROOM_GAP;
  return { rooms, width, height, byAgent };
}

/** A gentle curve between two desks, bowed away from the straight line so two-way talk does not overlap. */
export function talkPath(from: { x: number; y: number }, to: { x: number; y: number }): string {
  const midX = (from.x + to.x) / 2;
  const midY = (from.y + to.y) / 2;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.max(1, Math.hypot(dx, dy));
  const bow = Math.min(60, length / 4);
  const controlX = midX + (-dy / length) * bow;
  const controlY = midY + (dx / length) * bow;
  return `M ${from.x} ${from.y} Q ${controlX} ${controlY} ${to.x} ${to.y}`;
}
