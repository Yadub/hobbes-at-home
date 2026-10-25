import type { ReactNode } from "react";

// Line icons drawn in the spirit of SF Symbols (SF Symbols themselves may only be used in apps for
// Apple platforms). `filled` gives the selected-tab variant where one exists.

type P = { filled?: boolean; className?: string };

function Svg({ children, className, fill = false }: { children: ReactNode; className?: string; fill?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" className={className} aria-hidden="true" focusable="false"
      fill={fill ? "currentColor" : "none"} stroke={fill ? "none" : "currentColor"} strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}

export const HouseIcon = ({ filled, className }: P) =>
  filled ? (
    <Svg className={className} fill>
      <path d="M12 3.2c.3 0 .6.1.8.3l8 6.6c.5.4.2 1.2-.4 1.2H19v8.2c0 .8-.7 1.5-1.5 1.5H14.5v-5.5h-5V21H6.5C5.7 21 5 20.3 5 19.5v-8.2H3.6c-.6 0-.9-.8-.4-1.2l8-6.6c.2-.2.5-.3.8-.3Z" />
    </Svg>
  ) : (
    <Svg className={className}><path d="M3.8 10.6 12 3.9l8.2 6.7" /><path d="M5.8 9.2v10.3c0 .5.4.9.9.9h3.4v-5.6h3.8v5.6h3.4c.5 0 .9-.4.9-.9V9.2" /></Svg>
  );

export const ForkKnifeIcon = ({ className }: P) => (
  <Svg className={className}>
    <path d="M7 3v6.2a2 2 0 0 1-2 2v0" /><path d="M9 3v6.2a2 2 0 0 0 2 2v0" /><path d="M5 3v6.2c0 1.1.9 2 2 2h2c1.1 0 2-.9 2-2V3" />
    <path d="M8 11.2V21" /><path d="M17 21V3c-2 1.2-3 3.7-3 7v3.5h3" />
  </Svg>
);

export const EnvelopeIcon = ({ filled, className }: P) =>
  filled ? (
    <Svg className={className} fill>
      <path d="M4.5 5h15A2.5 2.5 0 0 1 22 7.5v.3l-10 6.4L2 7.8v-.3A2.5 2.5 0 0 1 4.5 5Z" />
      <path d="M2 9.6v7A2.5 2.5 0 0 0 4.5 19h15a2.5 2.5 0 0 0 2.5-2.4v-7l-9.3 6a1.3 1.3 0 0 1-1.4 0Z" />
    </Svg>
  ) : (
    <Svg className={className}><rect x="2.8" y="5.2" width="18.4" height="13.6" rx="2.4" /><path d="m3.4 6.6 8.6 6.3 8.6-6.3" /></Svg>
  );

export const AtIcon = ({ className }: P) => (
  <Svg className={className}><circle cx="12" cy="12" r="3.6" /><path d="M15.6 12v1.3a2.6 2.6 0 0 0 5.2 0V12a8.8 8.8 0 1 0-3.4 7" /></Svg>
);
export const ArrowClockwiseIcon = ({ className }: P) => (
  <Svg className={className}><path d="M19.6 12.4a7.6 7.6 0 1 1-2.3-5.8" /><path d="M18.2 3.4v3.6h-3.6" /></Svg>
);
export const ArrowUpRightIcon = ({ className }: P) => <Svg className={className}><path d="M7.5 16.5 16.5 7.5M9 7.5h7.5V15" /></Svg>;
export const CheckIcon = ({ className }: P) => <Svg className={className}><path d="m5 12.6 4.4 4.4L19 7.4" /></Svg>;
export const GlobeIcon = ({ className }: P) => <Svg className={className}><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.3 2.4 3.4 5.2 3.4 8.5s-1.1 6.1-3.4 8.5c-2.3-2.4-3.4-5.2-3.4-8.5S9.7 5.9 12 3.5Z" /></Svg>;

export const PeopleIcon = ({ filled, className }: P) =>
  filled ? (
    <Svg className={className} fill>
      <circle cx="9" cy="8" r="3.6" /><path d="M2.5 19.3C2.5 15.9 5.4 13.6 9 13.6s6.5 2.3 6.5 5.7c0 .5-.4.7-.8.7H3.3c-.4 0-.8-.2-.8-.7Z" />
      <circle cx="16.6" cy="8.6" r="2.9" /><path d="M17 13.2c2.8.1 4.5 2.1 4.5 4.8 0 .5-.4.7-.8.7h-3.8c.1-2.2-.6-4-1.9-5.3.6-.1 1.3-.2 2-.2Z" />
    </Svg>
  ) : (
    <Svg className={className}>
      <circle cx="9" cy="8" r="3.4" /><path d="M3 19.4c0-3.2 2.7-5.4 6-5.4s6 2.2 6 5.4" /><circle cx="16.7" cy="8.6" r="2.7" /><path d="M17 13.7c2.5.2 4 2 4 4.6" />
    </Svg>
  );

export const ChecklistIcon = ({ className }: P) => (
  <Svg className={className}>
    <path d="m3.5 6.5 1.6 1.6L8 5.2" /><path d="M11 6.7h9.5" /><path d="m3.5 12.5 1.6 1.6L8 11.2" /><path d="M11 12.7h9.5" />
    <path d="m3.5 18.5 1.6 1.6L8 17.2" /><path d="M11 18.7h9.5" />
  </Svg>
);

export const GearIcon = ({ className }: P) => (
  <Svg className={className}>
    <circle cx="12" cy="12" r="3.1" />
    <path d="M19.4 13.5a7.6 7.6 0 0 0 0-3l2-1.6-2-3.4-2.4.9a7.5 7.5 0 0 0-2.6-1.5L14 2.4h-4l-.4 2.5A7.5 7.5 0 0 0 7 6.4l-2.4-.9-2 3.4 2 1.6a7.6 7.6 0 0 0 0 3l-2 1.6 2 3.4 2.4-.9a7.5 7.5 0 0 0 2.6 1.5l.4 2.5h4l.4-2.5a7.5 7.5 0 0 0 2.6-1.5l2.4.9 2-3.4Z" />
  </Svg>
);

export const ChevronRight = ({ className = "row-chev" }: P) => (
  <svg viewBox="0 0 8 14" className={className} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="m1.5 1.5 5 5.5-5 5.5" /></svg>
);

export const ChevronLeft = ({ className = "chev" }: P) => (
  <svg viewBox="0 0 13 21" className={className} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><path d="M11 2 2.5 10.5 11 19" /></svg>
);

export const PlusIcon = ({ className }: P) => <Svg className={className}><path d="M12 5v14M5 12h14" /></Svg>;
export const MinusIcon = ({ className }: P) => <Svg className={className}><path d="M5 12h14" /></Svg>;

export const CameraIcon = ({ className }: P) => (
  <Svg className={className}>
    <path d="M4.5 7.5h2.6l1.5-2.2h6.8l1.5 2.2h2.6c.9 0 1.6.7 1.6 1.6v8.8c0 .9-.7 1.6-1.6 1.6h-15c-.9 0-1.6-.7-1.6-1.6V9.1c0-.9.7-1.6 1.6-1.6Z" />
    <circle cx="12" cy="13.2" r="3.6" />
  </Svg>
);

export const PhotoIcon = ({ className }: P) => (
  <Svg className={className}>
    <rect x="3" y="4.5" width="18" height="15" rx="2.5" /><circle cx="8.5" cy="9.5" r="1.6" /><path d="m3.5 17 5-4.6 4 3.6 3-2.6 5 4.4" />
  </Svg>
);

export const XCircleFill = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
    <circle cx="12" cy="12" r="10" fill="currentColor" /><path d="m8.6 8.6 6.8 6.8m0-6.8-6.8 6.8" stroke="var(--surface)" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

export const FlameIcon = ({ className }: P) => (
  <Svg className={className} fill>
    <path d="M12.6 2.5c.3 2.9-1.3 4.4-2.9 6C8 10.2 6.2 12 6.2 15a5.8 5.8 0 0 0 11.6 0c0-2.3-1-4.2-2.2-5.5-.2 1.4-.9 2.5-2 3 .5-3.6-.1-7.5-1-10Z" />
  </Svg>
);

export const ScaleIcon = ({ className }: P) => (
  <Svg className={className}>
    <rect x="3.5" y="3.5" width="17" height="17" rx="4.5" /><path d="M8.2 9.3a5 5 0 0 1 7.6 0" /><path d="m12 10.5 1.3-1.9" />
  </Svg>
);

export const FigureIcon = ({ className }: P) => (
  <Svg className={className} fill>
    <circle cx="13.4" cy="4.2" r="2" />
    <path d="M10.6 7.4c.4-.3 1-.4 1.5-.3l2.6.6c.4.1.7.3.9.6l1.7 2.6 2.3.5a1 1 0 0 1-.4 2l-2.7-.6a1 1 0 0 1-.6-.4l-.9-1.4-.9 3.4 2.3 2.2c.2.2.3.4.3.6l.6 4a1 1 0 0 1-2 .3l-.5-3.6-2.6-2.4-.9 2.6c-.1.3-.3.5-.5.6l-3.5 2a1 1 0 0 1-1-1.7l3.2-1.8 2-7.4-1.3-.3-1.6 2.6a1 1 0 0 1-1.7-1l1.8-3Z" />
  </Svg>
);

export const CalendarIcon = ({ className }: P) => (
  <Svg className={className}><rect x="3.5" y="5" width="17" height="15.5" rx="2.6" /><path d="M3.5 9.8h17M8 3v4M16 3v4" /></Svg>
);
export const CheckCircle = ({ className }: P) => (
  <Svg className={className}><circle cx="12" cy="12" r="8.6" /><path d="m8.3 12.3 2.4 2.4 5-5.2" /></Svg>
);
export const HalfCircle = ({ className }: P) => (
  <Svg className={className}><circle cx="12" cy="12" r="8.6" /><path d="M12 3.4v17.2A8.6 8.6 0 0 0 12 3.4Z" fill="currentColor" stroke="none" /></Svg>
);
export const AlertCircle = ({ className }: P) => (
  <Svg className={className}><circle cx="12" cy="12" r="8.6" /><path d="M12 7.6v5.2M12 16.2v.1" /></Svg>
);
export const ArrowUp = ({ className }: P) => <Svg className={className}><path d="M12 19V5M6 11l6-6 6 6" /></Svg>;
export const ArrowDown = ({ className }: P) => <Svg className={className}><path d="M12 5v14M6 13l6 6 6-6" /></Svg>;
export const MoreIcon = ({ className }: P) => (
  <Svg className={className} fill><circle cx="5.5" cy="12" r="1.9" /><circle cx="12" cy="12" r="1.9" /><circle cx="18.5" cy="12" r="1.9" /></Svg>
);
export const ClockIcon = ({ className }: P) => <Svg className={className}><circle cx="12" cy="12" r="8.6" /><path d="M12 7v5.2l3.2 2" /></Svg>;
export const SearchIcon = ({ className }: P) => <Svg className={className}><circle cx="10.8" cy="10.8" r="6.3" /><path d="m15.5 15.5 4.8 4.8" /></Svg>;
export const ChartIcon = ({ className }: P) => <Svg className={className}><path d="M5 20V12M10 20V6M15 20v-9M20 20V4" /></Svg>;
export const CupIcon = ({ className }: P) => (
  <Svg className={className}><path d="M5 9.5h11V14a5 5 0 0 1-5 5h-1a5 5 0 0 1-5-5V9.5Z" /><path d="M16 11h1.4a2.6 2.6 0 0 1 0 5.2H16" /><path d="M8.6 3.6c-.6.9.6 1.8 0 2.7M12.2 3.6c-.6.9.6 1.8 0 2.7" /></Svg>
);
export const TargetIcon = ({ className }: P) => <Svg className={className}><circle cx="12" cy="12" r="8.6" /><circle cx="12" cy="12" r="4.6" /><circle cx="12" cy="12" r="0.8" fill="currentColor" /></Svg>;
export const HeartIcon = ({ className }: P) => (
  <Svg className={className} fill><path d="M12 20.3c-.2 0-.5-.1-.7-.2C7.2 17.5 3 14.1 3 9.4 3 6.6 5.1 4.5 7.7 4.5c1.8 0 3.3.9 4.3 2.4 1-1.5 2.5-2.4 4.3-2.4 2.6 0 4.7 2.1 4.7 4.9 0 4.7-4.2 8.1-8.3 10.7-.2.1-.5.2-.7.2Z" /></Svg>
);
export const GiftIcon = ({ className }: P) => (
  <Svg className={className}>
    <rect x="3.8" y="8.2" width="16.4" height="4.2" rx="1" /><path d="M5.4 12.4v6.9c0 .6.5 1.1 1.1 1.1h11c.6 0 1.1-.5 1.1-1.1v-6.9" />
    <path d="M12 8.2v12.2" /><path d="M12 8.2c-1.2-2.9-3.9-4.3-5.1-3.2-1.1 1 .2 3.2 5.1 3.2ZM12 8.2c1.2-2.9 3.9-4.3 5.1-3.2 1.1 1-.2 3.2-5.1 3.2Z" />
  </Svg>
);
export const SunIcon = ({ className }: P) => (
  <Svg className={className}>
    <circle cx="12" cy="12" r="4.1" />
    <path d="M12 2.8v2.1M12 19.1v2.1M2.8 12h2.1M19.1 12h2.1M5.5 5.5 7 7M17 17l1.5 1.5M5.5 18.5 7 17M17 7l1.5-1.5" />
  </Svg>
);
export const StarIcon = ({ className }: P) => (
  <Svg className={className} fill>
    <path d="M12 3.4c.3 0 .6.2.7.5l2.1 4.6 5 .5c.7.1.9.9.4 1.3l-3.8 3.3 1.1 4.9c.1.7-.6 1.2-1.2.8L12 16.8l-4.3 2.5c-.6.4-1.3-.1-1.2-.8l1.1-4.9-3.8-3.3c-.5-.4-.3-1.2.4-1.3l5-.5 2.1-4.6c.1-.3.4-.5.7-.5Z" />
  </Svg>
);
export const CpuIcon = ({ className }: P) => (
  <Svg className={className}><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9.5 3v3M14.5 3v3M9.5 18v3M14.5 18v3M3 9.5h3M3 14.5h3M18 9.5h3M18 14.5h3" /></Svg>
);
export const ArchiveIcon = ({ className }: P) => (
  <Svg className={className}><rect x="3" y="4" width="18" height="4.5" rx="1.2" /><path d="M4.8 8.5v9.8c0 .9.7 1.7 1.7 1.7h11c.9 0 1.7-.8 1.7-1.7V8.5" /><path d="M10 12.5h4" /></Svg>
);
export const LockIcon = ({ className }: P) => (
  <Svg className={className}><rect x="5" y="10.5" width="14" height="10" rx="2.2" /><path d="M8 10.5V7.8a4 4 0 0 1 8 0v2.7" /></Svg>
);
export const BoltIcon = ({ className }: P) => (
  <Svg className={className} fill><path d="M13.5 2.5 5 13.3c-.3.4 0 .9.4.9h5.4l-1.3 7.3c-.1.5.6.8.9.4L19 11.1c.3-.4 0-.9-.4-.9h-5.4l1.3-7.3c.1-.5-.6-.8-1-.4Z" /></Svg>
);

export function Spinner({ label = "Working" }: { label?: string }) {
  return (
    <svg className="spinner" viewBox="0 0 24 24" role="img" aria-label={label}>
      {Array.from({ length: 8 }, (_, i) => (
        <rect key={i} x="11" y="2" width="2.2" height="6" rx="1.1" fill="currentColor"
          opacity={0.25 + (i / 8) * 0.75} transform={`rotate(${i * 45} 12 12)`} />
      ))}
    </svg>
  );
}
export const BellIcon = ({ className }: P) => (
  <Svg className={className} fill><path d="M12 2.8c-3.3 0-5.9 2.6-5.9 5.9v3.8L4.5 15c-.4.6 0 1.4.8 1.4h13.4c.8 0 1.2-.8.8-1.4l-1.6-2.5V8.7c0-3.3-2.6-5.9-5.9-5.9Z" /><path d="M9.4 18.2a2.7 2.7 0 0 0 5.2 0Z" /></Svg>
);
