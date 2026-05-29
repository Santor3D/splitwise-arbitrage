from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import ArbitragePlan, DebtOperation, ExpenseShare
from .money import money


class PendingRun:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def create_from_plan(self, plan: ArbitragePlan) -> dict[str, Any]:
        payload = {
            "run_id": plan.run_id,
            "scope": plan.scope,
            "operations": [
                {
                    "operation": _operation_to_json(operation),
                    "status": "pending",
                    "expense_id": None,
                }
                for operation in plan.operations
            ],
        }
        self.save(payload)
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.path)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def operation_from_json(payload: dict[str, Any]) -> DebtOperation:
    return DebtOperation(
        group_key=payload["group_key"],
        group_id=int(payload["group_id"]),
        kind=payload["kind"],
        debtor=payload["debtor"],
        creditor=payload["creditor"],
        amount=money(Decimal(str(payload["amount"]))),
        currency_code=payload["currency_code"],
        description=payload["description"],
        details=payload["details"],
        idempotency_key=payload["idempotency_key"],
        shares=tuple(
            ExpenseShare(
                alias=share["alias"],
                paid_share=money(Decimal(str(share["paid_share"]))),
                owed_share=money(Decimal(str(share["owed_share"]))),
            )
            for share in payload.get("shares", [])
        ),
    )


def _operation_to_json(operation: DebtOperation) -> dict[str, Any]:
    payload = asdict(operation)
    payload["amount"] = f"{operation.amount:.2f}"
    payload["shares"] = [
        {
            "alias": share.alias,
            "paid_share": f"{share.paid_share:.2f}",
            "owed_share": f"{share.owed_share:.2f}",
        }
        for share in operation.shares
    ]
    return payload
