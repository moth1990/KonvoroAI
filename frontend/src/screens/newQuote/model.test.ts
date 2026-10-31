import { describe, expect, it } from "vitest";

import type { Progress } from "../../api/client";
import {
  applyServerCheck,
  clientCheck,
  MESSAGES,
  sizeText,
  stageCounter,
  stageRows,
  startState,
  type PickedFile,
} from "./model";

const MB = 1024 * 1024;

function picked(name: string, error: PickedFile["error"] = null): PickedFile {
  return { key: name, file: new File([new Uint8Array(1)], name), error };
}

describe("clientCheck (mirrors the server: type, then size)", () => {
  it.each(["MAIN_BOARD.dwg", "x.DXF"])("%s is a CAD file", (name) => {
    expect(clientCheck({ name, size: 10 })).toEqual({ code: "cad_not_supported", message: MESSAGES.cad_not_supported });
  });

  it.each(["notes.docx", "noextension", "archive.rar"])("%s is not supported", (name) => {
    expect(clientCheck({ name, size: 10 })?.code).toBe("unsupported_format");
  });

  it("over 20 MB is too large, with the file's name", () => {
    expect(clientCheck({ name: "scan_site.pdf", size: 20 * MB + 1 })).toEqual({
      code: "too_large",
      message: "הקובץ scan_site.pdf גדול מ-20MB. אפשר לייצא אותו מחדש בלי תמונות ברזולוציה גבוהה, או לפצל אותו.",
    });
    expect(clientCheck({ name: "ok.pdf", size: 20 * MB })).toBeNull();
  });

  it.each(["a.pdf", "b.PNG", "c.jpeg", "d.webp", "e.heic", "f.xlsx", "g.csv", "h.zip"])("%s is fine", (name) => {
    expect(clientCheck({ name, size: 10 })).toBeNull();
  });
});

describe("applyServerCheck", () => {
  it("takes the server's errors and page counts, file by file", () => {
    const files = [picked("NURSERY-1.pdf"), picked("plan.pdf")];
    const out = applyServerCheck(files, [
      { name: "NURSERY-1.pdf", size_bytes: 1, detected_format: "pdf", page_count: 9, error: null, message: null },
      {
        name: "plan.pdf",
        size_bytes: 1,
        detected_format: "dwg",
        page_count: null,
        error: "cad_not_supported",
        message: "CAD",
      },
    ]);
    expect(out.map((f) => [f.pages, f.error?.code ?? null])).toEqual([
      [9, null],
      [null, "cad_not_supported"],
    ]);
  });

  it("a ZIP's files count toward the ZIP, and one bad file inside marks it", () => {
    const out = applyServerCheck(
      [picked("d.zip")],
      [
        { name: "d.zip/a.pdf", size_bytes: 1, detected_format: "pdf", page_count: 2, error: null, message: null },
        {
          name: "d.zip/b.dwg",
          size_bytes: 1,
          detected_format: null,
          page_count: null,
          error: "cad_not_supported",
          message: "CAD",
        },
      ],
    );
    expect([out[0]?.pages, out[0]?.error?.code]).toEqual([2, "cad_not_supported"]);
  });
});

describe("startState (01 §4.6 item 4)", () => {
  const base = { revision: false, revisionOf: "", remaining: 38, busy: false };

  it("counts once, only if intake succeeds", () => {
    expect(startState({ ...base, files: [picked("a.pdf")] })).toEqual({
      text: "קובץ אחד · ייספר 1 מהמכסה (נותרו 38) רק אם הקליטה מצליחה",
      isError: false,
      canStart: true,
    });
    expect(startState({ ...base, files: [picked("a.pdf"), picked("b.pdf")] }).text).toMatch(/^2 קבצים/);
  });

  it("a rejected file blocks the start and says why", () => {
    const bad = picked("x.dwg", { code: "cad_not_supported", message: "" });
    expect(startState({ ...base, files: [picked("a.pdf"), bad] })).toEqual({
      text: "קובץ אחד חורג. הסירו אותו או החליפו, כדי שלא יחסר לוח בהצעה.",
      isError: true,
      canStart: false,
    });
    expect(startState({ ...base, files: [bad, bad] }).text).toMatch(/^2 קבצים חורגים. הסירו אותם/);
  });

  it("a new version needs the earlier quote, and never counts", () => {
    const files = [picked("a.pdf")];
    expect(startState({ ...base, files, revision: true }).canStart).toBe(false);
    expect(startState({ ...base, files, revision: true, revisionOf: "drw_1", remaining: 0 })).toEqual({
      text: "קובץ אחד · גרסה חדשה, לא נספרת במכסה",
      isError: false,
      canStart: true,
    });
  });

  it("a full quota blocks a new quote, not a new version", () => {
    expect(startState({ ...base, files: [picked("a.pdf")], remaining: 0 }).canStart).toBe(false);
  });

  it("an unlimited plan shows no remaining count", () => {
    expect(startState({ ...base, files: [picked("a.pdf")], remaining: null }).text).toBe(
      "קובץ אחד · ייספר 1 מהמכסה רק אם הקליטה מצליחה",
    );
  });

  it("no double start while uploading", () => {
    expect(startState({ ...base, files: [picked("a.pdf")], busy: true }).canStart).toBe(false);
  });
});

function progress(statuses: string[], status = "processing"): Progress {
  return {
    drawing_id: "drw_1",
    name: "x",
    status: status as Progress["status"],
    current_stage: null,
    progress: 0,
    counted_as: "new_drawing",
    counted: false,
    files: [],
    stages: statuses.map((s, i) => ({ stage: i + 1, name: `s${i + 1}`, status: s as never, summary: null })),
    quote_id: null,
    pages: [],
  };
}

describe("stageRows", () => {
  it("done, the one being worked on, and the ones waiting", () => {
    const p = progress(["done", "done", "queued", "queued", "queued", "queued", "queued"]);
    expect(stageRows(p).map((r) => r.state)).toEqual(["done", "done", "run", "wait", "wait", "wait", "wait"]);
    expect(stageCounter(p)).toBe(3);
  });

  it("a fresh upload already shows stage 1 working", () => {
    const p = progress(Array(7).fill("queued"), "uploaded");
    expect(stageRows(p)[0]?.state).toBe("run");
  });

  it("nothing works once the run stopped", () => {
    const p = progress(["done", "failed", "queued", "queued", "queued", "queued", "queued"], "failed");
    expect(
      stageRows(p)
        .map((r) => r.state)
        .slice(0, 3),
    ).toEqual(["done", "failed", "wait"]);
  });

  it("the counter stops at 7", () => {
    expect(stageCounter(progress(Array(7).fill("done"), "ready"))).toBe(7);
  });
});

describe("sizeText", () => {
  it("one decimal, like the prototype", () => {
    expect([sizeText(0.8 * MB), sizeText(2 * MB), sizeText(10)]).toEqual(["0.8MB", "2MB", "0.1MB"]);
  });
});
