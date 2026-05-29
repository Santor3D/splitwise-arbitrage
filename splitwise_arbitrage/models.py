from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class BusinessGroup:
    name: str
    admins: tuple[str, ...]
    employees: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    api_key: str
    auth_mode: str
    consumer_key: str
    consumer_secret: str
    base_url: str
    office_group_id: int
    services_group_id: int
    office_group_name: str
    services_group_name: str
    user_ids: dict[str, int]
    business_groups: tuple[BusinessGroup, ...]
    cross_group_aliases: tuple[str, ...]
    currency_code: str
    min_amount: Decimal
    dry_run: bool
    mark_as_payment: bool
    state_file: str
    schedule_time: str
    schedule_timezone: str


@dataclass(frozen=True)
class ExpenseShare:
    alias: str
    paid_share: Decimal
    owed_share: Decimal


@dataclass(frozen=True)
class DebtOperation:
    group_key: str
    group_id: int
    kind: str
    debtor: str
    creditor: str
    amount: Decimal
    currency_code: str
    description: str
    details: str
    idempotency_key: str = ""
    shares: tuple[ExpenseShare, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ArbitragePlan:
    run_id: str
    scope: str
    initial_office: dict[str, Decimal]
    initial_services: dict[str, Decimal]
    projected_office: dict[str, Decimal]
    projected_services: dict[str, Decimal]
    operations: tuple[DebtOperation, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
