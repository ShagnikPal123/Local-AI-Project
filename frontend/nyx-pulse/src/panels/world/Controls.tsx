/** The speed control (U38) and the timeline strip along the bottom: real time against game time. */

import { span } from "./format";
import type { SpeedId, WorldLimits, WorldSnapshot } from "./types";

export function SpeedControl({ speed, limits, onChange }: {
  speed: SpeedId;
  limits: WorldLimits;
  onChange: (speed: SpeedId) => void;
}) {
  return (
    <div className="wld-speed" role="radiogroup" aria-label="Speed — how fast the world works, and how much care each task gets">
      {limits.speeds.map((option) => (
        <button key={option.id} type="button" role="radio" aria-checked={speed === option.id}
                className={speed === option.id ? "is-on" : ""} disabled={!option.allowed}
                onClick={() => onChange(option.id)}
                title={option.allowed ? option.what : `${option.what} Not on this ${limits.machine} machine.`}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

const MARKS = new Set(["era", "project", "war", "startup", "birth", "death", "law", "station"]);

export function TimelineStrip({ snapshot }: { snapshot: WorldSnapshot }) {
  const world = snapshot.world;
  const now = Date.now() / 1000;
  const start = world.created_at || now;
  const deadline = world.duration && world.status === "running" && world.time_left !== null
    ? now + (world.time_left ?? 0) : 0;
  const end = Math.max(now, deadline, start + 60);
  const at = (ts: number) => `${Math.max(0, Math.min(100, ((ts - start) / (end - start)) * 100))}%`;
  const marks = snapshot.timeline.filter((e) => MARKS.has(e.kind)).slice(-120);
  const progress = world.duration ? Math.min(1, world.spent / world.duration) : 0;
  return (
    <footer className="wld-timeline" aria-label="The world's timeline">
      <div className="wld-timeline__clock">
        <b>{world.game_date}</b>
        <span>{world.era_name} era · game time</span>
      </div>
      <div className="wld-timeline__track" role="img"
           aria-label={`From founding to ${world.duration ? "the deadline" : "now"}, with ${marks.length} events`}>
        <div className="wld-timeline__line" />
        {world.duration > 0 && <div className="wld-timeline__fill" style={{ width: `${progress * 100}%` }} />}
        {marks.map((event, index) => (
          <span key={`${event.ts}-${index}`} className={`wld-mark is-${event.kind}`} style={{ left: at(event.ts) }}
                title={event.text} />
        ))}
        <span className="wld-timeline__now" style={{ left: at(now) }} />
      </div>
      <div className="wld-timeline__real">
        <b>{world.duration ? `${span(world.time_left ?? 0)} left` : "No deadline"}</b>
        <span>{world.duration ? `of ${span(world.duration)} real time` : "runs until the goal is met"}</span>
      </div>
    </footer>
  );
}
