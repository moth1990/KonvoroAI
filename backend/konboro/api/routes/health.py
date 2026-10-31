"""Liveness for the load balancer. Public, touches no tenant data."""

from fastapi import APIRouter

from ..schemas import HealthOut

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> HealthOut:
    return HealthOut()
