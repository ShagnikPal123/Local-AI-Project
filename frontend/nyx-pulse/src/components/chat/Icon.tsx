/** Inline stroke icons for the chat UI.
 *
 * One 24×24 grid, `currentColor`, stroke width from `--nyx-icon-stroke`, so a
 * designer can recolour or re-weight every glyph from CSS. Icons are always
 * decorative (`aria-hidden`): the button or row that holds one carries the
 * accessible name, and meaning is never carried by the glyph alone.
 */

import type { ReactNode } from "react";

export type IconName =
  | "copy" | "check" | "retry" | "speaker" | "branch" | "thumbUp" | "thumbDown"
  | "chevronDown" | "chevronRight" | "paperclip" | "send" | "stop" | "close"
  | "alert" | "info" | "terminal" | "globe" | "file" | "search" | "image"
  | "code" | "brain" | "sparkle" | "plus" | "pencil" | "trash" | "arrowDown"
  | "external" | "users" | "shield" | "bolt" | "gear" | "mail" | "calendar"
  | "database" | "clock" | "pause" | "more" | "download" | "bookmark" | "refresh"
  | "memory" | "chat" | "monitor" | "link" | "wand";

const PATHS: Record<IconName, ReactNode> = {
  copy: (<><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></>),
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  retry: (<><path d="M20 11a8 8 0 1 0-2.34 5.66" /><path d="M20 4v7h-7" /></>),
  refresh: (<><path d="M4 12a8 8 0 0 1 13.66-5.66L20 8.5" /><path d="M20 4v4.5h-4.5" /><path d="M20 12a8 8 0 0 1-13.66 5.66L4 15.5" /><path d="M4 20v-4.5h4.5" /></>),
  speaker: (<><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="M16 9a4 4 0 0 1 0 6" /><path d="M18.5 6.5a7.5 7.5 0 0 1 0 11" /></>),
  branch: (<><circle cx="6" cy="5.5" r="2" /><circle cx="6" cy="18.5" r="2" /><circle cx="18" cy="8" r="2" /><path d="M6 7.5v9" /><path d="M18 10c0 4-6 3.5-11 6.5" /></>),
  thumbUp: (<><path d="M7.5 10.5V20H4.5v-9.5z" /><path d="M7.5 10.5l3.8-6.3a1.7 1.7 0 0 1 3.1 1.1L13.8 9.5h4.9a1.8 1.8 0 0 1 1.8 2.1l-1.2 6.8A1.8 1.8 0 0 1 17.5 20H7.5" /></>),
  thumbDown: (<><path d="M7.5 13.5V4H4.5v9.5z" /><path d="M7.5 13.5l3.8 6.3a1.7 1.7 0 0 0 3.1-1.1l-.6-4.2h4.9a1.8 1.8 0 0 0 1.8-2.1l-1.2-6.8A1.8 1.8 0 0 0 17.5 4H7.5" /></>),
  chevronDown: <path d="M6 9.5l6 6 6-6" />,
  chevronRight: <path d="M9.5 6l6 6-6 6" />,
  paperclip: <path d="M20 11.5l-7.8 7.8a5 5 0 0 1-7.1-7.1l8.2-8.2a3.3 3.3 0 0 1 4.7 4.7l-8.2 8.2a1.7 1.7 0 0 1-2.4-2.4l7.5-7.5" />,
  send: (<><path d="M12 19V5.5" /><path d="M6 11.5l6-6 6 6" /></>),
  stop: <rect x="7" y="7" width="10" height="10" rx="1.5" />,
  close: (<><path d="M6.5 6.5l11 11" /><path d="M17.5 6.5l-11 11" /></>),
  alert: (<><path d="M12 4.2l9 15.6H3z" /><path d="M12 10v4.2" /><path d="M12 17.2v.1" /></>),
  info: (<><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5" /><path d="M12 7.8v.1" /></>),
  terminal: (<><rect x="3" y="4.5" width="18" height="15" rx="2" /><path d="M7 9.5l3 2.5-3 2.5" /><path d="M12.5 15h4.5" /></>),
  globe: (<><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17" /><path d="M12 3.5c2.5 2.6 3.6 5.4 3.6 8.5S14.5 17.9 12 20.5C9.5 17.9 8.4 15.1 8.4 12S9.5 6.1 12 3.5z" /></>),
  file: (<><path d="M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5z" /><path d="M14 3.5v5h5" /></>),
  search: (<><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></>),
  image: (<><rect x="3.5" y="4.5" width="17" height="15" rx="2" /><circle cx="9" cy="10" r="1.6" /><path d="M20.5 16l-5-5-9 8.5" /></>),
  code: (<><path d="M8.5 7.5L4 12l4.5 4.5" /><path d="M15.5 7.5L20 12l-4.5 4.5" /><path d="M13.5 5l-3 14" /></>),
  brain: (<><path d="M9.5 4.5a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 5.5 1.5V6a3 3 0 0 0-2.5-1.5z" /><path d="M14.5 4.5a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-5.5 1.5" /></>),
  sparkle: (<><path d="M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9L12 17.5l-1.9-5.1L5 10.5l5.1-1.9z" /><path d="M18.5 16l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" /></>),
  plus: (<><path d="M12 5v14" /><path d="M5 12h14" /></>),
  pencil: (<><path d="M15.5 4.5l4 4L9 19H5v-4z" /><path d="M13.5 6.5l4 4" /></>),
  trash: (<><path d="M4.5 7h15" /><path d="M9.5 7V4.5h5V7" /><path d="M6.5 7l1 13h9l1-13" /></>),
  arrowDown: (<><path d="M12 5v13.5" /><path d="M6 12.5l6 6 6-6" /></>),
  external: (<><path d="M14 4.5h5.5V10" /><path d="M19.5 4.5l-8 8" /><path d="M17 13.5v5a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 4 18.5v-10A1.5 1.5 0 0 1 5.5 7h5" /></>),
  users: (<><circle cx="9" cy="8.5" r="3.2" /><path d="M3.5 19.5a5.5 5.5 0 0 1 11 0" /><circle cx="16.8" cy="9.5" r="2.5" /><path d="M16 14.2a4.6 4.6 0 0 1 4.8 4.8" /></>),
  shield: (<><path d="M12 3.5l7.5 3v5.5c0 4.4-3.1 7.6-7.5 9-4.4-1.4-7.5-4.6-7.5-9V6.5z" /><path d="M9 12l2.2 2.2L15.5 10" /></>),
  bolt: <path d="M13 3.5L5.5 13.5h6l-1 7 7.5-10h-6z" />,
  gear: (<><circle cx="12" cy="12" r="3" /><path d="M12 3.5v2.2M12 18.3v2.2M20.5 12h-2.2M5.7 12H3.5M18 6l-1.6 1.6M7.6 16.4L6 18M18 18l-1.6-1.6M7.6 7.6L6 6" /></>),
  mail: (<><rect x="3.5" y="5.5" width="17" height="13" rx="2" /><path d="M4 7l8 6 8-6" /></>),
  calendar: (<><rect x="3.5" y="5" width="17" height="15" rx="2" /><path d="M3.5 10h17" /><path d="M8 3v4M16 3v4" /></>),
  database: (<><ellipse cx="12" cy="6" rx="7.5" ry="2.8" /><path d="M4.5 6v12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6" /><path d="M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8" /></>),
  clock: (<><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>),
  pause: (<><path d="M9 6.5v11" /><path d="M15 6.5v11" /></>),
  more: (<><circle cx="6" cy="12" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="18" cy="12" r="1.2" /></>),
  download: (<><path d="M12 4v11" /><path d="M7 10.5l5 5 5-5" /><path d="M5 19.5h14" /></>),
  bookmark: <path d="M7 4h10v16l-5-3.8L7 20z" />,
  memory: (<><path d="M12 20.5a8.5 8.5 0 1 1 8.5-8.5" /><path d="M12 7.5V12l3 2" /><path d="M17 17.5l1.8 1.8 3-3.3" /></>),
  chat: <path d="M5 5.5h14a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 17.5h-7l-4.5 3v-3H5A1.5 1.5 0 0 1 3.5 16V7A1.5 1.5 0 0 1 5 5.5z" />,
  monitor: (<><rect x="3" y="4.5" width="18" height="12" rx="2" /><path d="M12 16.5V20" /><path d="M8.5 20h7" /></>),
  link: (<><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1" /><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1" /></>),
  wand: (<><path d="M4.5 19.5l10-10" /><path d="M12.5 7.5l4 4" /><path d="M18 3.5v3M16.5 5h3" /><path d="M7 4v2M6 5h2" /><path d="M19.5 14v2M18.5 15h2" /></>),
};

interface IconProps {
  name: IconName;
  /** Pixel size; defaults to the `--nyx-icon-size` token via CSS. */
  size?: number;
  className?: string;
}

export function Icon({ name, size, className }: IconProps) {
  return (
    <svg
      className={className ? `nyx-icon ${className}` : "nyx-icon"}
      data-icon={name}
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}

/** Tool category → icon. Categories are free-form server strings, so match loosely. */
export function iconForCategory(category: string | undefined, name?: string): IconName {
  const c = `${category ?? ""} ${name ?? ""}`.toLowerCase();
  if (/shell|terminal|powershell|process|command|system|exec/.test(c)) return "terminal";
  if (/search/.test(c)) return "search";
  if (/web|browser|http|fetch|url|internet/.test(c)) return "globe";
  if (/image|vision|screenshot|photo|camera/.test(c)) return "image";
  if (/code|python|script|git/.test(c)) return "code";
  if (/memory|learn|recall/.test(c)) return "memory";
  if (/agent|delegate|team/.test(c)) return "users";
  if (/mail|email|message|notify/.test(c)) return "mail";
  if (/calendar|schedule|reminder|time/.test(c)) return "calendar";
  if (/db|database|sql|data/.test(c)) return "database";
  if (/file|fs|folder|document|pdf|read|write/.test(c)) return "file";
  if (/skill/.test(c)) return "bolt";
  return "gear";
}
