// Hand-drawn 24px stroke icon set (no icon font, no emoji).
const paths: Record<string, string> = {
  chat: "M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H10l-4.2 3.6c-.5.4-1.3.1-1.3-.6V16.3A2.5 2.5 0 0 1 4 14Z",
  ticket: "M4 7.5A1.5 1.5 0 0 1 5.5 6h13A1.5 1.5 0 0 1 20 7.5V10a2 2 0 0 0 0 4v2.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 16.5V14a2 2 0 0 0 0-4Z M14 6v12",
  queue: "M5 6h14 M5 12h14 M5 18h9 M18 16v4 M16 18h4",
  book: "M5 5.5A1.5 1.5 0 0 1 6.5 4H18v14H6.5A1.5 1.5 0 0 0 5 19.5Zm0 14A1.5 1.5 0 0 0 6.5 21H18 M9 8h5",
  gauge: "M4.5 16a7.5 7.5 0 1 1 15 0 M12 16l3.5-4.5 M12 16h.01",
  chart: "M4 20h16 M7 16v-4 M12 16V7 M17 16v-7",
  people: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-5 8c.6-3 2.6-4.5 5-4.5s4.4 1.5 5 4.5 M16 5.3a3 3 0 0 1 0 5.4 M17.5 14.6c1.3.6 2.2 2 2.5 4.4",
  sliders: "M5 7h9 M18 7h1 M5 17h3 M12 17h7 M16 5v4 M10 15v4",
  logout: "M14 4h3.5A1.5 1.5 0 0 1 19 5.5v13a1.5 1.5 0 0 1-1.5 1.5H14 M10 8l-4 4 4 4 M6 12h9",
  plus: "M12 5v14 M5 12h14",
  send: "M5 12h11 M12 6l6 6-6 6",
  up: "M12 19V6 M6 11l6-6 6 6",
  thumbUp: "M8 11v8H5.5A1.5 1.5 0 0 1 4 17.5v-5A1.5 1.5 0 0 1 5.5 11Zm0 0 3.2-6.2a1.6 1.6 0 0 1 3 .9L13.6 9H18a2 2 0 0 1 2 2.3l-1 6A2 2 0 0 1 17 19H8",
  thumbDown: "M16 13V5h2.5A1.5 1.5 0 0 1 20 6.5v5a1.5 1.5 0 0 1-1.5 1.5Zm0 0-3.2 6.2a1.6 1.6 0 0 1-3-.9l.6-3.3H6a2 2 0 0 1-2-2.3l1-6A2 2 0 0 1 7 5h9",
  upload: "M12 15V4 M7.5 8.5 12 4l4.5 4.5 M5 15v3.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V15",
  trash: "M5 7h14 M9.5 7V5.5A1.5 1.5 0 0 1 11 4h2a1.5 1.5 0 0 1 1.5 1.5V7 M7 7l.8 11.6A1.5 1.5 0 0 0 9.3 20h5.4a1.5 1.5 0 0 0 1.5-1.4L17 7",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Z M20 20l-4-4",
  handoff: "M5 13a7 7 0 0 1 14 0 M5 13v3a2 2 0 0 0 2 2h1v-6H7a2 2 0 0 0-2 2Zm14 0v3a2 2 0 0 1-2 2h-1v-6h1a2 2 0 0 1 2 2Z M16 18c0 1.5-1.5 2.5-4 2.5",
  pen: "M15 5l4 4 M4 20l1-4.5L15.5 5a1.4 1.4 0 0 1 2 0l1.5 1.5a1.4 1.4 0 0 1 0 2L8.5 19Z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12 M18 6 6 18",
  menu: "M4 7h16 M4 12h16 M4 17h16",
  sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z M12 2.5v2 M12 19.5v2 M4.5 4.5l1.4 1.4 M18.1 18.1l1.4 1.4 M2.5 12h2 M19.5 12h2 M4.5 19.5l1.4-1.4 M18.1 5.9l1.4-1.4",
  moon: "M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5Z",
  clock: "M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z M12 8v4l2.5 2",
  alert: "M12 4 3 19.5h18Z M12 10v4 M12 17h.01",
  back: "M15 6l-6 6 6 6",
  chevron: "M9 6l6 6-6 6",
  external: "M14 5h5v5 M19 5l-8 8 M17 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 4 18.5v-10A1.5 1.5 0 0 1 5.5 7H10",
  lock: "M7 11V8a5 5 0 0 1 10 0v3 M6 11h12v9H6Z M12 15v2",
  plug: "M9 3v4 M15 3v4 M7 7h10v4a5 5 0 0 1-10 0Z M12 16v5",
  note: "M7 4h7l4 4v12H7Z M14 4v4h4 M10 12h5 M10 16h5",
  refresh: "M19 8a7.5 7.5 0 1 0 .8 6 M19 4v4h-4",
  github:
    "M9 19c-4.3 1.4-4.3-2.5-6-3 M15 21v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21",
};

export type IconName = keyof typeof paths;

export function Icon({ name, size = 20, className, title }: { name: IconName; size?: number; className?: string; title?: string }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title && <title>{title}</title>}
      <path d={paths[name]} />
    </svg>
  );
}

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="logo-mark">
      <rect width="32" height="32" rx="7" fill="#1E3A8A" />
      <circle cx="10" cy="11" r="3.2" fill="#F8FAFC" />
      <circle cx="22" cy="21" r="3.2" fill="#06B6D4" />
      <path d="M10 14.5c0 6 12 1 12 3" fill="none" stroke="#F8FAFC" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}
