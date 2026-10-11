/** The chat panes' layout: a tree of splits whose leaves are chats (owner, 2026-10-10: "open multiple chats on one
 *  screen and drag them to where I want … more flexibility with left to right and up and down").
 *
 *  A split lays its children out in a row (side by side) or a column (stacked); any leaf can be split again in either
 *  direction, so the screen can hold two columns, a 2×2 grid, one tall chat beside two stacked ones, and so on. The
 *  tree is drawn flat (`layout`) — every pane is absolutely placed — so moving a pane never remounts its chat.
 *  Pure functions: every change returns a new tree. */

export type Edge = "left" | "right" | "top" | "bottom" | "center";
export interface Leaf { kind: "leaf"; id: string; chatId: string }
export interface Split { kind: "split"; id: string; dir: "row" | "col"; children: PaneNode[]; sizes: number[] }
export type PaneNode = Leaf | Split;

/** The home chat (with the chat list) is always one of the panes and cannot be closed. */
export const MAIN = "main";
export const MAX_PANES = 6;
/** Smallest share a pane can be dragged down to, in percent of its split. */
export const MIN_SHARE = 12;

export const SINGLE: PaneNode = { kind: "leaf", id: MAIN, chatId: "" };

let counter = 0;
export function newId(prefix: string): string {
  counter += 1;
  return `${prefix}${Date.now().toString(36)}${counter}`;
}

const clone = <T,>(node: T): T => JSON.parse(JSON.stringify(node)) as T;

export function leaves(node: PaneNode): Leaf[] {
  return node.kind === "leaf" ? [node] : node.children.flatMap(leaves);
}

export function findNode(node: PaneNode, id: string): PaneNode | null {
  if (node.id === id) return node;
  if (node.kind === "leaf") return null;
  for (const child of node.children) {
    const found = findNode(child, id);
    if (found) return found;
  }
  return null;
}

function findParent(node: PaneNode, id: string): { parent: Split; index: number } | null {
  if (node.kind === "leaf") return null;
  const index = node.children.findIndex((c) => c.id === id);
  if (index >= 0) return { parent: node, index };
  for (const child of node.children) {
    const found = findParent(child, id);
    if (found) return found;
  }
  return null;
}

/** One child splits collapse into the child; a split inside a split of the same direction is flattened into it. */
export function normalize(node: PaneNode): PaneNode {
  if (node.kind === "leaf") return node;
  const children: PaneNode[] = [];
  const sizes: number[] = [];
  node.children.forEach((raw, i) => {
    const child = normalize(raw);
    const share = node.sizes[i] ?? 100 / node.children.length;
    if (child.kind === "split" && child.dir === node.dir) {
      const total = child.sizes.reduce((a, b) => a + b, 0) || 100;
      child.children.forEach((grand, j) => { children.push(grand); sizes.push((child.sizes[j] / total) * share); });
    } else {
      children.push(child);
      sizes.push(share);
    }
  });
  if (children.length === 1) return children[0];
  const total = sizes.reduce((a, b) => a + b, 0) || 100;
  return { ...node, children, sizes: sizes.map((s) => (s / total) * 100) };
}

/** Put `leaf` against an edge of the node `targetId` (a pane, a split, or the whole layout). */
export function insertAt(root: PaneNode, targetId: string, edge: Edge, leaf: Leaf): PaneNode {
  if (edge === "center") return root;
  const dir = edge === "left" || edge === "right" ? "row" : "col";
  const before = edge === "left" || edge === "top";
  const tree = clone(root);
  const target = findNode(tree, targetId) ?? tree;
  // Against the outside of a split running the same way: one more child at that end.
  if (target.kind === "split" && target.dir === dir) {
    const n = target.children.length;
    target.sizes = target.sizes.map((s) => (s * n) / (n + 1));
    if (before) { target.children.unshift(leaf); target.sizes.unshift(100 / (n + 1)); }
    else { target.children.push(leaf); target.sizes.push(100 / (n + 1)); }
    return normalize(tree);
  }
  const loc = findParent(tree, target.id);
  // Beside a pane in a split running the same way: share that pane's room.
  if (loc && loc.parent.dir === dir) {
    const { parent, index } = loc;
    const half = parent.sizes[index] / 2;
    parent.sizes[index] = half;
    const at = before ? index : index + 1;
    parent.children.splice(at, 0, leaf);
    parent.sizes.splice(at, 0, half);
    return normalize(tree);
  }
  const split: Split = { kind: "split", id: newId("s"), dir, children: before ? [leaf, target] : [target, leaf], sizes: [50, 50] };
  if (!loc) return normalize(split);
  loc.parent.children[loc.index] = split;
  return normalize(tree);
}

export function removeLeaf(root: PaneNode, leafId: string): PaneNode {
  if (leafId === MAIN) return root;
  const tree = clone(root);
  const loc = findParent(tree, leafId);
  if (!loc) return tree;
  loc.parent.children.splice(loc.index, 1);
  loc.parent.sizes.splice(loc.index, 1);
  return normalize(tree);
}

function swap(root: PaneNode, a: string, b: string): PaneNode {
  const tree = clone(root);
  const first = findNode(tree, a);
  const second = findNode(tree, b);
  if (!first || !second || first.kind !== "leaf" || second.kind !== "leaf") return root;
  const keep = { id: first.id, chatId: first.chatId };
  first.id = second.id; first.chatId = second.chatId;
  second.id = keep.id; second.chatId = keep.chatId;
  return tree;
}

/** Move a pane next to another (or onto it: the two swap places). */
export function moveLeaf(root: PaneNode, leafId: string, targetId: string, edge: Edge): PaneNode {
  if (leafId === targetId) return root;
  const leaf = findNode(root, leafId);
  if (!leaf || leaf.kind !== "leaf") return root;
  if (edge === "center") return swap(root, leafId, targetId);
  // Removing the pane can collapse the split it was aimed at; then aim at the whole layout.
  const without = leafId === MAIN ? detachMain(root) : removeLeaf(root, leafId);
  const target = findNode(without, targetId) ? targetId : without.id;
  return insertAt(without, target, edge, clone(leaf));
}

function detachMain(root: PaneNode): PaneNode {
  const tree = clone(root);
  const loc = findParent(tree, MAIN);
  if (!loc) return tree;
  loc.parent.children.splice(loc.index, 1);
  loc.parent.sizes.splice(loc.index, 1);
  return normalize(tree);
}

export function setChat(root: PaneNode, leafId: string, chatId: string): PaneNode {
  const tree = clone(root);
  const leaf = findNode(tree, leafId);
  if (!leaf || leaf.kind !== "leaf" || leaf.chatId === chatId) return root;
  leaf.chatId = chatId;
  return tree;
}

/** Drag the divider after child `index` of a split by `delta` percent of that split. */
export function resize(root: PaneNode, splitId: string, index: number, delta: number): PaneNode {
  const tree = clone(root);
  const split = findNode(tree, splitId);
  if (!split || split.kind !== "split" || index < 0 || index >= split.children.length - 1) return root;
  const a = split.sizes[index];
  const b = split.sizes[index + 1];
  const d = Math.max(MIN_SHARE - a, Math.min(b - MIN_SHARE, delta));
  split.sizes[index] = a + d;
  split.sizes[index + 1] = b - d;
  return tree;
}

/** Equal shares everywhere — "tidy up". */
export function evenOut(node: PaneNode): PaneNode {
  if (node.kind === "leaf") return node;
  return { ...node, children: node.children.map(evenOut), sizes: node.children.map(() => 100 / node.children.length) };
}

export interface Box { x: number; y: number; w: number; h: number }
export interface PlacedLeaf extends Box { id: string; chatId: string }
export interface PlacedDivider extends Box { splitId: string; index: number; dir: "row" | "col"; span: number }

/** Where every pane and divider goes, in percent of the whole area. `span` is the split's own length along its
 *  direction (also in percent), so a divider drag in pixels can be turned back into a share. */
export function layout(root: PaneNode): { leaves: PlacedLeaf[]; dividers: PlacedDivider[] } {
  const out = { leaves: [] as PlacedLeaf[], dividers: [] as PlacedDivider[] };
  const walk = (node: PaneNode, box: Box) => {
    if (node.kind === "leaf") { out.leaves.push({ ...box, id: node.id, chatId: node.chatId }); return; }
    let offset = 0;
    node.children.forEach((child, i) => {
      const share = node.sizes[i];
      const childBox = node.dir === "row"
        ? { x: box.x + (offset * box.w) / 100, y: box.y, w: (share * box.w) / 100, h: box.h }
        : { x: box.x, y: box.y + (offset * box.h) / 100, w: box.w, h: (share * box.h) / 100 };
      if (i > 0) {
        out.dividers.push(node.dir === "row"
          ? { splitId: node.id, index: i - 1, dir: "row", span: box.w, x: childBox.x, y: box.y, w: 0, h: box.h }
          : { splitId: node.id, index: i - 1, dir: "col", span: box.h, x: box.x, y: childBox.y, w: box.w, h: 0 });
      }
      walk(child, childBox);
      offset += share;
    });
  };
  walk(root, { x: 0, y: 0, w: 100, h: 100 });
  return out;
}

/** A saved layout is used only if it is a well-formed tree holding the home chat exactly once. */
export function validate(value: unknown): PaneNode | null {
  const seen = new Set<string>();
  const check = (node: unknown): node is PaneNode => {
    if (!node || typeof node !== "object") return false;
    const n = node as Record<string, unknown>;
    if (typeof n.id !== "string" || seen.has(n.id)) return false;
    seen.add(n.id);
    if (n.kind === "leaf") return typeof n.chatId === "string";
    if (n.kind !== "split" || (n.dir !== "row" && n.dir !== "col")) return false;
    const children = n.children as unknown[];
    const sizes = n.sizes as unknown[];
    return Array.isArray(children) && Array.isArray(sizes) && children.length >= 1 && children.length === sizes.length
      && sizes.every((s) => typeof s === "number" && s > 0) && children.every(check);
  };
  if (!check(value)) return null;
  const all = leaves(value);
  if (all.filter((l) => l.id === MAIN).length !== 1 || all.length > MAX_PANES) return null;
  return normalize(value);
}

/** Which edge of a pane the pointer is over: the outer 28 % of each side, else the middle. */
export function edgeAt(px: number, py: number, rect: { left: number; top: number; width: number; height: number }): Edge {
  const fx = (px - rect.left) / Math.max(1, rect.width);
  const fy = (py - rect.top) / Math.max(1, rect.height);
  const distances: [Edge, number][] = [["left", fx], ["right", 1 - fx], ["top", fy], ["bottom", 1 - fy]];
  const [edge, distance] = distances.reduce((best, cur) => (cur[1] < best[1] ? cur : best));
  return distance < 0.28 ? edge : "center";
}
