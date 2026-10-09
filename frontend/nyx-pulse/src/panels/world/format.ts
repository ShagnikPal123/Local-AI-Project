/** Words for numbers the World tab shows — the two clocks especially (U38). */

export const DAYS_PER_YEAR = 360;

export function gameDate(days: number): string {
  const total = Math.max(0, days || 0);
  return `Year ${Math.floor(total / DAYS_PER_YEAR) + 1}, day ${Math.floor(total % DAYS_PER_YEAR) + 1}`;
}

export function gameDateShort(days: number): string {
  const total = Math.max(0, days || 0);
  return `Y${Math.floor(total / DAYS_PER_YEAR) + 1} · D${Math.floor(total % DAYS_PER_YEAR) + 1}`;
}

export function span(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) return `${days} day${days === 1 ? "" : "s"}${hours ? ` ${hours} h` : ""}`;
  if (hours) return `${hours} h${minutes ? ` ${minutes} min` : ""}`;
  if (minutes) return `${minutes} min`;
  return `${total % 60} s`;
}

export function when(ts: number): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export const KIND_LABELS: Record<string, string> = {
  capitol: "Capitol", house: "Homes", office: "Office", lab: "Laboratory", data_center: "Data centre", mine: "Mine",
  farm: "Farm", factory: "Factory", refinery: "Refinery", archive: "Archive", studio: "Studio", bank: "Bank",
  tower: "Tower", council: "Council hall", station: "Space station", planet: "Artificial planet",
};

export const ERAS = ["First Light", "Settlement", "Township", "City", "Metropolis", "Orbital", "Stellar"];

export const STATUS_WORDS: Record<string, string> = {
  idle: "Not started", running: "Running", paused: "Paused", complete: "Goal met", stopped: "Stopped",
};
