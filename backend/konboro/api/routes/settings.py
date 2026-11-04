"""Tenant preferences for the settings screen (10 §9.1, prototype vPrefs). Flags are read-only (S03 decision)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from konboro.db.models import AttributeSchema, TenantSettings
from konboro.domain.permissions import Permission
from konboro.services import onboarding

from ..deps import Actor, require
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import SettingsOut, SettingsPatch

router = APIRouter(prefix="/settings", tags=["settings"], responses=ERROR_RESPONSES)

# Current and poles never get a default (05 §4.4, CLAUDE.md non-negotiable 4).
NEVER_DEFAULT = frozenset({"current_a", "poles"})


def settings_out(actor: Actor, row: TenantSettings) -> SettingsOut:
    fields = {k: getattr(row, k) for k in SettingsOut.model_fields if k != "default_markup"}
    return SettingsOut.model_validate(
        {**fields, "default_markup": onboarding.default_markup(actor.session, actor.tenant_id)}
    )


def settings_row(actor: Actor) -> TenantSettings:
    row = actor.session.get(TenantSettings, actor.tenant_id)
    if row is None:
        row = TenantSettings(tenant_id=actor.tenant_id)
        actor.session.add(row)
        actor.session.flush()
        actor.session.refresh(row)
    return row


def check_attribute_defaults(actor: Actor, defaults: dict[str, dict[str, Any]]) -> None:
    """Only attributes whose schema allows a default may have one (05 §4.4). current_a and poles never."""
    schemas = {s.family: s for s in actor.session.scalars(select(AttributeSchema)).all()}
    bad: list[dict[str, Any]] = []
    for family, attributes in defaults.items():
        schema = schemas.get(family)
        # No schema yet for the family (schemas arrive with the catalog sessions): only the never-default rule.
        allowed = {a["name"] for a in schema.attributes if a.get("default_allowed")} if schema else None
        for name in attributes:
            if name in NEVER_DEFAULT or (allowed is not None and name not in allowed):
                bad.append({"loc": ["body", "attribute_defaults", family, name], "type": "default_not_allowed"})
    if bad:
        raise ApiError(422, "validation_error", bad)


@router.get("")
def get_settings(actor: Annotated[Actor, Depends(require(Permission.SETTINGS_READ))]) -> SettingsOut:
    return settings_out(actor, settings_row(actor))


@router.patch("")
def patch_settings(
    body: SettingsPatch, actor: Annotated[Actor, Depends(require(Permission.SETTINGS_WRITE))]
) -> SettingsOut:
    changes = body.model_dump(exclude_unset=True)
    if changes.get("attribute_defaults"):
        check_attribute_defaults(actor, changes["attribute_defaults"])
    row = settings_row(actor)
    if "default_markup" in changes:  # the `default` margin rule, as the onboarding question sets it (07 §7.3)
        changes.pop("default_markup")
        assert body.default_markup is not None  # noqa: S101  (the patch refuses null for it)
        onboarding.set_default_markup(actor.session, actor.tenant_id, actor.user_id, body.default_markup)
    for name, value in changes.items():
        setattr(row, name, value)
    actor.session.flush()
    actor.session.refresh(row)
    return settings_out(actor, row)
