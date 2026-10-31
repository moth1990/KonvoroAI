"""License gate for Python dependencies (specs/12-tech-stack.md §8): no GPL or AGPL in a closed SaaS product.

LGPL is allowed (psycopg is LGPL-3.0): we link to it as a library and never ship a modified copy.
Run with `python -m konboro.licenses`; exits non-zero and names the offenders.
"""

import json
import re
import subprocess
import sys

# Our own package has no license metadata.
OWN_PACKAGES = {"konboro"}

_LGPL = re.compile(r"\bLGPL|Lesser General Public", re.IGNORECASE)
_GPL = re.compile(r"\b(A?GPL)|General Public License", re.IGNORECASE)


def is_forbidden(license_text: str) -> bool:
    """True for GPL or AGPL in any spelling; False for LGPL and everything else.

    A dual license ("MIT OR GPL-3.0") is allowed when one of its options is permissive,
    so each OR / ";" alternative is judged on its own.
    """
    options = re.split(r"\s+OR\s+|;", license_text)
    return all(_GPL.search(opt) and not _LGPL.search(opt) for opt in options if opt.strip())


def forbidden_packages(packages: list[dict[str, str]]) -> list[str]:
    return [
        f"{p['Name']} {p['Version']}: {p['License']}"
        for p in packages
        if p["Name"] not in OWN_PACKAGES and is_forbidden(p["License"])
    ]


def main() -> int:
    out = subprocess.run(
        [sys.executable, "-m", "piplicenses", "--from=mixed", "--format=json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    bad = forbidden_packages(json.loads(out))
    for line in bad:
        print(f"forbidden license: {line}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
