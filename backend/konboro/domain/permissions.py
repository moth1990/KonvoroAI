"""Permissions (00 §14.1). v1.0 has one user per tenant with the `owner` role, but every endpoint still
checks a permission, so adding roles later changes this table and nothing else.
"""

from enum import StrEnum


class Permission(StrEnum):
    ACCOUNT_READ = "account.read"
    QUOTA_READ = "quota.read"
    QUOTES_READ = "quotes.read"
    DRAWINGS_READ = "drawings.read"
    DRAWINGS_WRITE = "drawings.write"
    SETTINGS_READ = "settings.read"
    SETTINGS_WRITE = "settings.write"


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "owner": frozenset(Permission),
}


def allowed(role: str, permission: Permission) -> bool:
    """An unknown role has no permissions."""
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
