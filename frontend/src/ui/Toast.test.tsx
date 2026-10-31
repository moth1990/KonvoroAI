import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TOAST_MS, ToastProvider, useToast } from "./Toast";

function Trigger({ text, onUndo }: { text: string; onUndo?: () => void }) {
  const toast = useToast();
  return <button onClick={() => toast(text, onUndo ? { onUndo } : undefined)}>{`show ${text}`}</button>;
}

describe("Toast", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("is a status message that hides after 4.2 s", () => {
    render(
      <ToastProvider>
        <Trigger text="נשמר" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("show נשמר"));
    expect(screen.getByRole("status")).toHaveProperty("textContent", "נשמר");
    act(() => vi.advanceTimersByTime(TOAST_MS - 1));
    expect(screen.queryByRole("status")).not.toBeNull();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByRole("status")).toBeNull();
    expect(TOAST_MS).toBe(4200);
  });

  it("a new toast replaces the current one and restarts the timer", () => {
    render(
      <ToastProvider>
        <Trigger text="א" />
        <Trigger text="ב" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("show א"));
    act(() => vi.advanceTimersByTime(3000));
    fireEvent.click(screen.getByText("show ב"));
    expect(screen.getAllByRole("status")).toHaveLength(1);
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByRole("status").textContent).toBe("ב");
    act(() => vi.advanceTimersByTime(1200));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("undo runs the callback and closes the toast", () => {
    const undo = vi.fn();
    render(
      <ToastProvider>
        <Trigger text="נמחק" onUndo={undo} />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("show נמחק"));
    fireEvent.click(screen.getByRole("button", { name: "בטל" }));
    expect(undo).toHaveBeenCalledOnce();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("no undo button without a callback", () => {
    render(
      <ToastProvider>
        <Trigger text="נשמר" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("show נשמר"));
    expect(screen.queryByRole("button", { name: "בטל" })).toBeNull();
  });
});
