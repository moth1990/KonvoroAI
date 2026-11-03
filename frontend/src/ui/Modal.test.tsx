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

describe("a dialog over another (S23b: the picker over the phone's sheet)", () => {
  afterEach(cleanup);

  function Stack() {
    const [outer, setOuter] = useState(true);
    const [inner, setInner] = useState(false);
    return outer ? (
      <Modal onClose={() => setOuter(false)} labelledBy="o-title">
        <h2 id="o-title">גיליון</h2>
        <button onClick={() => setInner(true)}>מוצר אחר…</button>
        {inner ? (
          <Modal onClose={() => setInner(false)} labelledBy="i-title">
            <h2 id="i-title">בחירת מוצר</h2>
            <input aria-label="חיפוש" />
          </Modal>
        ) : null}
      </Modal>
    ) : null;
  }

  it("Esc closes the top one only, then the one under it", () => {
    render(<Stack />);
    fireEvent.click(screen.getByRole("button", { name: "מוצר אחר…" })); // opened from the sheet, as in the app
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "בחירת מוצר" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "גיליון" })).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "גיליון" })).toBeNull();
  });
});
