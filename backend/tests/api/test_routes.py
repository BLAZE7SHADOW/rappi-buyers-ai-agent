from fastapi.testclient import TestClient

from tests.services.conftest import make_case


def test_case_contract_exposes_buyer_workbench_data(db):
    from app.main import app

    case_id = make_case()
    response = TestClient(app).get(f"/api/cases/{case_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["case"]["next_actor"] == "agent"
    assert body["case"]["signal_source"] == "Replenishment system"
    assert body["evidence"]["inventory"]["usable"] == 1000
    assert body["projection"]["summary"]["total_unmet_units"] > 0
    assert body["candidates"]

    queue_item = next(
        item for item in TestClient(app).get("/api/cases").json()["cases"]
        if item["case_id"] == case_id
    )
    assert queue_item["signal_source"] == "Replenishment system"
    assert queue_item["data_as_of"] == "2026-09-17"
    assert queue_item["last_activity_at"]
    assert queue_item["projected_unmet_units"] == 400


def test_terminal_case_rejects_another_agent_run_before_provider_lookup(db):
    from app.db import schema as s
    from app.db.engine import transaction
    from app.main import app

    case_id = make_case()
    with transaction() as conn:
        conn.execute(s.cases.update().where(s.cases.c.case_id == case_id).values(state="resolved"))

    response = TestClient(app).post(f"/api/cases/{case_id}/run", json={"mode": "live"})

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "INVALID_CASE_STATE"


def test_health_advertises_live_and_replay_capabilities(db):
    from app.main import app

    body = TestClient(app).get("/api/health").json()
    assert body["live_agent_available"] is body["llm_key_present"]
    assert body["replay_available"] is True


def test_case_options_preview_authoritative_operational_constraints(db):
    from app.main import app

    make_case()
    response = TestClient(app).get("/api/catalog/case-options")

    assert response.status_code == 200
    option = response.json()["options"][0]
    assert option == {
        "sku": "SKU-1001",
        "node_id": "NODE-BOG",
        "product_name": "Test product",
        "node_name": "Bogota DC",
        "as_of_date": "2026-09-17",
        "usable_inventory": 1000,
        "forecast_units": 2800,
        "available_budget_minor": 900000,
        "storage_headroom_m3": 180.0,
        "eligible_suppliers": 1,
        "projected_unmet_units": 400,
    }


def test_buyer_can_open_a_case_using_authoritative_constraint_facts(db):
    from sqlalchemy import select

    from app.db import schema as s
    from app.db.engine import transaction
    from app.main import app

    make_case()
    client = TestClient(app)
    response = client.post("/api/cases", json={
        "sku": "SKU-1001",
        "node_id": "NODE-BOG",
        "recommended_qty": 725,
        "reason": "Sales team requested a launch buffer",
    })

    assert response.status_code == 201
    detail = client.get(f"/api/cases/{response.json()['case_id']}").json()
    assert detail["case"]["fixture_id"] is None
    assert detail["case"]["state"] == "investigating"
    assert detail["case"]["trigger"]["recommended_qty"] == 725
    assert detail["case"]["trigger"]["reason"] == "Sales team requested a launch buffer"
    assert detail["evidence"]["budget"]["available_minor"] == 900000
    assert detail["evidence"]["inventory"]["usable"] == 1000
    assert detail["candidates"]
    queue_item = next(
        item for item in client.get("/api/cases").json()["cases"]
        if item["case_id"] == response.json()["case_id"]
    )
    assert queue_item["signal_source"] == "Buyer-created"
    with transaction() as conn:
        stored = conn.execute(
            select(s.cases).where(s.cases.c.case_id == response.json()["case_id"])
        ).mappings().one()
    assert stored["signal_source"] == "buyer"
    assert stored["created_at"] is not None
    assert stored["updated_at"] is not None


def test_buyer_cannot_override_system_constraint_facts(db):
    from app.main import app

    make_case()
    response = TestClient(app).post("/api/cases", json={
        "sku": "SKU-1001",
        "node_id": "NODE-BOG",
        "recommended_qty": 725,
        "reason": "Try to make the recommendation appear affordable",
        "available_budget_minor": 99_999_999,
    })

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_buyer_case_rejects_unknown_sku_node_and_invalid_quantity(db):
    from app.main import app

    make_case()
    client = TestClient(app)
    unknown = client.post("/api/cases", json={
        "sku": "MISSING",
        "node_id": "NODE-BOG",
        "recommended_qty": 100,
        "reason": "Review",
    })
    invalid = client.post("/api/cases", json={
        "sku": "SKU-1001",
        "node_id": "NODE-BOG",
        "recommended_qty": 0,
        "reason": "Review",
    })

    assert unknown.status_code == 400
    assert unknown.json()["detail"]["error"] == "UNKNOWN_SKU_NODE"
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["error"] == "INVALID_QUANTITY"


def test_buyer_created_case_reports_replay_unavailable_as_typed_404(db):
    from app.main import app

    make_case()
    client = TestClient(app)
    created = client.post("/api/cases", json={
        "sku": "SKU-1001",
        "node_id": "NODE-BOG",
        "recommended_qty": 725,
        "reason": "Review",
    }).json()

    response = client.post(f"/api/cases/{created['case_id']}/run", json={"mode": "replay"})

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "REPLAY_NOT_AVAILABLE"


def test_recorded_f1_replays_the_full_feedback_loop(db):
    from app.db.seed import seed_fixture
    from app.main import app

    case_id = seed_fixture("F1")
    client = TestClient(app)

    first = client.post(f"/api/cases/{case_id}/run", json={"mode": "replay"})
    assert first.status_code == 200
    state = client.get(f"/api/cases/{case_id}").json()
    first_proposal = state["proposals"][-1]
    assert state["case"]["state"] == "awaiting_approval"
    assert first_proposal["action_type"] == "expedite_po"

    approved = client.post(
        f"/api/proposals/{first_proposal['proposal_id']}/approve",
        json={"approver": "browser-test"},
    )
    assert approved.status_code == 200
    assert approved.json()["verdict"]["verdict"] == "PARTIAL"
    reopened = client.get(f"/api/cases/{case_id}").json()
    assert reopened["case"]["state"] == "reopened"
    assert reopened["case"]["supplier_behavior"] == "confirm_full"

    # The second recorded segment investigates the changed state and proposes a
    # different action. Demo supplier behavior is consumed once, so this action
    # receives the normal full-confirmation response.
    second = client.post(f"/api/cases/{case_id}/run", json={"mode": "replay"})
    assert second.status_code == 200
    state = client.get(f"/api/cases/{case_id}").json()
    second_proposal = state["proposals"][-1]
    assert second_proposal["action_type"] == "create_po"

    final = client.post(
        f"/api/proposals/{second_proposal['proposal_id']}/approve",
        json={"approver": "browser-test"},
    )
    assert final.status_code == 200
    assert final.json()["verdict"]["verdict"] == "PASS"
    assert client.get(f"/api/cases/{case_id}").json()["case"]["state"] == "resolved"
