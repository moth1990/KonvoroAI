# Bug log

Every bug found during development goes here, including bugs fixed in the same session. Severities and the fix policy are in [dev-strategy.md §7](dev-strategy.md#7-definition-of-done-bugs-gates):

| Severity | Meaning | Fix by |
| --- | --- | --- |
| P0 | Cross-tenant leak, wrong money, a value made up without evidence, data loss, a broken main flow | Now, in the current session |
| P1 | A feature in scope doesn't work, or fidelity is badly off | The phase gate |
| P2 | Minor functional or visual deviation | The gate, or scheduled later |
| P3 | Cosmetic, or an idea | Backlog |

**How to add a bug:**
- Use the next free id.
- Write the repro as steps someone can follow.
- Link the failing test once one exists.
- When it is fixed, set the status to `fixed` and fill in "Fixed in" with the session and PR.

## Open

| ID | Found in | Sev | Area | Summary | Repro | Status | Fixed in |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

## Closed

| ID | Found in | Sev | Area | Summary | Fixed in |
| --- | --- | --- | --- | --- | --- |
| BUG-001 | S01 | P1 | CI / licenses | The npm license gate never ran. The script was named `licenses`, and `pnpm licenses` is a built-in pnpm command that shadows it: it printed a usage error and exited 1. The script is now `license-check`, called with `pnpm run`. A probe with an AGPL package now fails as it should | S01 |
| BUG-002 | S04 | P2 | Frontend / theme | Body text rendered at 16px instead of the prototype's 14px: MUI's CssBaseline gives `<body>` the theme's `body1` (1rem), which overrode `base.css`. The theme now sets `body1` to 14px / 1.5, and `e2e/smoke.spec.ts` checks the computed size. Found in the fidelity review | S04 |
| BUG-003 | S04 | P3 | Login (prototype) | The password placeholder runs under the "הצג" button: the input is LTR, so its text starts on the button's side. Fixed in the app (`.pw .input` keeps room); the prototype file is unchanged | S04 |
