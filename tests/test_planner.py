from __future__ import annotations

from decimal import Decimal

from splitwise_arbitrage.models import AppConfig, BusinessGroup
from splitwise_arbitrage.planner import build_arbitrage_plan


def test_dummy_debt_moves_to_fran_then_services_moves_to_office() -> None:
    config = _config()
    services = {
        "Fran": Decimal("0.00"),
        "dummyMeli": Decimal("-10000.00"),
        "Reski": Decimal("-5000.00"),
        "Gordo": Decimal("15000.00"),
        "Teo": Decimal("0.00"),
    }
    office = {
        "Fran": Decimal("-3000.00"),
        "Reski": Decimal("3000.00"),
        "Gordo": Decimal("0.00"),
        "Teo": Decimal("0.00"),
    }

    plan = build_arbitrage_plan(
        config,
        office,
        services,
        run_id="test-run",
        compact_internal=False,
        compact_cross=False,
    )

    assert plan.projected_services["dummyMeli"] == Decimal("0.00")
    assert plan.projected_services["Fran"] == Decimal("0.00")
    assert plan.projected_services["Reski"] == Decimal("0.00")
    assert plan.projected_services["Gordo"] == Decimal("0.00")
    assert plan.projected_office["Fran"] == Decimal("-13000.00")
    assert plan.projected_office["Reski"] == Decimal("-2000.00")
    assert plan.projected_office["Gordo"] == Decimal("15000.00")

    rendered = [(op.group_key, op.kind, op.debtor, op.creditor, op.amount) for op in plan.operations]
    assert ("services", "internal_dummy", "Fran", "dummyMeli", Decimal("10000.00")) in rendered
    assert ("services", "services_zero", "Gordo", "Fran", Decimal("10000.00")) in rendered
    assert ("office", "office_import", "Fran", "Gordo", Decimal("10000.00")) in rendered


def test_sensus3d_dummy_balance_splits_between_reski_and_gordo() -> None:
    config = _config()
    services = {
        "dummyBenja": Decimal("-100.01"),
        "Reski": Decimal("0.00"),
        "Gordo": Decimal("100.01"),
        "Fran": Decimal("0.00"),
        "Teo": Decimal("0.00"),
    }
    office = {}

    plan = build_arbitrage_plan(
        config,
        office,
        services,
        run_id="test-run",
        compact_internal=False,
    )

    assert plan.projected_services["dummyBenja"] == Decimal("0.00")
    assert plan.projected_services["Reski"] == Decimal("0.00")
    assert plan.projected_services["Gordo"] == Decimal("0.00")

    internal = [op for op in plan.operations if op.kind == "internal_dummy"]
    assert [(op.debtor, op.creditor, op.amount) for op in internal] == [
        ("Reski", "dummyBenja", Decimal("50.01")),
        ("Gordo", "dummyBenja", Decimal("50.00")),
    ]


def test_internal_scope_only_cleans_dummies_inside_services() -> None:
    config = _config()
    services = {
        "dummyBenja": Decimal("-100.00"),
        "Reski": Decimal("0.00"),
        "Gordo": Decimal("100.00"),
        "Fran": Decimal("50.00"),
        "Teo": Decimal("-50.00"),
    }
    office = {
        "Fran": Decimal("-20.00"),
        "Teo": Decimal("20.00"),
    }

    plan = build_arbitrage_plan(config, office, services, run_id="test-run", scope="internal")

    assert plan.scope == "internal"
    assert {operation.kind for operation in plan.operations} == {"internal_dummy"}
    assert plan.projected_services["dummyBenja"] == Decimal("0.00")
    assert plan.projected_services["Reski"] == Decimal("-50.00")
    assert plan.projected_services["Gordo"] == Decimal("50.00")
    assert plan.projected_services["Fran"] == Decimal("50.00")
    assert plan.projected_services["Teo"] == Decimal("-50.00")
    assert plan.projected_office["Fran"] == Decimal("-20.00")
    assert plan.projected_office["Teo"] == Decimal("20.00")


def test_internal_scope_compacts_dummy_cleanup_into_one_expense() -> None:
    config = _config()
    services = {
        "dummyBenja": Decimal("-100.01"),
        "dummyMeli": Decimal("-10.00"),
        "Reski": Decimal("0.00"),
        "Gordo": Decimal("100.01"),
        "Fran": Decimal("0.00"),
        "Teo": Decimal("0.00"),
    }
    office = {}

    plan = build_arbitrage_plan(config, office, services, run_id="test-run", scope="internal")

    assert len(plan.operations) == 1
    operation = plan.operations[0]
    assert operation.debtor == "multiple"
    assert operation.creditor == "multiple"
    assert operation.amount == Decimal("110.01")
    assert {
        (share.alias, share.paid_share, share.owed_share)
        for share in operation.shares
    } == {
        ("dummyBenja", Decimal("100.01"), Decimal("0.00")),
        ("Reski", Decimal("0.00"), Decimal("50.01")),
        ("Gordo", Decimal("0.00"), Decimal("50.00")),
        ("dummyMeli", Decimal("10.00"), Decimal("0.00")),
        ("Fran", Decimal("0.00"), Decimal("10.00")),
    }


def test_opposite_balances_cancel_in_office() -> None:
    config = _config()
    services = {
        "Fran": Decimal("1000.00"),
        "Reski": Decimal("-1000.00"),
        "Gordo": Decimal("0.00"),
        "Teo": Decimal("0.00"),
    }
    office = {
        "Fran": Decimal("-700.00"),
        "Reski": Decimal("700.00"),
    }

    plan = build_arbitrage_plan(config, office, services, run_id="test-run")

    assert plan.projected_services["Fran"] == Decimal("0.00")
    assert plan.projected_services["Reski"] == Decimal("0.00")
    assert plan.projected_office["Fran"] == Decimal("300.00")
    assert plan.projected_office["Reski"] == Decimal("-300.00")


def test_cross_scope_compacts_into_one_expense_per_group() -> None:
    config = _config()
    services = {
        "Fran": Decimal("1000.00"),
        "Reski": Decimal("-700.00"),
        "Gordo": Decimal("-300.00"),
        "Teo": Decimal("0.00"),
    }
    office = {
        "Fran": Decimal("-200.00"),
        "Reski": Decimal("200.00"),
        "Gordo": Decimal("0.00"),
        "Teo": Decimal("0.00"),
    }

    plan = build_arbitrage_plan(config, office, services, run_id="test-run", scope="cross")

    assert len(plan.operations) == 2
    assert [(operation.group_key, operation.kind, operation.amount) for operation in plan.operations] == [
        ("services", "services_zero", Decimal("1000.00")),
        ("office", "office_import", Decimal("1000.00")),
    ]
    assert all(operation.shares for operation in plan.operations)
    assert plan.projected_services["Fran"] == Decimal("0.00")
    assert plan.projected_services["Reski"] == Decimal("0.00")
    assert plan.projected_services["Gordo"] == Decimal("0.00")
    assert plan.projected_services["Teo"] == Decimal("0.00")
    assert plan.projected_office["Fran"] == Decimal("800.00")
    assert plan.projected_office["Reski"] == Decimal("-500.00")
    assert plan.projected_office["Gordo"] == Decimal("-300.00")


def _config() -> AppConfig:
    return AppConfig(
        api_key="token",
        auth_mode="api_key",
        consumer_key="",
        consumer_secret="",
        base_url="https://secure.splitwise.com/api/v3.0",
        office_group_id=1,
        services_group_id=2,
        office_group_name="Office",
        services_group_name="Office Servicios",
        user_ids={
            "Gordo": 10,
            "Reski": 11,
            "Fran": 12,
            "Teo": 13,
            "dummyMeli": 20,
            "dummyBenja": 21,
            "dummyJavi": 22,
            "dummyFeli": 23,
            "dummyIanchi": 24,
            "dummyPablo": 25,
        },
        business_groups=(
            BusinessGroup(
                "Sensus3D",
                ("Reski", "Gordo"),
                ("dummyBenja", "dummyJavi", "dummyFeli", "dummyIanchi", "dummyPablo"),
            ),
            BusinessGroup("InmoClick", ("Fran",), ("dummyMeli",)),
            BusinessGroup("TiendaNube", ("Teo",), ()),
        ),
        cross_group_aliases=("Gordo", "Reski", "Fran", "Teo"),
        currency_code="ARS",
        min_amount=Decimal("0.01"),
        dry_run=True,
        mark_as_payment=False,
        state_file="state/test_pending.json",
        schedule_time="06:00",
        schedule_timezone="America/Buenos_Aires",
    )
