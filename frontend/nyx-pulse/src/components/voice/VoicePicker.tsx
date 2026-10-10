/** Hear a voice before choosing it: hover (or keyboard-focus) a voice for a moment and it says a short line in that
 * exact voice; moving away stops it; clicking chooses it. The owner (2026-10-09): "the current voices I cannot hear
 * before clicking". Used by Settings → Voices and by Equalize. */

import { useEffect, useMemo, useRef, useState } from "react";
import { onSpeakingChange, speakText, stopSpeaking } from "../../voice/voicePlayer";
import "./voicepicker.css";

export interface PickableVoice { id: string; name: string; locale?: string; gender?: string; engine?: string }

const HOVER_MS = 350;

export function VoicePicker({ voices, value, onPick, sample = "Hi there. This is how I sound when I talk with you.",
  label = "Voices" }: {
  voices: PickableVoice[]; value: string; onPick: (id: string) => void; sample?: string; label?: string;
}) {
  const [query, setQuery] = useState("");
  const [playing, setPlaying] = useState("");
  const timer = useRef<number | null>(null);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return voices.filter((v) => !q || `${v.name} ${v.locale ?? ""} ${v.gender ?? ""}`.toLowerCase().includes(q)).slice(0, 120);
  }, [voices, query]);

  const cancel = () => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
  };
  const listen = (voice: PickableVoice) => {
    cancel();
    timer.current = window.setTimeout(() => {
      stopSpeaking();
      setPlaying(voice.id);
      void speakText(sample, { voice: voice.id, role: "" }).catch(() => setPlaying(""));
    }, HOVER_MS);
  };
  const leave = () => {
    cancel();
    if (playing) { stopSpeaking(); setPlaying(""); }
  };
  useEffect(() => () => { cancel(); stopSpeaking(); }, []);
  // The wave moves while the sample is actually being heard, and stops when it ends.
  useEffect(() => onSpeakingChange((now) => { if (!now) setPlaying(""); }), []);

  return (
    <div className="vp">
      <input className="vp-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
        placeholder={`Search ${voices.length} voices — name, language, female, male…`} aria-label={`Search ${label}`} />
      <p className="vp-hint">Hover a voice to hear it. Click to choose.</p>
      <ul className="vp-list" role="listbox" aria-label={label}>
        {shown.map((voice) => (
          <li key={`${voice.engine}-${voice.id}`}>
            <button type="button" role="option" aria-selected={voice.id === value}
              className={`vp-voice${voice.id === value ? " is-on" : ""}${playing === voice.id ? " is-playing" : ""}`}
              onMouseEnter={() => listen(voice)} onMouseLeave={leave} onFocus={() => listen(voice)} onBlur={leave}
              onClick={() => { leave(); onPick(voice.id); }}>
              <span className="vp-wave" aria-hidden="true"><i /><i /><i /></span>
              <b>{voice.name}</b>
              <small>{[voice.locale, voice.gender, voice.engine === "sapi" ? "offline" : ""].filter(Boolean).join(" · ")}</small>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
