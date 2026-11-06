"""GET /quotes/{id}/unresolved: the "לא פוענח" layer (13 §4.4, S26) on the NURSERY-1 fixture, behind
`unresolved_overlay`, and how a review action takes a spot off it."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import (
    PX_TO_PT,
    seed_nursery,
    seed_nursery_detections,
    seed_nursery_pages,
)
from konboro.services.storage import Storage

from .api import Api, ApiTenant, add_tenant, set_tenant_flag

FLAG = "unresolved_overlay"


@dataclass
class Fixture:
    api: Api
    tenant: ApiTenant
    quote_id: str

    def spots(self, status: int = 200) -> Any:
        r = self.api.client.get(f"/quotes/{self.quote_id}/unresolved", headers=self.api.as_(self.tenant))
        assert r.status_code == status, r.text
        return r.json()["spots"] if status == 200 else r.json()

    def quote(self) -> dict[str, Any]:
        return dict(self.api.client.get(f"/quotes/{self.quote_id}", headers=self.api.as_(self.tenant)).json())

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self.api.client.post(f"/quotes/{self.quote_id}{path}", json=body, headers=self.api.as_(self.tenant))
        assert r.status_code == 200, r.text
        return dict(r.json())


@pytest.fixture(scope="module")
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)
    return migrated_db


@pytest.fixture
def fixture(api: Api, seeded: dict[str, Engine], storage: Storage) -> Iterator[Fixture]:
    tenant = add_tenant(seeded["app"])
    with tenant_session(tenant.tenant_id, api.engine) as s:
        qid = seed_nursery(s, tenant.tenant_id)
        seed_nursery_pages(s, storage, tenant.tenant_id)
        assert seed_nursery_detections(s, storage, tenant.tenant_id)
        assert not seed_nursery_detections(s, storage, tenant.tenant_id)  # safe to rerun
    assert qid is not None
    set_tenant_flag(api.engine, tenant.tenant_id, FLAG, True)
    yield Fixture(api, tenant, qid)


def pt(*box: float) -> list[float]:
    return [round(v * PX_TO_PT, 1) for v in box]


def test_the_fixture_shows_the_prototypes_spots_and_the_lines_not_identified(fixture: Fixture) -> None:
    pages = {p["page_id"]: p["page_no"] for p in fixture.quote()["pages"]}
    spots = fixture.spots()
    seen = [(pages[s["page_id"]], s["kind"]) for s in spots]
    assert sorted(set(seen)) == [
        (4, "front_only"),
        (4, "unknown_symbol"),
        (5, "partial"),
        (8, "orphan_text"),
        (8, "partial"),
    ]
    by_kind = {
        k: [s for s in spots if s["kind"] == k] for k in ("unknown_symbol", "front_only", "orphan_text", "partial")
    }

    # the prototype's four (konboro-app.html 575–580), in the fixture's own boxes
    (unknown,) = by_kind["unknown_symbol"]
    assert unknown["bbox"] == pt(205, 500, 292, 572) and unknown["note"] == "סימן שלא זיהינו. לא בספריית הסימנים"
    (front,) = by_kind["front_only"]
    assert front["bbox"] == pt(497, 663, 632, 733) and front["note"] == "F26–F29 מופיעים בחזית ולא בתוכנית"
    assert front["finding_id"].startswith("iss_")
    (orphan,) = by_kind["orphan_text"]
    assert orphan["bbox"] == pt(1210, 380, 1290, 448) and orphan["note"] == '"9 / 5": ערך חשמלי שלא שויך לאף רכיב'

    # S26 decision 7: RNV has no model, C1–C4's current is inferred. RNV's second box is the orphan text's place,
    # so it is drawn once (`one_per_place`). Q0 (its model written, no price) and NVR (priced) are not partial.
    partial = by_kind["partial"]
    notes = sorted({s["note"] for s in partial})
    assert notes == ["C1–C4: הוסק מהמעגל ואין מחיר", "RNV: אין דגם ואין מחיר"]
    assert sum(s["note"].startswith("RNV") for s in partial) == 1
    assert sum(s["note"].startswith("C1") for s in partial) == 8
    assert len(spots) == 12

    # in page order, then top to bottom
    order = [(pages[s["page_id"]], s["bbox"][1]) for s in spots]
    assert order == sorted(order)


def test_a_spot_drops_off_when_the_user_resolves_it(fixture: Fixture) -> None:
    lines = {ln["designators"][0]: ln for ln in fixture.quote()["panels"][0]["lines"] if ln["designators"]}
    done = fixture.post(f"/lines/{lines['C1']['line_id']}/approve")
    assert not [s for s in fixture.spots() if s["line_id"] == lines["C1"]["line_id"]]

    fv = next(f for f in fixture.quote()["findings"] if f["code"] == "FRONT_VIEW_DESIGNATOR_MISSING")
    fixture.post(f"/findings/{fv['finding_id']}/dismiss", {"reason": "intended"})
    assert not [s for s in fixture.spots() if s["kind"] == "front_only"]

    fixture.post(f"/undo/{done['event_id']}")  # undo the approval: C1–C4 are back
    assert sum(s["line_id"] == lines["C1"]["line_id"] for s in fixture.spots()) == 8


def test_the_route_is_not_there_with_the_flag_off(fixture: Fixture) -> None:
    set_tenant_flag(fixture.api.engine, fixture.tenant.tenant_id, FLAG, False)
    assert fixture.spots(status=404)["error"]["code"] == "not_found"
    set_tenant_flag(fixture.api.engine, fixture.tenant.tenant_id, FLAG, True)
    assert fixture.spots()


def test_another_tenants_quote_is_not_found(fixture: Fixture) -> None:
    api = fixture.api
    set_tenant_flag(api.engine, api.b.tenant_id, FLAG, True)
    r = api.client.get(f"/quotes/{fixture.quote_id}/unresolved", headers=api.as_(api.b))
    assert r.status_code == 404, r.text
