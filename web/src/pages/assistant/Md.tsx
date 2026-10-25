import type { ReactNode } from "react";
import { siteOf } from "./common";

const INLINE = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|(https?:\/\/[^\s)]+)|\*\*([^*]+)\*\*/g;
const BULLET = /^\s*[-•*]\s+/;

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let n = 0;
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const k = `${key}-${n++}`;
    if (m[1] && m[2]) out.push(<a key={k} href={m[2]} target="_blank" rel="noopener noreferrer">{m[1]}</a>);
    else if (m[3]) out.push(<a key={k} href={m[3]} target="_blank" rel="noopener noreferrer">{siteOf(m[3])}</a>);
    else if (m[4]) out.push(<strong key={k}>{m[4]}</strong>);
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** A reply's light formatting, as the assistant writes it: paragraphs, "- " bullets, **bold** and links
 *  (http and https only). Everything else is shown as text. */
export function Md({ text }: { text: string }) {
  const out: ReactNode[] = [];
  text.split(/\n\s*\n/).forEach((block, b) => {
    let para: string[] = [];
    let items: string[] = [];
    const flush = () => {
      if (para.length) {
        out.push(<p key={`p${b}-${out.length}`}>{para.flatMap((l, i) => (i ? [<br key={i} />, ...inline(l, `${b}${i}`)] : inline(l, `${b}${i}`)))}</p>);
        para = [];
      }
      if (items.length) {
        out.push(<ul key={`u${b}-${out.length}`}>{items.map((l, i) => <li key={i}>{inline(l, `${b}l${i}`)}</li>)}</ul>);
        items = [];
      }
    };
    for (const line of block.split("\n")) {
      if (!line.trim()) continue;
      if (BULLET.test(line)) {
        if (para.length) flush();
        items.push(line.replace(BULLET, ""));
      } else {
        if (items.length) flush();
        para.push(line.trim());
      }
    }
    flush();
  });
  return <div className="as-md">{out}</div>;
}

/** The same reply for WhatsApp: its own *bold*, and links written out. */
export function mdToMessage(text: string): string {
  return text.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, "$1 ($2)").replace(/\*\*([^*]+)\*\*/g, "*$1*");
}
