"""A new factory's two questions and the data terms (10 §5.1, S24 decision 1), behind `onboarding`.

`GET` tells the app whether /welcome comes first; `POST` answers both questions and accepts the terms in one step.
Until then, `POST /drawings` and `POST /audits` answer 409 `data_terms_required`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from konboro.domain.permissions import Permission
from konboro.services import onboarding as ob

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import OnboardingIn, OnboardingOut

router = APIRouter(
    prefix="/onboarding", tags=["onboarding"], responses=ERROR_RESPONSES, dependencies=[Depends(require_flag(ob.FLAG))]
)


def onboarding_out(state: ob.OnboardingState) -> OnboardingOut:
    return OnboardingOut.model_validate(state, from_attributes=True)


@router.get("")
def get_onboarding(actor: Annotated[Actor, Depends(require(Permission.SETTINGS_READ))]) -> OnboardingOut:
    return onboarding_out(ob.state(actor.session, actor.tenant_id))


@router.post("")
def answer_onboarding(
    body: OnboardingIn, actor: Annotated[Actor, Depends(require(Permission.SETTINGS_WRITE))]
) -> OnboardingOut:
    try:
        state = ob.answer(
            actor.session,
            actor.tenant_id,
            actor.user_id,
            markup=body.markup,
            brands={str(family): brand for family, brand in body.brands.items()},
            accept_terms=body.accept_terms,
        )
    except ob.OnboardingError as e:
        details = [{"loc": ["body", *e.field.split(".")], "type": e.code}] if e.field else None
        raise ApiError(e.status, "validation_error", details) from e
    return onboarding_out(state)
