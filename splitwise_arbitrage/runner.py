from __future__ import annotations

from decimal import Decimal

from .models import AppConfig, ArbitragePlan, DebtOperation
from .money import ZERO, fmt
from .planner import balances_from_group, build_arbitrage_plan
from .splitwise_client import SplitwiseClient
from .state import PendingRun, operation_from_json


def load_remote_plan(
    config: AppConfig,
    client: SplitwiseClient,
    scope: str = "all",
    compact_internal: bool = True,
    compact_cross: bool = True,
) -> ArbitragePlan:
    office_group = client.get_group(config.office_group_id)
    services_group = client.get_group(config.services_group_id)
    office_balances, office_warnings = balances_from_group(
        office_group,
        config.user_ids,
        config.currency_code,
    )
    services_balances, services_warnings = balances_from_group(
        services_group,
        config.user_ids,
        config.currency_code,
    )
    plan = build_arbitrage_plan(
        config,
        office_balances,
        services_balances,
        scope=scope,
        compact_internal=compact_internal,
        compact_cross=compact_cross,
    )
    if office_warnings or services_warnings:
        plan = ArbitragePlan(
            run_id=plan.run_id,
            scope=plan.scope,
            initial_office=plan.initial_office,
            initial_services=plan.initial_services,
            projected_office=plan.projected_office,
            projected_services=plan.projected_services,
            operations=plan.operations,
            warnings=tuple([*plan.warnings, *office_warnings, *services_warnings]),
        )
    return plan


def apply_or_resume(config: AppConfig, client: SplitwiseClient, plan: ArbitragePlan) -> int:
    pending = PendingRun(config.state_file)
    if pending.exists():
        payload = pending.load()
        pending_scope = payload.get("scope")
        if pending_scope and pending_scope != plan.scope:
            raise ValueError(
                f"Pending run scope is {pending_scope}, but current plan scope is {plan.scope}."
            )
    else:
        payload = pending.create_from_plan(plan)

    applied = 0
    for item in payload.get("operations", []):
        if item.get("status") == "done":
            continue
        operation = operation_from_json(item["operation"])
        existing = client.find_expense_by_idempotency_key(operation.group_id, operation.idempotency_key)
        if existing:
            item["status"] = "done"
            item["expense_id"] = existing.get("id")
            pending.save(payload)
            continue
        created = client.create_expense(operation)
        item["status"] = "done"
        item["expense_id"] = created.get("id")
        pending.save(payload)
        applied += 1

    pending.clear()
    return applied


def validate_memberships(config: AppConfig, client: SplitwiseClient) -> list[str]:
    office_group = client.get_group(config.office_group_id)
    services_group = client.get_group(config.services_group_id)
    messages: list[str] = []

    for expected, group in (
        (config.office_group_name, office_group),
        (config.services_group_name, services_group),
    ):
        actual = group.get("name", "")
        if expected and actual and str(actual) != expected:
            messages.append(f"Group name mismatch: expected {expected}, got {actual}.")

    office_ids = _member_ids(office_group)
    services_ids = _member_ids(services_group)
    for alias in config.cross_group_aliases:
        user_id = config.user_ids[alias]
        if user_id not in office_ids:
            messages.append(f"{alias} ({user_id}) is not in Office.")
        if user_id not in services_ids:
            messages.append(f"{alias} ({user_id}) is not in Office Servicios.")

    for group in config.business_groups:
        for employee in group.employees:
            user_id = config.user_ids[employee]
            if user_id not in services_ids:
                messages.append(f"{employee} ({user_id}) is not in Office Servicios.")

    return messages


def format_plan(plan: ArbitragePlan) -> str:
    lines: list[str] = [f"Run id: {plan.run_id}", f"Scope: {plan.scope}"]
    if plan.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in plan.warnings:
            lines.append(f"- {warning}")

    lines.append("")
    lines.append(f"Operations: {len(plan.operations)}")
    for index, operation in enumerate(plan.operations, 1):
        lines.append(_format_operation(index, operation))

    lines.append("")
    lines.append("Projected Office Servicios:")
    lines.extend(_format_balances(plan.projected_services, plan.initial_services))
    lines.append("")
    lines.append("Projected Office:")
    lines.extend(_format_balances(plan.projected_office, plan.initial_office))
    return "\n".join(lines)


def _format_operation(index: int, operation: DebtOperation) -> str:
    return (
        f"{index}. [{operation.group_key}/{operation.kind}] "
        f"{_operation_parties(operation)} "
        f"{fmt(operation.amount)} {operation.currency_code}"
    )


def _operation_parties(operation: DebtOperation) -> str:
    if not operation.shares:
        return f"{operation.debtor} owes {operation.creditor}"

    paid = [
        f"{share.alias} +{fmt(share.paid_share)}"
        for share in operation.shares
        if share.paid_share > ZERO
    ]
    owed = [
        f"{share.alias} -{fmt(share.owed_share)}"
        for share in operation.shares
        if share.owed_share > ZERO
    ]
    return f"compact expense (paid: {', '.join(paid)}; owed: {', '.join(owed)})"


def _format_balances(projected: dict[str, Decimal], initial: dict[str, Decimal]) -> list[str]:
    lines: list[str] = []
    aliases = sorted(set(projected) | set(initial))
    for alias in aliases:
        before = initial.get(alias, ZERO)
        after = projected.get(alias, ZERO)
        if before == ZERO and after == ZERO:
            continue
        lines.append(f"- {alias}: {fmt(before)} -> {fmt(after)}")
    if not lines:
        lines.append("- all tracked aliases are zero")
    return lines


def _member_ids(group: dict) -> set[int]:
    return {int(member.get("id") or 0) for member in group.get("members", [])}
