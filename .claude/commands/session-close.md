---
description: Close the current Konboro development session — verify, document, commit, open the PR
---

Close the current development session. The session id comes from the current branch name (`sNN-…`). Follow the definition of done in docs/dev-strategy.md §7.

1. **Verify.**
   - Run `make check`. If anything fails, fix it, or stop and report it. Never skip a failing check.
   - Run the Playwright suites that cover screens this session touched, on both projects.
   - For a UI session, regenerate the prototype-fidelity report and ask the user to review it. Do not mark the session done until they have.
   - For a pipeline session, run `make eval` and compare against the baseline.
2. **Check the scope.** Compare the session file's tasks and acceptance criteria with the diff (`git diff main...HEAD --stat`).
   - Tick the items that are really done.
   - For anything left undone, say so plainly in the session file. Either move it to a named later session in `docs/roadmap.md`, or log it in `docs/bugs.md`.
3. **Document.**
   - Fill in the session file's "Outcome": done, decisions (who decided and why), eval numbers, bugs logged, follow-ups.
   - Update `docs/bugs.md` with every bug found or fixed in this session.
   - Set the roadmap status to `in review`.
   - If a command, rule or layout changed, update CLAUDE.md and docs/dev-strategy.md.
   - If a spec inconsistency was resolved, fix the spec and remove it from the CLAUDE.md list.
4. **Commit and PR.**
   - Commit with a message that starts `SNN: `.
   - Push the branch.
   - Open a PR into `main` with: the goal, a summary of the changes, spec references, test evidence (which suites ran and the eval deltas), the open bugs, and a link to the session file.
   - Report the PR link and the CI status to the user. The user merges.
