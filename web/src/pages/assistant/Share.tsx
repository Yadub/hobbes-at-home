import type { AssistantTask } from "../../api/client";
import { useToast } from "../../components/Controls";
import { List, Row, Section } from "../../components/List";
import { ChatIcon, CopyIcon } from "./icons";
import { mdToMessage } from "./Md";

/** The result as a plain message to send someone: the options with prices, times and links (not the
 *  reasons, which are written for the owner), or the summary when there are no options. WhatsApp's
 *  *bold* marks the names. */
export function messageText(t: AssistantTask): string {
  const r = t.result;
  if (!r) return t.title;
  const lines = [`*${t.title}*`];
  if (r.options.length === 0) {
    lines.push(mdToMessage(r.summary));
    return lines.join("\n");
  }
  r.options.forEach((o, i) => {
    lines.push("", `${i + 1}. *${o.title}*${r.recommended === i ? " (recommended)" : ""}`);
    const detail = [o.price, o.when].filter(Boolean).join(" · ");
    if (detail) lines.push(detail);
    if (o.link) lines.push(o.link);
  });
  lines.push("", "Prices change; check before booking.");
  return lines.join("\n");
}

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // The clipboard needs HTTPS; until the tailnet has it, copy through a hidden text box.
    const box = document.createElement("textarea");
    box.value = text;
    box.setAttribute("readonly", "");
    box.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.appendChild(box);
    box.select();
    box.setSelectionRange(0, text.length);
    const ok = document.execCommand("copy");
    box.remove();
    return ok;
  }
}

/** Send the shortlist on WhatsApp (it opens with the message filled in; you pick who and tap Send), or
 *  copy it to paste anywhere. */
export function Share({ task }: { task: AssistantTask }) {
  const toast = useToast();
  const text = messageText(task);
  return (
    <Section footer="A plain message with the options, prices and links. Nothing is sent until you send it.">
      <List>
        <Row icon={<ChatIcon />} tile="var(--good)" title="Send on WhatsApp" chevron={false}
          onClick={() => window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener")} />
        <Row icon={<CopyIcon />} tile="var(--gray)" title="Copy as Message" chevron={false}
          onClick={async () => toast({ text: (await copy(text)) ? "Copied. Paste it into any chat." : "Couldn't copy on this device." })} />
      </List>
    </Section>
  );
}
