import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { back } from "../router";
import { ChevronLeft } from "./Icons";

/** A page with an iOS-style navigation bar: a large title that, once scrolled past, becomes the small
 *  centred title of a translucent bar. `backTo` adds a back button. `head` replaces the large title
 *  with a header of the page's own (a contact card, say); the bar's title still appears once it's
 *  scrolled past. */
export function Page({ title, eyebrow, backTo, backLabel, trailing, head: custom, children }: {
  title: string;
  eyebrow?: ReactNode;
  backTo?: string;
  backLabel?: string;
  trailing?: ReactNode;
  head?: ReactNode;
  children: ReactNode;
}) {
  const head = useRef<HTMLDivElement>(null);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    document.title = title === "Summary" ? "Hobbes at Home" : `${title} · Hobbes at Home`;
    const el = head.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setScrolled(!(e?.isIntersecting ?? true)), {
      rootMargin: "-50px 0px 0px 0px",
    });
    io.observe(el);
    return () => io.disconnect();
  }, [title]);

  return (
    <div className="page">
      <header className={`navbar${scrolled ? " scrolled" : ""}`}>
        <div className="navbar-leading">
          {backTo && (
            <button className="bar-button" onClick={() => back(backTo)}>
              <ChevronLeft />
              {backLabel ?? "Back"}
            </button>
          )}
        </div>
        <div className="navbar-title" aria-hidden={!scrolled}>{title}</div>
        <div className="navbar-trailing">{trailing}</div>
      </header>
      {custom ? <div className="page-head" ref={head}>{custom}</div> : (
        <div className="page-head" ref={head}>
          {eyebrow && <div className="eyebrow">{eyebrow}</div>}
          <h1 className="large-title">{title}</h1>
        </div>
      )}
      <main id="main">{children}</main>
    </div>
  );
}
