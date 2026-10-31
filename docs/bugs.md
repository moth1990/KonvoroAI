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
| | | | | | |
