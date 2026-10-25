import type { CSSProperties, ReactNode } from "react";
import { Link } from "../router";
import { ChevronRight } from "./Icons";

export function Section({ header, footer, big = false, action, children }: {
  header?: ReactNode; footer?: ReactNode; big?: boolean; action?: ReactNode; children: ReactNode;
}) {
  return (
    <section className="section">
      {header && (
        <h2 className={`section-header${big ? " big" : ""}`}>
          <span>{header}</span>
          {action && <span className="action">{action}</span>}
        </h2>
      )}
      {children}
      {footer && <p className="section-footer">{footer}</p>}
    </section>
  );
}

export function List({ children }: { children: ReactNode }) {
  return <div className="list">{children}</div>;
}

type RowProps = {
  title: ReactNode;
  sub?: ReactNode;
  value?: ReactNode;
  icon?: ReactNode;
  tile?: string;
  thumb?: ReactNode;
  to?: string;
  onClick?: () => void;
  chevron?: boolean;
  tone?: "tinted" | "destructive" | "center";
  trailing?: ReactNode;
  disabled?: boolean;
  label?: string;
};

/** One row of a grouped list: optional icon tile or thumbnail, title and subtitle, a value, a chevron. */
export function Row({ title, sub, value, icon, tile, thumb, to, onClick, chevron, tone, trailing, disabled, label }: RowProps) {
  const cls = ["row", icon ? "has-icon" : "", thumb ? "has-thumb" : "", tone ?? ""].filter(Boolean).join(" ");
  const inner = (
    <>
      {icon && <span className="icon-tile" style={{ "--tile": tile } as CSSProperties}>{icon}</span>}
      {thumb}
      <span className="row-main">
        <span className="row-title">{title}</span>
        {sub && <span className="row-sub">{sub}</span>}
      </span>
      {value !== undefined && <span className="row-value">{value}</span>}
      {trailing}
      {(chevron ?? Boolean(to)) && <ChevronRight />}
    </>
  );
  if (to) return <Link to={to} className={cls} aria-label={label}>{inner}</Link>;
  if (onClick) return <button type="button" className={cls} onClick={onClick} disabled={disabled} aria-label={label}>{inner}</button>;
  return <div className={cls}>{inner}</div>;
}
