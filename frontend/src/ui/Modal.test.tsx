import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { Modal } from "./Modal";

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>פתח</button>
      {open && (
        <Modal onClose={() => setOpen(false)} labelledBy="m-title">
          <h2 id="m-title">אישור</h2>
          <button>ביטול</button>
          <button className="primary">אישור ושליחה</button>
        </Modal>
      )}
    </>
  );
}

function open() {
  render(<Harness />);
  const opener = screen.getByRole("button", { name: "פתח" });
  opener.focus();
  fireEvent.click(opener);
  return opener;
}

describe("Modal", () => {
  afterEach(cleanup);

  it("is a labelled modal dialog that focuses its primary button", () => {
    open();
    const dialog = screen.getByRole("dialog", { name: "אישור" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "אישור ושליחה" }));
  });

  it("Esc closes it and gives focus back to the opener", () => {
    const opener = open();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("a click on the backdrop closes it; a click inside does not", () => {
    open();
    fireEvent.mouseDown(screen.getByRole("dialog"));
    expect(screen.queryByRole("dialog")).not.toBeNull();
    fireEvent.mouseDown(screen.getByTestId("modal-bg"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Tab stays inside, both ways", () => {
    open();
    const [first, last] = [
      screen.getByRole("button", { name: "ביטול" }),
      screen.getByRole("button", { name: "אישור ושליחה" }),
    ];
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });
});
