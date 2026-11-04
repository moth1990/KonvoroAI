"""The pilot approval queue (00 §14.2, prototype `vQueue`), behind `approval_queue`.

Only an explicit approval here promotes a candidate to the shared layer, through `konboro_promote` (S24 decision 4).
A rejection keeps it with the factory. Either decision is final: a decided candidate answers 409.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from konboro.domain.permissions import Permission
from konboro.services import knowledge as kn

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import CandidateList, CandidateOut, RejectIn

router = APIRouter(
    prefix="/knowledge-candidates",
    tags=["knowledge"],
    responses=ERROR_RESPONSES,
    dependencies=[Depends(require_flag(kn.FLAG))],
)

Reader = Annotated[Actor, Depends(require(Permission.KNOWLEDGE_READ))]
Decider = Annotated[Actor, Depends(require(Permission.KNOWLEDGE_DECIDE))]
CandidateId = Annotated[str, Path(pattern=r"^kc_[0-9A-Z]{26}$")]


def candidate_out(v: kn.CandidateView) -> CandidateOut:
    return CandidateOut.model_validate(v, from_attributes=True)


@router.get("")
def list_candidates(actor: Reader) -> CandidateList:
    """Pending first, oldest first; then the decided ones, newest decision first."""
    items = [candidate_out(v) for v in kn.list_candidates(actor.session, actor.tenant_id)]
    return CandidateList(items=items, pending=sum(i.status == "pending" for i in items))


@router.post("/{candidate_id}/approve")
def approve(candidate_id: CandidateId, actor: Decider) -> CandidateOut:
    try:
        return candidate_out(kn.approve(actor.session, actor.tenant_id, actor.user_id, candidate_id))
    except kn.KnowledgeError as e:
        raise ApiError(e.status, e.code) from e


@router.post("/{candidate_id}/reject")
def reject(candidate_id: CandidateId, body: RejectIn, actor: Decider) -> CandidateOut:
    try:
        return candidate_out(kn.reject(actor.session, actor.tenant_id, actor.user_id, candidate_id, body.reason))
    except kn.KnowledgeError as e:
        raise ApiError(e.status, e.code) from e
