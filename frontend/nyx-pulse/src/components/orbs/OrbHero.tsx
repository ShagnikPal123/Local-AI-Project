/** The empty chat: a large thought-orb that walks through every shape Ichos
 * can take, with a legend that says what each one means. When a turn runs,
 * the same shapes show up beside the status, so this is where they are learnt.
 * Picking a chip holds that shape; the suggestions wear the orb they would wake.
 */

import { useEffect, useState } from "react";
import { useReducedMotion } from "../../useReducedMotion";
import { IchosOrb } from "./IchosOrb";
import { ORB_MEANING, orbStateFor, type OrbState } from "./orbState";

const CYCLE: OrbState[] = ["breathing", "searching", "working", "solving", "connecting", "weaving", "composing", "shaping", "listening"];

interface Props {
  intro: string;
  suggestions: string[];
  onSuggestion?: (text: string) => void;
}

export function OrbHero({ intro, suggestions, onSuggestion }: Props) {
  const reduced = useReducedMotion();
  const [index, setIndex] = useState(0);
  const [held, setHeld] = useState<OrbState | null>(null);

  useEffect(() => {
    if (held || reduced) return;
    const id = window.setInterval(() => setIndex((i) => (i + 1) % CYCLE.length), 4200);
    return () => window.clearInterval(id);
  }, [held, reduced]);

  const state = held ?? CYCLE[index];

  return (
    <div className="orb-hero">
      <div className="orb-hero__stage">
        <IchosOrb state={state} size={128} label={`Ichos is ${ORB_MEANING[state]}`} />
      </div>
      <h2 className="orb-hero__title">What should Ichos think about?</h2>
      <p className="orb-hero__caption" aria-live="polite">
        <b>{state}</b> — {ORB_MEANING[state]}
      </p>
      <div className="orb-hero__legend" role="group" aria-label="What the orb shapes mean">
        {CYCLE.map((s) => (
          <button
            key={s}
            type="button"
            className="orb-chip"
            aria-pressed={state === s && held === s}
            title={ORB_MEANING[s]}
            onClick={() => setHeld((h) => (h === s ? null : s))}
          >
            <IchosOrb state={s} size={16} decorative />
            {s}
          </button>
        ))}
      </div>
      <p className="orb-hero__intro">{intro}</p>
      {suggestions.length > 0 && (
        <div className="orb-suggestions">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="orb-suggestion"
              onClick={() => onSuggestion?.(suggestion)}
              onMouseEnter={() => setHeld(orbStateFor(suggestion))}
              onMouseLeave={() => setHeld(null)}
              onFocus={() => setHeld(orbStateFor(suggestion))}
              onBlur={() => setHeld(null)}
            >
              <IchosOrb state={orbStateFor(suggestion)} size={20} decorative />
              <span>{suggestion}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
