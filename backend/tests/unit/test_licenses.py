import pytest

from konboro.licenses import forbidden_packages, is_forbidden


@pytest.mark.parametrize(
    "text",
    [
        "GNU Affero General Public License v3",
        "AGPL-3.0-only",
        "GPL-3.0-or-later",
        "GNU General Public License v2 (GPLv2)",
        "GPLv3",
    ],
)
def test_gpl_and_agpl_are_forbidden(text: str) -> None:
    assert is_forbidden(text)


@pytest.mark.parametrize(
    "text",
    [
        "LGPL-3.0-only",  # psycopg
        "GNU Lesser General Public License v3 (LGPLv3)",
        "MIT",
        "Apache-2.0 OR BSD-2-Clause",
        "MIT OR GPL-3.0",  # dual license: we take the MIT option
        "Mozilla Public License 2.0 (MPL 2.0)",
        "UNKNOWN",
    ],
)
def test_lgpl_permissive_and_dual_licenses_are_allowed(text: str) -> None:
    assert not is_forbidden(text)


def test_reports_offenders_and_skips_our_own_package() -> None:
    packages = [
        {"Name": "pymupdf", "Version": "1.24.0", "License": "GNU Affero General Public License v3"},
        {"Name": "psycopg", "Version": "3.3.6", "License": "LGPL-3.0-only"},
        {"Name": "konboro", "Version": "0.1.0", "License": "UNKNOWN"},
    ]
    assert forbidden_packages(packages) == ["pymupdf 1.24.0: GNU Affero General Public License v3"]
