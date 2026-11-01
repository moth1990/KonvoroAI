/**
 * Undo on the review screen (09 §7.11, prototype `pushUndo` / `doUndo`; S11 decision 3).
 *
 * Every action but sending pushes an entry: what it was, and how to take it back. The stack keeps the last 30 per
 * quote, across lines, pages and chat. After an action the toast offers "בטל" for 5 s; Ctrl+Z (⌘Z) and the header's
 * button take back the latest. S11 builds the stack; S23's actions push onto it, and their `undo` asks the server to
 * revert what the action changed (rows, instances, dismissed findings, page kinds).
 */
import { useCallback, useSyncExternalStore } from "react";

import { useToast } from "../../ui/Toast";

export const UNDO_LIMIT = 30;

export interface UndoEntry {
  /** What the toast says: "אושר: מא"ז 16A" → "בוטל: אושר: מא"ז 16A". */
  label: string;
  undo: () => void | Promise<void>;
}

export class UndoStack {
  private entries: UndoEntry[] = [];
  private listeners = new Set<() => void>();

  get size(): number {
    return this.entries.length;
  }

  /** The newest last; past the limit the oldest is dropped. */
  push(entry: UndoEntry): void {
    this.entries = [...this.entries, entry].slice(-UNDO_LIMIT);
    this.emit();
  }

  pop(): UndoEntry | undefined {
    const entry = this.entries.at(-1);
    if (entry) {
      this.entries = this.entries.slice(0, -1);
      this.emit();
    }
    return entry;
  }

  /** After sending, nothing before it can be undone (09 §7.11). */
  clear(): void {
    if (!this.entries.length) return;
    this.entries = [];
    this.emit();
  }

  labels(): string[] {
    return this.entries.map((e) => e.label);
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    for (const l of this.listeners) l();
  }
}

// One stack per quote for the life of the page, so leaving the quote and coming back keeps it.
const stacks = new Map<string, UndoStack>();

export function undoStackFor(quoteId: string): UndoStack {
  let stack = stacks.get(quoteId);
  if (!stack) {
    stack = new UndoStack();
    stacks.set(quoteId, stack);
  }
  return stack;
}

export function resetUndoStacksForTests(): void {
  stacks.clear();
}

/** The keyboard's undo, by key position like 09 §8's `/`, so it works on a Hebrew layout too. */
export function isUndoKey(e: Pick<KeyboardEvent, "code" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey">): boolean {
  return e.code === "KeyZ" && (e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey;
}

export interface Undo {
  canUndo: boolean;
  /** Record an action: it goes on the stack and the toast offers "בטל". */
  record: (entry: UndoEntry) => void;
  /** Take back the newest action; says so in a toast, or that there is nothing to undo. */
  undo: () => Promise<void>;
}

export function useUndo(quoteId: string): Undo {
  const stack = undoStackFor(quoteId);
  const toast = useToast();
  const size = useSyncExternalStore(
    (cb) => stack.subscribe(cb),
    () => stack.size,
  );

  const undo = useCallback(async () => {
    const entry = stack.pop();
    if (!entry) {
      toast("אין מה לבטל");
      return;
    }
    await entry.undo();
    toast(`בוטל: ${entry.label}`);
  }, [stack, toast]);

  const record = useCallback(
    (entry: UndoEntry) => {
      stack.push(entry);
      toast(entry.label, { onUndo: () => void undo() });
    },
    [stack, toast, undo],
  );

  return { canUndo: size > 0, record, undo };
}
