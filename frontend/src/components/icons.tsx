// Line icons for the app shell. 24px grid, 1.8 stroke, currentColor.
import type { ReactNode } from "react";

const PATHS: Record<string, ReactNode> = {
  home: <path d="M3.5 10.5 12 4l8.5 6.5M6 9v10.5h4.5V14h3v5.5H18V9" />,
  calc: (
    <>
      <rect x="5" y="3" width="14" height="18" rx="2.5" />
      <path d="M8.5 7.5h7M8.5 12h.01M12 12h.01M15.5 12h.01M8.5 15.5h.01M12 15.5h.01M15.5 15.5h.01" />
    </>
  ),
  ask: <path d="M5 18.5V7.5A2.5 2.5 0 0 1 7.5 5h9A2.5 2.5 0 0 1 19 7.5v6a2.5 2.5 0 0 1-2.5 2.5H9.5L5 18.5ZM9 9.5h6M9 12.5h4" />,
  laws: (
    <>
      <path d="M12 4v16M7 20h10M5 8l-2 6a2.5 2.5 0 0 0 4 0L5 8Zm14 0-2 6a2.5 2.5 0 0 0 4 0l-2-6ZM5 8h14" />
    </>
  ),
  more: (
    <>
      <circle cx="5.5" cy="12" r="1.3" />
      <circle cx="12" cy="12" r="1.3" />
      <circle cx="18.5" cy="12" r="1.3" />
    </>
  ),
  back: <path d="M14.5 5.5 8 12l6.5 6.5" />,
  chevron: <path d="m9.5 6 6 6-6 6" />,
  user: (
    <>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 19.5c1.2-3.2 3.8-4.8 7-4.8s5.8 1.6 7 4.8" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="m15.5 15.5 4 4" />
    </>
  ),
  paye: (
    <>
      <rect x="3.5" y="6" width="17" height="12" rx="2" />
      <path d="M3.5 10h17M7 14.5h4" />
    </>
  ),
  compare: <path d="M7 4v16M17 4v16M4 8h6M14 15h6M4 8l3-3 3 3M14 15l3 3 3-3" />,
  company: (
    <>
      <path d="M4 20V6l7-2v16M11 9h9v11M4 20h16M7 8h1M7 11h1M7 14h1M14.5 12h2M14.5 15h2" />
    </>
  ),
  vat: (
    <>
      <path d="M6 18 18 6" />
      <circle cx="7.5" cy="7.5" r="2" />
      <circle cx="16.5" cy="16.5" r="2" />
    </>
  ),
  wht: (
    <>
      <path d="M12 3.5v11M8 10.5l4 4 4-4M5 17v2.5h14V17" />
    </>
  ),
  cgt: <path d="M4 17l5-5 4 3 7-8M15 7h5v5" />,
  stamp: (
    <>
      <path d="M9 4h6v5l3 3v3H6v-3l3-3V4ZM5 19h14" />
    </>
  ),
  health: <path d="M12 20s-7-4.3-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.7-7 10-7 10ZM8.5 12h2l1.2-2.2L13.5 14l1.2-2h1.8" />,
  adviser: (
    <>
      <circle cx="9" cy="8.5" r="3" />
      <path d="M3.5 19c.9-2.7 2.9-4.2 5.5-4.2s4.6 1.5 5.5 4.2M15.5 6.5a3 3 0 0 1 0 5M17.5 14.8c1.6.6 2.6 2 3 4.2" />
    </>
  ),
  news: (
    <>
      <path d="M5 5h11v14H6.5A1.5 1.5 0 0 1 5 17.5V5ZM16 9h3v8.5a1.5 1.5 0 0 1-3 0M8 9h5M8 12h5M8 15h3" />
    </>
  ),
  reform: <path d="M6 4h9l3 3v13H6V4ZM14.5 4v3.5H18M9 12h6M9 15.5h6" />,
  academy: <path d="M3 9l9-4.5L21 9l-9 4.5L3 9ZM7 11v4.5c1.4 1.3 3 2 5 2s3.6-.7 5-2V11M21 9v5" />,
  chat: <path d="M4.5 19l1.2-3.6A7 7 0 1 1 8.6 18L4.5 19ZM9 12h.01M12 12h.01M15 12h.01" />,
  info: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 11v5M12 8h.01" />
    </>
  ),
  code: <path d="m8.5 8-4 4 4 4M15.5 8l4 4-4 4M13.5 5.5l-3 13" />,
  globe: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M4 12h16M12 4c2.2 2.3 3.2 5 3.2 8s-1 5.7-3.2 8c-2.2-2.3-3.2-5-3.2-8s1-5.7 3.2-8Z" />
    </>
  ),
  mail: (
    <>
      <rect x="3.5" y="6" width="17" height="12" rx="2" />
      <path d="m4 7 8 6 8-6" />
    </>
  ),
  briefcase: (
    <>
      <rect x="3.5" y="7.5" width="17" height="11.5" rx="2" />
      <path d="M9 7.5V5.5h6v2M3.5 12.5h17" />
    </>
  ),
  megaphone: <path d="M4 10v4h3l7 4V6L7 10H4ZM17.5 9a4 4 0 0 1 0 6" />,
  pen: <path d="M5 19l1-4L15.5 5.5a2.1 2.1 0 0 1 3 3L9 18l-4 1ZM13.5 7.5l3 3" />,
  insight: <path d="M12 4a5.5 5.5 0 0 0-3 10.1V17h6v-2.9A5.5 5.5 0 0 0 12 4ZM9.5 20h5" />,
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 22 }: { name: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name] ?? PATHS.info}
    </svg>
  );
}
