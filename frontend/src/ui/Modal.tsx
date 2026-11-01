import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * A dialog (prototype `modal()`, lines 637–644): closes on Esc or a click on the backdrop, keeps Tab inside,
 * focuses the primary button or the first input when it opens, and gives focus back when it closes.
 */
export function Modal({
  onClose,
  labelledBy,
  className = "",
  backdropClassName = "",
  children,
}: {
  onClose: () => void;
  labelledBy: string;
  className?: string;
  /** `sheet-bg` turns the dialog into the phone's bottom sheet (09 §5.2). */
  backdropClassName?: string;
  children: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  useLayoutEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const el = box.current;
    const first = el?.querySelector<HTMLElement>("button.primary, input") ?? el?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? el)?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        close.current();
        return;
      }
      if (e.key !== "Tab" || !el) return;
      const items = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const [head, tail] = [items[0], items[items.length - 1]];
      if (e.shiftKey && document.activeElement === head) {
        e.preventDefault();
        tail?.focus();
      } else if (!e.shiftKey && document.activeElement === tail) {
        e.preventDefault();
        head?.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, []);

  return createPortal(
    <div
      className={`modal-bg ${backdropClassName}`.trim()}
      data-testid="modal-bg"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close.current();
      }}
    >
      <div
        ref={box}
        className={`modal ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
