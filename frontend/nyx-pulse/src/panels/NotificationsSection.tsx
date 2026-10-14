/** Settings → Notifications: which corner the boxes appear in, what is worth a notice, and when the phone gets a text.
 *
 * Every change is saved on the spot (POST /api/notifications/settings) and the server tells every open window the new
 * corner, so the boxes move without a reload. The "Test" buttons send a real sample so the owner sees what they chose.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { setToastPosition, TOAST_POSITIONS, type ToastPosition } from "../state/toastStore";

interface Settings {
  position: ToastPosition;
  kinds: Record<string, boolean>;
  channels: Record<string, boolean>;
  phone: "off" | "away" | "always";
  away: "auto" | "on" | "off";
  away_minutes: number;
  min_seconds: number;
}

interface View {
  settings: Settings;
  away_now: boolean;
  phone_linked: boolean;
}

const POSITION_LABEL: Record<ToastPosition, string> = {
  "top-left": "Top left",
  "top-center": "Top middle",
  "top-right": "Top right",
  "bottom-left": "Bottom left",
  "bottom-center": "Bottom middle",
  "bottom-right": "Bottom right",
};

const KIND_LABEL: Record<string, string> = {
  done: "A chat finished",
  help: "A chat needs you",
  message: "A chat texts you",
  schedule: "A scheduled task ran",
};

const CHANNEL_LABEL: Record<string, string> = {
  toast: "Box in the app",
  desktop: "Windows notification",
  phone: "Text to my phone",
};

const PHONE_CHOICES: Array<{ id: Settings["phone"]; label: string; hint: string }> = [
  { id: "off", label: "Never", hint: "Only chats you linked to WhatsApp text you." },
  { id: "away", label: "When I'm away", hint: "Texts you when you've been off the computer a while." },
  { id: "always", label: "Always", hint: "Every notice also goes to your phone (at most 12 an hour)." },
];

const AWAY_CHOICES: Array<{ id: Settings["away"]; label: string }> = [
  { id: "auto", label: "Detect it" },
  { id: "on", label: "I'm away" },
  { id: "off", label: "I'm here" },
];

function Pill({ on, label, onClick, title }: { on: boolean; label: string; onClick: () => void; title?: string }) {
  return (
    <button
      type="button"
      className={on ? "btn" : "btn ghost"}
      aria-pressed={on}
      title={title}
      onClick={onClick}
      style={{ fontSize: 12, padding: "4px 10px" }}
    >
      {label}
    </button>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginBottom: 6 }}>{label}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>{children}</div>
    </div>
  );
}

export function NotificationsSection() {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [sent, setSent] = useState("");

  const load = useCallback(async () => {
    const result = await api.get<View>("/api/notifications");
    if (result.ok) setView(result.data);
    else setError(result.error);
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function save(change: Partial<Settings>) {
    setError("");
    const result = await api.post<View>("/api/notifications/settings", change);
    if (!result.ok) { setError(result.error); return; }
    setView(result.data);
    setToastPosition(result.data.settings.position);
  }

  async function test(kind: string, phone: boolean) {
    setSent("");
    const result = await api.post<{ delivered?: unknown }>("/api/notifications/test", { kind, phone });
    setSent(result.ok ? (phone ? "Sample sent. Check your phone." : "Sample sent.") : result.error);
  }

  const s = view?.settings;
  return (
    <div className="card">
      <div className="label" style={{ marginBottom: 4 }}>Notifications</div>
      <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
        Boxes and texts for when a chat finishes, needs your help, or writes to you. A chat you linked to WhatsApp
        always reaches your phone.
      </div>
      {error && <div role="alert" style={{ color: "var(--color-danger, #c0392b)", fontSize: 12, marginTop: 8 }}>{error}</div>}
      {!s && !error && <div style={{ fontSize: 12, marginTop: 10 }}>Reading notification settings…</div>}
      {s && (
        <>
          <Row label="Where the boxes appear">
            {TOAST_POSITIONS.map((place) => (
              <Pill key={place} on={s.position === place} label={POSITION_LABEL[place]} onClick={() => void save({ position: place })} />
            ))}
          </Row>
          <Row label="Tell me when">
            {Object.keys(KIND_LABEL).map((kind) => (
              <Pill
                key={kind}
                on={s.kinds[kind] !== false}
                label={KIND_LABEL[kind]}
                onClick={() => void save({ kinds: { ...s.kinds, [kind]: s.kinds[kind] === false } })}
              />
            ))}
          </Row>
          <Row label="How">
            {Object.keys(CHANNEL_LABEL).map((channel) => (
              <Pill
                key={channel}
                on={s.channels[channel] !== false}
                label={CHANNEL_LABEL[channel]}
                onClick={() => void save({ channels: { ...s.channels, [channel]: s.channels[channel] === false } })}
              />
            ))}
          </Row>
          <Row label={`Text my phone${view?.phone_linked ? "" : " (WhatsApp is not linked yet)"}`}>
            {PHONE_CHOICES.map((choice) => (
              <Pill key={choice.id} on={s.phone === choice.id} label={choice.label} title={choice.hint} onClick={() => void save({ phone: choice.id })} />
            ))}
          </Row>
          <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginTop: 6 }}>
            {PHONE_CHOICES.find((choice) => choice.id === s.phone)?.hint}
          </div>
          <Row label={`Am I away? Right now: ${view?.away_now ? "away" : "here"}. Auto counts as away after ${s.away_minutes} minutes idle.`}>
            {AWAY_CHOICES.map((choice) => (
              <Pill key={choice.id} on={s.away === choice.id} label={choice.label} onClick={() => void save({ away: choice.id })} />
            ))}
          </Row>
          <Row label="Try it">
            <button type="button" className="btn ghost" style={{ fontSize: 12 }} onClick={() => void test("done", false)}>Test the box</button>
            <button type="button" className="btn ghost" style={{ fontSize: 12 }} onClick={() => void test("help", true)}>Test the phone text</button>
          </Row>
          {sent && <div role="status" style={{ fontSize: 12, marginTop: 8 }}>{sent}</div>}
        </>
      )}
    </div>
  );
}
