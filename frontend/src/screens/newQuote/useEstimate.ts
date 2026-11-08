import { useEffect, useRef, useState } from "react";

import { checkFiles, type Estimate } from "../../api/client";
import { shownEstimate } from "./live";
import { applyServerCheck, type PickedFile } from "./model";

/**
 * The start bar's estimate (01 §4.6 item 4, `live_run`; S28c decision 1): each time the picked files change, the
 * server counts their pages and checks them without storing anything, and its answer replaces the browser's
 * check, as the upload's would. Shown only when every valid file's pages are known. A failed check leaves the start
 * bar as it was: the estimate is a help, never a gate.
 */
export function useStartEstimate(
  files: PickedFile[],
  setFiles: (files: PickedFile[]) => void,
  on: boolean,
  purpose: "quote" | "audit" = "quote",
): Estimate | null {
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const checked = useRef("");
  const picked = files.map((f) => f.key).join(",");
  useEffect(() => {
    if (!on || checked.current === picked) return;
    checked.current = picked;
    const sent = files.filter((f) => !f.error);
    if (!sent.length) return;
    checkFiles(
      sent.map((f) => f.file),
      purpose,
    )
      .then((answer) => {
        if (checked.current !== picked) return; // the files changed since: a newer check is on its way
        setFiles(applyServerCheck(files, answer.files));
        setEstimate(answer.estimate ?? null);
      })
      .catch(() => undefined);
  }, [on, picked, files, setFiles, purpose]);
  return on ? shownEstimate(files, estimate) : null;
}
