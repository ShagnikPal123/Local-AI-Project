/** The two bars that had no home in the chat before: connectors in use, and remote access (the phone link).
 *  Both only read; turning things on stays in Connectors and Settings → Phone, where the checks live. */

import { useEffect, useState } from "react";
import { api } from "../../../api";

interface Connector { id: string; name: string; category?: string }

export function useConnectors(): Connector[] | null {
  const [list, setList] = useState<Connector[] | null>(null);
  useEffect(() => {
    let alive = true;
    void api.get<{ connectors: Connector[] }>("/api/connectors/mine").then((r) => { if (alive) setList(r.ok ? r.data.connectors : []); });
    return () => { alive = false; };
  }, []);
  return list;
}

export function ConnectorsBody({ list }: { list: Connector[] | null }) {
  if (!list) return <p className="cb-note">Loading…</p>;
  if (list.length === 0) return <p className="cb-note">No connectors yet. Add Gmail, Drive, Slack and more in the Connectors tab.</p>;
  return (
    <ul className="cb-list">
      {list.map((c) => <li key={c.id}><span className="cb-on" aria-hidden="true" /> {c.name}{c.category ? <em> · {c.category}</em> : null}</li>)}
    </ul>
  );
}

interface Phone { enabled: boolean; running: boolean; port: number; urls: string[]; error: string; devices?: unknown[] }

export function usePhone(): Phone | null {
  const [phone, setPhone] = useState<Phone | null>(null);
  useEffect(() => {
    let alive = true;
    void api.get<Phone>("/api/phone").then((r) => { if (alive && r.ok) setPhone(r.data); });
    return () => { alive = false; };
  }, []);
  return phone;
}

export function RemoteBody({ phone }: { phone: Phone | null }) {
  if (!phone) return <p className="cb-note">Remote access is owner-only, or the engine did not answer.</p>;
  return (
    <div className="cb-note">
      <p>{phone.running ? `Your phone can reach Ichos on port ${phone.port}.` : "Remote access is off. Turn it on in Settings → Phone."}</p>
      {phone.error && <p className="cb-warn">{phone.error}</p>}
      {phone.urls.length > 0 && <ul className="cb-list">{phone.urls.map((u) => <li key={u}><code>{u}</code></li>)}</ul>}
      <p>{(phone.devices?.length ?? 0)} paired {(phone.devices?.length ?? 0) === 1 ? "phone" : "phones"}.</p>
    </div>
  );
}
