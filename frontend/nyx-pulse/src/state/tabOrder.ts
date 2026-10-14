/** The owner's own order for the tabs (S4: "drag and reorder them"), kept in this browser.
 *
 * Only ids are saved, never labels, so a renamed or merged tab cannot break the list. Tabs the saved list does not know
 * about (a new core tab, a tab the AI just made) slot in right after the tab that came before them in the shipped order,
 * rather than piling up at the end, so an update does not bury them.
 */

const KEY = "ichos.tab-order";

export function readTabOrder(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function saveTabOrder(ids: string[]): void {
  try { localStorage.setItem(KEY, JSON.stringify(ids)); } catch { /* the order simply will not persist */ }
}

export function clearTabOrder(): void {
  try { localStorage.removeItem(KEY); } catch { /* nothing to clear */ }
}

/** `items` in the saved order; unknown items keep their place relative to their shipped neighbours. */
export function applyOrder<T extends { id: string }>(items: T[], order: string[]): T[] {
  if (!order.length) return items;
  const byId = new Map(items.map((item) => [item.id, item]));
  const result: T[] = [];
  const seen = new Set<string>();
  for (const id of order) {
    const item = byId.get(id);
    if (item && !seen.has(id)) { result.push(item); seen.add(id); }
  }
  items.forEach((item, index) => {
    if (seen.has(item.id)) return;
    const before = items.slice(0, index).reverse().find((x) => seen.has(x.id));
    const at = before ? result.findIndex((x) => x.id === before.id) + 1 : 0;
    result.splice(at, 0, item);
    seen.add(item.id);
  });
  return result;
}

/** The full id list after `dragged` is dropped next to `over` (before it, or after it when `after`). */
export function moveTab(ids: string[], dragged: string, over: string, after: boolean): string[] {
  if (dragged === over) return ids;
  const rest = ids.filter((id) => id !== dragged);
  const at = rest.indexOf(over);
  if (at < 0) return ids;
  rest.splice(after ? at + 1 : at, 0, dragged);
  return rest;
}
