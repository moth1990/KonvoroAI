"""Permissions (00 §14.1). v1.0 has one user per tenant with the `owner` role, but every endpoint still
checks a permission, so adding roles later changes this table and nothing else.
"""

from enum import StrEnum


class Permission(StrEnum):
    ACCOUNT_READ = "account.read"
    QUOTA_READ = "quota.read"
    QUOTES_READ = "quotes.read"
    QUOTES_WRITE = "quotes.write"
    DRAWINGS_READ = "drawings.read"
    DRAWINGS_WRITE = "drawings.write"
    SETTINGS_READ = "settings.read"
    SETTINGS_WRITE = "settings.write"
    PRICE_LIST_READ = "price_list.read"
    PRICE_LIST_WRITE = "price_list.write"
    COSTS_READ = "costs.read"  # 09 §12: costs and margins; without it the server sends none
    QUOTES_SEND = "quotes.send"  # 09 §12: send to the customer, open a new version
    KNOWLEDGE_READ = "knowledge.read"  # the approval queue (00 §14.2)
    KNOWLEDGE_DECIDE = "knowledge.decide"  # approve a candidate for the shared layer, or reject it


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "owner": frozenset(Permission),
}


def allowed(role: str, permission: Permission) -> bool:
    """An unknown role has no permissions."""
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
