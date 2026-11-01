import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, UNDO_TOAST_MS } from "../../ui/Toast";
import { isUndoKey, resetUndoStacksForTests, UNDO_LIMIT, UndoStack, undoStackFor, useUndo } from "./undo";

describe("the undo stack (09 §7.11)", () => {
  it("takes back the newest first", () => {
    const stack = new UndoStack();
    const done: string[] = [];
    for (const label of ["א", "ב", "ג"]) stack.push({ label, undo: () => void done.push(label) });
    void stack.pop()?.undo();
    void stack.pop()?.undo();
    expect(done).toEqual(["ג", "ב"]);
    expect(stack.labels()).toEqual(["א"]);
  });

  it("keeps the last 30 actions", () => {
    const stack = new UndoStack();
    for (let i = 1; i <= 35; i++) stack.push({ label: String(i), undo: () => {} });
    expect(UNDO_LIMIT).toBe(30);
    expect(stack.size).toBe(30);
    expect(stack.labels()[0]).toBe("6");
    expect(stack.labels().at(-1)).toBe("35");
  });

  it("an empty stack pops nothing; clearing empties it (after sending)", () => {
    const stack = new UndoStack();
    expect(stack.pop()).toBeUndefined();
    stack.push({ label: "א", undo: () => {} });
    stack.clear();
    expect(stack.size).toBe(0);
  });

  it("is one stack per quote", () => {
    resetUndoStacksForTests();
    undoStackFor("quo_1").push({ label: "א", undo: () => {} });
    expect(undoStackFor("quo_1").size).toBe(1);
    expect(undoStackFor("quo_2").size).toBe(0);
  });

  it("Ctrl+Z or ⌘Z by key position, so a Hebrew layout works", () => {
    const key = { code: "KeyZ", ctrlKey: true, metaKey: false, shiftKey: false, altKey: false };
    expect(isUndoKey(key)).toBe(true);
    expect(isUndoKey({ ...key, ctrlKey: false, metaKey: true })).toBe(true);
    expect(isUndoKey({ ...key, ctrlKey: false })).toBe(false);
    expect(isUndoKey({ ...key, shiftKey: true })).toBe(false); // redo, not undo
    expect(isUndoKey({ ...key, code: "KeyX" })).toBe(false);
  });
});

function Harness({ onUndo }: { onUndo: () => void }) {
  const undo = useUndo("quo_harness");
  return (
    <>
      <button onClick={() => undo.record({ label: "אושר: F1", undo: onUndo })}>act</button>
      <button disabled={!undo.canUndo} onClick={() => void undo.undo()}>
        undo-last
      </button>
    </>
  );
}

describe("useUndo", () => {
  beforeEach(() => {
    resetUndoStacksForTests();
    vi.useFakeTimers();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  const mount = (onUndo = vi.fn()) => {
    render(
      <ToastProvider>
        <Harness onUndo={onUndo} />
      </ToastProvider>,
    );
    return onUndo;
  };

  it("an action shows a 5 s toast with בטל, which takes it back", async () => {
    const onUndo = mount();
    expect(screen.getByText("undo-last")).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByText("act"));
    expect(screen.getByRole("status").textContent).toContain("אושר: F1");
    expect(screen.getByText("undo-last")).toHaveProperty("disabled", false);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "בטל" })));
    expect(onUndo).toHaveBeenCalledOnce();
    expect(screen.getByRole("status").textContent).toBe("בוטל: אושר: F1");
    expect(screen.getByText("undo-last")).toHaveProperty("disabled", true);
  });

  it("the toast's offer ends after 5 s; the header's undo still works", async () => {
    const onUndo = mount();
    fireEvent.click(screen.getByText("act"));
    act(() => vi.advanceTimersByTime(UNDO_TOAST_MS));
    expect(screen.queryByRole("status")).toBeNull();
    await act(async () => fireEvent.click(screen.getByText("undo-last")));
    expect(onUndo).toHaveBeenCalledOnce();
  });
});
