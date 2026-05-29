from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from .models import AppConfig, ArbitragePlan, DebtOperation, ExpenseShare
from .money import ZERO, fmt, is_zero, money, split_signed_amount
from .splitwise_client import decimal_from_splitwise


def balances_from_group(
    group: dict,
    user_ids: dict[str, int],
    currency_code: str,
) -> tuple[dict[str, Decimal], tuple[str, ...]]:
    id_to_alias = {user_id: alias for alias, user_id in user_ids.items() if user_id > 0}
    balances: dict[str, Decimal] = {alias: ZERO for alias in user_ids}
    warnings: list[str] = []

    for member in group.get("members", []):
        user_id = int(member.get("id") or 0)
        alias = id_to_alias.get(user_id)
        if not alias:
            continue
        balances[alias] = _member_balance(member, currency_code)

        other_currencies = []
        for balance in member.get("balance", []) or []:
            code = str(balance.get("currency_code", "")).upper()
            amount = money(decimal_from_splitwise(balance.get("amount")))
            if code and code != currency_code and amount != ZERO:
                other_currencies.append(f"{fmt(amount)} {code}")
        if other_currencies:
            warnings.append(
                f"{alias} has non-zero balances outside {currency_code}: "
                + ", ".join(other_currencies)
            )

    return balances, tuple(warnings)


def build_arbitrage_plan(
    config: AppConfig,
    office_balances: dict[str, Decimal],
    services_balances: dict[str, Decimal],
    run_id: str | None = None,
    scope: str = "all",
    compact_internal: bool = True,
    compact_cross: bool = True,
) -> ArbitragePlan:
    if scope not in {"all", "internal", "cross"}:
        raise ValueError("scope must be one of: all, internal, cross")

    run_id = run_id or _new_run_id()
    operations: list[DebtOperation] = []
    warnings: list[str] = []

    projected_services = _complete_balance_map(services_balances, config.user_ids)
    projected_office = _complete_balance_map(office_balances, config.user_ids)

    if scope in {"all", "internal"}:
        internal_delta: dict[str, Decimal] = defaultdict(lambda: ZERO)
        internal_details: list[str] = []
        for business_group in config.business_groups:
            for employee in business_group.employees:
                net = money(projected_services.get(employee, ZERO))
                if is_zero(net, config.min_amount):
                    continue

                delta: dict[str, Decimal] = defaultdict(lambda: ZERO)
                delta[employee] += money(-net)
                for owner, share in split_signed_amount(net, business_group.admins).items():
                    delta[owner] += share

                details = (
                    f"Transfiere saldo neto de {employee} a admins de {business_group.name}: "
                    + ", ".join(business_group.admins)
                )
                if compact_internal:
                    internal_details.append(details)
                    for alias, amount in delta.items():
                        internal_delta[alias] += amount
                else:
                    operations.extend(
                        _settle_delta(
                            delta=dict(delta),
                            group_key="services",
                            group_id=config.services_group_id,
                            kind="internal_dummy",
                            currency_code=config.currency_code,
                            description=f"Arbitraje dummy {employee}",
                            details=details,
                            min_amount=config.min_amount,
                        )
                    )
                _apply_delta(projected_services, delta)

        if compact_internal and internal_details:
            operations.extend(
                _compact_delta_expense(
                    delta=dict(internal_delta),
                    group_key="services",
                    group_id=config.services_group_id,
                    kind="internal_dummy",
                    currency_code=config.currency_code,
                    description="Arbitraje dummies",
                    details="; ".join(internal_details),
                    min_amount=config.min_amount,
                )
            )

    if scope == "internal":
        keyed_operations = tuple(
            _with_idempotency_key(run_id, index, op) for index, op in enumerate(operations, 1)
        )
        return ArbitragePlan(
            run_id=run_id,
            scope=scope,
            initial_office=_complete_balance_map(office_balances, config.user_ids),
            initial_services=_complete_balance_map(services_balances, config.user_ids),
            projected_office=projected_office,
            projected_services=projected_services,
            operations=keyed_operations,
            warnings=tuple(warnings),
        )

    cross_vector = {
        alias: money(projected_services.get(alias, ZERO))
        for alias in config.cross_group_aliases
    }
    cross_total = money(sum(cross_vector.values(), ZERO))
    if not is_zero(cross_total, config.min_amount):
        warnings.append(
            "Cross-group aliases in Office Servicios do not sum to zero "
            f"({fmt(cross_total)} {config.currency_code}). Check unconfigured users/currencies."
        )

    services_zero_delta = {alias: money(-amount) for alias, amount in cross_vector.items()}
    office_import_delta = dict(cross_vector)

    if compact_cross:
        services_cross_ops = _compact_delta_expense(
            delta=services_zero_delta,
            group_key="services",
            group_id=config.services_group_id,
            kind="services_zero",
            currency_code=config.currency_code,
            description="Arbitraje hacia Office",
            details="Cancela en Office Servicios el saldo que se migra a Office.",
            min_amount=config.min_amount,
        )
        office_cross_ops = _compact_delta_expense(
            delta=office_import_delta,
            group_key="office",
            group_id=config.office_group_id,
            kind="office_import",
            currency_code=config.currency_code,
            description="Arbitraje desde Office Servicios",
            details="Replica en Office el saldo neto migrado desde Office Servicios.",
            min_amount=config.min_amount,
        )
    else:
        services_cross_ops = _settle_delta(
            delta=services_zero_delta,
            group_key="services",
            group_id=config.services_group_id,
            kind="services_zero",
            currency_code=config.currency_code,
            description="Arbitraje hacia Office",
            details="Cancela en Office Servicios el saldo que se migra a Office.",
            min_amount=config.min_amount,
        )
        office_cross_ops = _settle_delta(
            delta=office_import_delta,
            group_key="office",
            group_id=config.office_group_id,
            kind="office_import",
            currency_code=config.currency_code,
            description="Arbitraje desde Office Servicios",
            details="Replica en Office el saldo neto migrado desde Office Servicios.",
            min_amount=config.min_amount,
        )

    operations.extend(services_cross_ops)
    operations.extend(office_cross_ops)
    _apply_delta(projected_services, services_zero_delta)
    _apply_delta(projected_office, office_import_delta)

    keyed_operations = tuple(_with_idempotency_key(run_id, index, op) for index, op in enumerate(operations, 1))

    return ArbitragePlan(
        run_id=run_id,
        scope=scope,
        initial_office=_complete_balance_map(office_balances, config.user_ids),
        initial_services=_complete_balance_map(services_balances, config.user_ids),
        projected_office=projected_office,
        projected_services=projected_services,
        operations=keyed_operations,
        warnings=tuple(warnings),
    )


def _settle_delta(
    delta: dict[str, Decimal],
    group_key: str,
    group_id: int,
    kind: str,
    currency_code: str,
    description: str,
    details: str,
    min_amount: Decimal,
) -> list[DebtOperation]:
    normalized = {alias: money(amount) for alias, amount in delta.items()}
    total = money(sum(normalized.values(), ZERO))
    if not is_zero(total, min_amount):
        raise ValueError(f"Delta for {kind} does not sum to zero: {fmt(total)} {currency_code}")

    debtors = [[alias, money(-amount)] for alias, amount in normalized.items() if amount <= -min_amount]
    creditors = [[alias, amount] for alias, amount in normalized.items() if amount >= min_amount]
    operations: list[DebtOperation] = []

    debtor_index = 0
    creditor_index = 0
    while debtor_index < len(debtors) and creditor_index < len(creditors):
        debtor, debt_amount = debtors[debtor_index]
        creditor, credit_amount = creditors[creditor_index]
        amount = money(min(debt_amount, credit_amount))
        if amount >= min_amount:
            operations.append(
                DebtOperation(
                    group_key=group_key,
                    group_id=group_id,
                    kind=kind,
                    debtor=debtor,
                    creditor=creditor,
                    amount=amount,
                    currency_code=currency_code,
                    description=description,
                    details=details,
                )
            )

        debtors[debtor_index][1] = money(debt_amount - amount)
        creditors[creditor_index][1] = money(credit_amount - amount)
        if debtors[debtor_index][1] < min_amount:
            debtor_index += 1
        if creditors[creditor_index][1] < min_amount:
            creditor_index += 1

    return operations


def _compact_delta_expense(
    delta: dict[str, Decimal],
    group_key: str,
    group_id: int,
    kind: str,
    currency_code: str,
    description: str,
    details: str,
    min_amount: Decimal,
) -> list[DebtOperation]:
    normalized = {alias: money(amount) for alias, amount in delta.items()}
    total = money(sum(normalized.values(), ZERO))
    if not is_zero(total, min_amount):
        raise ValueError(f"Delta for {kind} does not sum to zero: {fmt(total)} {currency_code}")

    shares: list[ExpenseShare] = []
    cost = ZERO
    for alias, amount in normalized.items():
        if amount >= min_amount:
            shares.append(ExpenseShare(alias=alias, paid_share=amount, owed_share=ZERO))
            cost = money(cost + amount)
        elif amount <= -min_amount:
            shares.append(ExpenseShare(alias=alias, paid_share=ZERO, owed_share=money(-amount)))

    if not shares or cost < min_amount:
        return []

    owed_total = money(sum((share.owed_share for share in shares), ZERO))
    if money(cost - owed_total) != ZERO:
        raise ValueError(
            f"Compact expense for {kind} is unbalanced: paid={fmt(cost)}, owed={fmt(owed_total)}"
        )

    return [
        DebtOperation(
            group_key=group_key,
            group_id=group_id,
            kind=kind,
            debtor="multiple",
            creditor="multiple",
            amount=cost,
            currency_code=currency_code,
            description=description,
            details=details,
            shares=tuple(shares),
        )
    ]


def _apply_delta(balances: dict[str, Decimal], delta: dict[str, Decimal]) -> None:
    for alias, amount in delta.items():
        balances[alias] = money(balances.get(alias, ZERO) + amount)


def _complete_balance_map(source: dict[str, Decimal], user_ids: dict[str, int]) -> dict[str, Decimal]:
    result = {alias: ZERO for alias in user_ids}
    for alias, amount in source.items():
        result[alias] = money(amount)
    return result


def _member_balance(member: dict, currency_code: str) -> Decimal:
    for balance in member.get("balance", []) or []:
        if str(balance.get("currency_code", "")).upper() == currency_code:
            return money(decimal_from_splitwise(balance.get("amount")))
    return ZERO


def _new_run_id() -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{now}-{uuid4().hex[:8]}"


def _with_idempotency_key(run_id: str, index: int, operation: DebtOperation) -> DebtOperation:
    if operation.shares:
        share_material = "|".join(
            f"{share.alias}:{fmt(share.paid_share)}:{fmt(share.owed_share)}"
            for share in operation.shares
        )
    else:
        share_material = f"{operation.debtor}|{operation.creditor}|{fmt(operation.amount)}"
    material = (
        f"{run_id}|{index}|{operation.group_key}|{operation.kind}|"
        f"{share_material}|{operation.currency_code}"
    )
    digest = sha256(material.encode("utf-8")).hexdigest()[:20]
    return DebtOperation(
        group_key=operation.group_key,
        group_id=operation.group_id,
        kind=operation.kind,
        debtor=operation.debtor,
        creditor=operation.creditor,
        amount=operation.amount,
        currency_code=operation.currency_code,
        description=operation.description,
        details=operation.details,
        idempotency_key=digest,
        shares=operation.shares,
    )
