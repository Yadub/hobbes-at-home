import type { ReactNode } from "react";

// The assistant's own icons, drawn like the shared ones in components/Icons.tsx.

function Svg({ children, fill = false }: { children: ReactNode; fill?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" focusable="false"
      fill={fill ? "currentColor" : "none"} stroke={fill ? "none" : "currentColor"} strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}

export const PersonCircleIcon = () => (
  <Svg><circle cx="12" cy="12" r="9" /><circle cx="12" cy="10" r="3.2" /><path d="M6.4 18.4c1.3-2 3.3-3 5.6-3s4.3 1 5.6 3" /></Svg>
);

export const ArrowUpRightIcon = () => <Svg><path d="M8 16 16.5 7.5" /><path d="M9.5 7.2h7.3v7.3" /></Svg>;

export const CheckCircleIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <circle cx="12" cy="12" r="10" fill="currentColor" />
    <path d="m7.6 12.3 3 3 5.8-6.2" fill="none" stroke="var(--surface)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const LockSmallIcon = () => (
  <Svg><rect x="5.5" y="10.5" width="13" height="9.5" rx="2" /><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" /></Svg>
);

// What a suggested job is about.
export const PlaneIcon = () => (
  <Svg><path d="M10.6 13.4 4 11.2l1.2-1.6 7.6.8 4.4-4.6c.8-.8 2.1-.9 2.7-.3.6.6.5 1.9-.3 2.7l-4.6 4.4.8 7.6-1.6 1.2-2.2-6.6-3.4 3.2.2 2.4-1.2 1-1.4-3-3-1.4 1-1.2 2.4.2Z" /></Svg>
);

export const BedIcon = () => (
  <Svg><path d="M3.5 6v13" /><path d="M3.5 15.5h17V19" /><path d="M3.5 12h17v3.5" /><path d="M20.5 12a3.5 3.5 0 0 0-3.5-3.5h-6.5V12" /><circle cx="7" cy="9.6" r="1.8" /></Svg>
);

export const TicketIcon = () => (
  <Svg><path d="M4 7.5h16v3a1.5 1.5 0 0 0 0 3v3H4v-3a1.5 1.5 0 0 0 0-3Z" /><path d="M14.5 7.5v9" strokeDasharray="1.5 2" /></Svg>
);

export const RupeeIcon = () => (
  <Svg><path d="M7 5h10" /><path d="M7 9.5h10" /><path d="M9.5 5h1a4 4 0 0 1 0 8.5H7l7.5 6" /></Svg>
);

export const EyeIcon = () => (
  <Svg><path d="M2.8 12s3.3-6 9.2-6 9.2 6 9.2 6-3.3 6-9.2 6-9.2-6-9.2-6Z" /><circle cx="12" cy="12" r="2.8" /></Svg>
);

export const SparklesIcon = () => (
  <Svg><path d="M10 4.5 11.4 9l4.6 1.5-4.6 1.4L10 16.5 8.6 12 4 10.5 8.6 9Z" /><path d="M17.5 14l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7Z" /><path d="M17 3.5l.5 1.4 1.4.5-1.4.5-.5 1.4-.5-1.4-1.4-.5 1.4-.5Z" /></Svg>
);

export const RepeatIcon = () => (
  <Svg><path d="M4.5 11V9.5a3 3 0 0 1 3-3h11" /><path d="m15.5 3.5 3 3-3 3" /><path d="M19.5 13v1.5a3 3 0 0 1-3 3h-11" /><path d="m8.5 20.5-3-3 3-3" /></Svg>
);

export const ChatIcon = () => (
  <Svg><path d="M12 4c4.7 0 8.5 3.2 8.5 7.2s-3.8 7.2-8.5 7.2c-1 0-2-.1-2.9-.4L5 19.8l1-3.6c-1.6-1.3-2.5-3-2.5-5C3.5 7.2 7.3 4 12 4Z" /></Svg>
);

export const CopyIcon = () => (
  <Svg><rect x="8.5" y="8.5" width="11" height="11" rx="2.2" /><path d="M15.5 8.5V6.7a2.2 2.2 0 0 0-2.2-2.2H6.7a2.2 2.2 0 0 0-2.2 2.2v6.6a2.2 2.2 0 0 0 2.2 2.2h1.8" /></Svg>
);

export const TerminalIcon = () => (
  <Svg><rect x="3.5" y="5" width="17" height="14" rx="2.5" /><path d="m7.5 10 2.5 2-2.5 2" /><path d="M12.5 14.5h4" /></Svg>
);
