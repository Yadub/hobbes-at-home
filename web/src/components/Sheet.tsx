import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

/** A modal sheet: slides up from the bottom on a phone, a centred panel on a laptop. Cancel on the
 *  left, the action on the right, as in iOS. Escape and tapping outside close it. `cancelLabel` renames
 *  the left button, or (null) leaves it out, for a sheet whose only button is "Done". */
export function Sheet({ open, title, onClose, action, cancelLabel = "Cancel", children }: {
  open: boolean;
  title: string;
  onClose: () => void;
  action?: { label: string; onClick: () => void; disabled?: boolean; busy?: boolean };
  cancelLabel?: string | null;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      document.documentElement.style.overflow = "hidden";
    } else if (!open && d.open) {
      d.close();
    }
    return () => {
      document.documentElement.style.overflow = "";
    };
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="sheet"
      aria-label={title}
      onCancel={(e) => { e.preventDefault(); onClose(); }}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}
    >
      {open && (
        <>
          <div className="sheet-grabber" />
          <div className="sheet-bar">
            <div>{cancelLabel !== null && <button type="button" className="bar-button" onClick={onClose}>{cancelLabel}</button>}</div>
            <div className="title">{title}</div>
            <div>
              {action && (
                <button type="button" className="bar-button strong" onClick={action.onClick}
                  disabled={action.disabled || action.busy}>
                  {action.busy ? "…" : action.label}
                </button>
              )}
            </div>
          </div>
          <div className="sheet-body">{children}</div>
        </>
      )}
    </dialog>
  );
}
