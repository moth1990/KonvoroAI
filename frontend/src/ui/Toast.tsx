import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

/** How long a toast stays up (prototype `toast()`, line 628). */
export const TOAST_MS = 4200;

interface ToastState {
  id: number;
  text: string;
  onUndo?: () => void;
}

type ShowToast = (text: string, options?: { onUndo?: () => void }) => void;

const ToastContext = createContext<ShowToast | null>(null);

/** One toast at a time: a new one replaces the current one and restarts the timer. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const next = useRef(0);

  const show = useCallback<ShowToast>((text, options) => {
    next.current += 1;
    setToast({ id: next.current, text, onUndo: options?.onUndo });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), TOAST_MS);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const value = useMemo(() => show, [show]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      {toast && (
        <div className="toast" role="status" data-testid="toast" key={toast.id}>
          <span>{toast.text}</span>
          {toast.onUndo && (
            <button
              type="button"
              data-testid="undo"
              onClick={() => {
                toast.onUndo?.();
                setToast(null);
              }}
            >
              בטל
            </button>
          )}
        </div>
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ShowToast {
  const show = useContext(ToastContext);
  if (!show) throw new Error("useToast outside ToastProvider");
  return show;
}
