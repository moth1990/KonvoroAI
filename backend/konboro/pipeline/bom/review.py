"""The user's side of a BOM table (01 §5.8, S14 decision 1): when its column mapping stops the drawing, and what a
mapping needs before decoding goes on. Behind `bom_column_mapping` (13): with the flag off nothing stops, and stage 4
keeps the rows of an unsure mapping yellow."""

from collections.abc import Iterable

from sqlalchemy.orm import Session

from konboro.contracts.intake import ContextArtifact
from konboro.domain.flags import is_enabled
from konboro.services import flags

from .table import BomTable, mapping_complete

MAPPING_FLAG = "bom_column_mapping"


def flag_on(session: Session, tenant_id: str) -> bool:
    return is_enabled(flags.tenant_flags(session, tenant_id), MAPPING_FLAG)


def tables(artifacts: Iterable[ContextArtifact]) -> list[tuple[ContextArtifact, BomTable]]:
    return [(a, BomTable.model_validate_json(a.content)) for a in artifacts if a.kind == "bom_table"]


def unsure(artifacts: Iterable[ContextArtifact]) -> list[tuple[ContextArtifact, BomTable]]:
    """The spreadsheet tables whose mapping nobody has settled. A picture's columns come with its transcription."""
    return [(a, t) for a, t in tables(artifacts) if t.source == "spreadsheet" and not t.mapping_sure]


def needs_user(session: Session, tenant_id: str, artifacts: Iterable[ContextArtifact]) -> bool:
    """The `bom_mapping` confirmation reason (01 §5.6)."""
    return bool(unsure(artifacts)) and flag_on(session, tenant_id)


def incomplete(artifacts: Iterable[ContextArtifact]) -> list[str]:
    """Pages whose mapping has no item column or no quantity column: confirming them would read no product."""
    return [a.page_id for a, t in unsure(artifacts) if a.page_id and not mapping_complete(t)]
