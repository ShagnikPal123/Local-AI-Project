/** Connectors tab (Plan Null N10, Update 1 U9/U24).
 *
 * The owner asked for "all the basic ones Claude and GPT have" in the format of his reference photo — a dark grid
 * of rounded tiles, each with the app's mark in its own colour and the name in small grey text under it; a
 * connected one carries a small green dot — plus a way to add anything: a site, an API or an MCP server.
 *
 * The grid is grouped by category and searchable; a tile opens its sheet (how to connect, Test, what Nyx can do).
 * The machine connectors built into Nyx (files, apps, system control) keep their risk labels in their own group at
 * the end, because those reach this PC rather than an account somewhere else.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";
import { onWorkspaceEvent } from "../state/workspaceEvents";
import { AddConnector } from "./connectors/AddConnector";
import { ConnectorSheet } from "./connectors/ConnectorSheet";
import { Mark } from "./connectors/Mark";
import type { BuiltinConnector, CatalogResponse, Connector, UseSettings } from "./connectors/types";
import "./connectors/connectors.css";

const RISK_COLOR: Record<string, string> = { high: "var(--color-danger)", medium: "var(--color-warn)", low: "var(--color-ok)" };
const MACHINE_NAMES: Record<string, string> = {
  local_files: "Files on this PC", web_search: "Web search", app_launcher: "Open apps", mcp: "MCP bridge",
  dynamic_modularity: "Dynamic tools", system_control: "System control", google_services: "Google links",
  youtube: "YouTube (built in)", voice: "Voice", apple_design: "Apple design guide",
};
const HIDDEN_MACHINE = new Set(["finance", "obsidian"]);  // shown as Yahoo Finance and Obsidian in their categories

function Tile({ connector, onOpen }: { connector: Connector; onOpen: (c: Connector) => void }) {
  return (
    <button type="button" className="cx-tile" data-connected={connector.connected} onClick={() => onOpen(connector)}
      title={connector.description} aria-label={`${connector.name}${connector.connected ? ", connected" : ""}`}>
      <Mark connector={connector} />
      <span className="cx-tile__name">{connector.name}</span>
      {connector.connected && <span className="cx-dot" aria-hidden="true" />}
    </button>
  );
}

function MachineTile({ item, open, onToggle }: { item: BuiltinConnector; open: boolean; onToggle: () => void }) {
  const name = MACHINE_NAMES[item.name] ?? item.name.replace(/_/g, " ");
  return (
    <div className={`cx-machine${open ? " is-open" : ""}`}>
      <button type="button" className="cx-tile" data-connected={item.available} onClick={onToggle} aria-expanded={open}>
        <span className="cx-mark" style={{ ["--brand" as string]: RISK_COLOR[item.risk_level] ?? "var(--color-accent)" }} aria-hidden="true">
          {name.slice(0, 1).toUpperCase()}
        </span>
        <span className="cx-tile__name">{name}</span>
        {item.available && <span className="cx-dot" aria-hidden="true" />}
      </button>
      {open && (
        <div className="cx-machine__detail">
          <p>{item.description}</p>
          <div className="cx-pills">
            <span className="cx-pill" style={{ color: RISK_COLOR[item.risk_level] }}>{item.risk_level} risk</span>
            {item.is_write && <span className="cx-pill is-warn">can change things — asks first</span>}
            {!item.is_offline && <span className="cx-pill">uses the network</span>}
            {!item.available && <span className="cx-pill">not available</span>}
          </div>
        </div>
      )}
    </div>
  );
}

function Switch({ checked, label, hint, onChange }: { checked: boolean; label: string; hint: string; onChange: (v: boolean) => void }) {
  return (
    <label className="cx-switch">
      <button type="button" className="switch" role="switch" aria-checked={checked} onClick={() => onChange(!checked)} />
      <span><b>{label}</b><span className="cx-muted">{hint}</span></span>
    </label>
  );
}

export function ConnectorsPanel() {
  const [data, setData] = useState<CatalogResponse | null>(null);
  const [machine, setMachine] = useState<BuiltinConnector[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<string>("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [machineOpen, setMachineOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [catalog, registry] = await Promise.all([
      api.get<CatalogResponse>("/api/connectors/catalog"),
      api.get<{ connectors: BuiltinConnector[] }>("/api/connectors"),
    ]);
    if (catalog.ok) { setData(catalog.data); setError(null); } else setError(catalog.error);
    if (registry.ok) setMachine(registry.data.connectors.filter((c) => !HIDDEN_MACHINE.has(c.name)));
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => onWorkspaceEvent((event) => {
    if (["connectors.changed", "email.accounts.changed", "keys.changed"].includes(event.type)) void load();
  }), [load]);

  const byId = useMemo(() => new Map((data?.connectors ?? []).map((c) => [c.id, c])), [data]);
  const shown = useMemo(() => {
    const words = query.trim().toLowerCase();
    return (data?.connectors ?? []).filter((c) => {
      if (filter === "connected" && !c.connected) return false;
      if (filter !== "all" && filter !== "connected" && c.category !== filter && !(filter === "custom" && c.origin === "custom")) return false;
      if (!words) return true;
      return `${c.name} ${c.description} ${c.keywords.join(" ")} ${c.id}`.toLowerCase().includes(words);
    });
  }, [data, query, filter]);

  async function saveSettings(change: Partial<UseSettings>) {
    const result = await api.put<{ settings: UseSettings }>("/api/connectors/settings", change);
    if (result.ok) setData((d) => (d ? { ...d, settings: result.data.settings } : d));
  }

  const closeSheet = useCallback(() => setOpenId(null), []);
  const closeAdd = useCallback(() => setAdding(null), []);

  if (error && !data) return <PanelShell title="Connectors"><ErrorState error={error} /></PanelShell>;
  if (!data) return <PanelShell title="Connectors"><Loading what="Reading connectors" /></PanelShell>;

  const groups = data.categories
    .map((category) => ({
      ...category,
      items: shown.filter((c) => (category.id === "custom" ? c.category === "custom" || c.origin === "custom" : c.category === category.id && c.origin !== "custom"))
        .sort((a, b) => Number(b.connected) - Number(a.connected) || b.popular - a.popular || a.name.localeCompare(b.name)),
    }))
    .filter((group) => group.items.length > 0);
  const showMachine = (filter === "all" || filter === "builtin") && machine.length > 0 &&
    (!query.trim() || machine.some((m) => `${m.name} ${m.description}`.toLowerCase().includes(query.trim().toLowerCase())));
  const open = openId ? byId.get(openId) : undefined;

  return (
    <PanelShell
      title="Connectors"
      subtitle={`${data.connected} connected · ${data.total} apps, sites and servers`}
      actions={<button className="btn btn-primary" onClick={() => setAdding(query)}>+ Add Any App or Site</button>}
    >
      <div className="cx">
        <div className="cx-toolbar">
          <input className="cx-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search ${data.total} connectors — Gmail, Excel, Vercel, Stripe…`} aria-label="Search connectors" />
          <div className="cx-filters" role="tablist" aria-label="Show">
            {[{ id: "all", label: "All" }, { id: "connected", label: `Connected · ${data.connected}` },
              ...data.categories, { id: "builtin", label: "On this PC" }].map((item) => (
              <button key={item.id} type="button" role="tab" aria-selected={filter === item.id}
                className={`cx-chip${filter === item.id ? " is-on" : ""}`} onClick={() => setFilter(item.id)}>
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="cx-settings">
          <Switch checked={data.settings.auto} label="Pick connectors in chat"
            hint="Nyx uses a connected app when a message needs it. Write &name to choose one yourself."
            onChange={(auto) => void saveSettings({ auto })} />
          <Switch checked={data.settings.confirm_writes} label="Ask before changes"
            hint="Sending, posting or editing in another app waits for your yes in the chat."
            onChange={(confirm_writes) => void saveSettings({ confirm_writes })} />
        </div>

        {groups.length === 0 && !showMachine && (
          <div className="cx-empty">
            <p>No connector matches “{query}”.</p>
            <button className="btn btn-primary" onClick={() => setAdding(query)}>Add “{query || "it"}” as a new connector</button>
          </div>
        )}

        {filter !== "builtin" && groups.map((group) => (
          <section key={group.id} className="cx-group" aria-labelledby={`cx-g-${group.id}`}>
            <h2 id={`cx-g-${group.id}`} className="cx-group__title">
              {group.label}<span>{group.items.filter((c) => c.connected).length > 0 && `${group.items.filter((c) => c.connected).length} connected`}</span>
            </h2>
            <div className="cx-grid">
              {group.items.map((connector) => <Tile key={connector.id} connector={connector} onOpen={(c) => setOpenId(c.id)} />)}
              {group.id === "custom" && (
                <button type="button" className="cx-tile cx-tile--add" onClick={() => setAdding("")}>
                  <span className="cx-mark cx-mark--plus" aria-hidden="true">+</span>
                  <span className="cx-tile__name">Add any</span>
                </button>
              )}
            </div>
          </section>
        ))}

        {showMachine && (
          <section className="cx-group" aria-labelledby="cx-g-builtin">
            <h2 id="cx-g-builtin" className="cx-group__title">On this PC<span>built into Nyx · reach this computer, so changes ask first</span></h2>
            <div className="cx-grid">
              {machine.map((item) => (
                <MachineTile key={item.name} item={item} open={machineOpen === item.name}
                  onToggle={() => setMachineOpen((m) => (m === item.name ? null : item.name))} />
              ))}
            </div>
          </section>
        )}
      </div>

      {open && (
        <ConnectorSheet connector={open} onClose={closeSheet} onChanged={() => void load()}
          onAdd={(text) => { setOpenId(null); setAdding(text); }} />
      )}
      {adding !== null && (
        <AddConnector initial={adding} onClose={closeAdd}
          onAdded={(connector) => { void load(); if (connector) { setAdding(null); setOpenId(connector.id); } }}
          onOpen={(id) => { setAdding(null); setOpenId(id); }} />
      )}
    </PanelShell>
  );
}
