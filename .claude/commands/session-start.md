---
description: Start the next Konboro development session (or the one given as an argument, e.g. S05)
argument-hint: "[SNN]"
---

Start a development session for Konboro. Follow CLAUDE.md and docs/dev-strategy.md.

1. **Pick the session.** If `$ARGUMENTS` names one (e.g. `S05`), use it. Otherwise read `docs/roadmap.md` and take the first session with status `todo` whose dependencies are all `done`. A session marked `blocked`, or one with an unfinished dependency, cannot start. If that is the only kind left, explain why and stop.
2. **Check the ground.**
   - `git status` must be clean. Bring `main` up to date and branch from it.
   - Check that the previous session's PR is merged. If it is not, tell the user and ask whether to continue.
   - Check `docs/bugs.md` for open P0 bugs. If there are any, they come first: say so and ask.
3. **Session file.** Open `docs/sessions/SNN-*.md`. If it doesn't exist, create it from `docs/sessions/_template.md`, filled in from the roadmap row: goal, specs, prototype lines, depends on. Then write concrete tasks for every layer: backend, frontend, unit, integration, Playwright, eval, docs.
4. **Read the references.** Read every spec section the session file cites, and the cited prototype line ranges in `prototype/konboro-app.html`. Read the relevant golden labels for pipeline sessions. Check the "Known spec inconsistencies" list in CLAUDE.md for any that this session touches.
5. **Branch.** `git checkout -b sNN-short-slug`, using the branch name from the session file. Set the session status to `in progress` in the session file and in `docs/roadmap.md`.
6. **Ask before building.** List the session file's open questions, plus any spec-vs-prototype conflicts you found, and ask the user. Record the answers in the session file under "Decisions made".
7. **Propose the plan.** Give the ordered task list, saying which tests prove each task, and wait for the user's go-ahead before writing code.
