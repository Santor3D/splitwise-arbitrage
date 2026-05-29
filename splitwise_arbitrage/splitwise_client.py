from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

import requests

from .models import AppConfig, DebtOperation
from .money import fmt


class SplitwiseApiError(RuntimeError):
    pass


class SplitwiseClient:
    def __init__(self, config: AppConfig, timeout: int = 30) -> None:
        self.config = config
        self.timeout = timeout
        self.session = requests.Session()
        token_type = "api key" if config.auth_mode == "api_key" else "OAuth2 access token"
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": f"splitwise-arbitrage/0.1.0 ({token_type})",
            }
        )

    def get_current_user(self) -> dict[str, Any]:
        return self._request("GET", "/get_current_user")

    def get_groups(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/get_groups")
        return list(payload.get("groups", []))

    def get_friends(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/get_friends")
        return list(payload.get("friends", []))

    def get_group(self, group_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/get_group/{group_id}")
        return dict(payload.get("group", {}))

    def get_expenses(self, group_id: int, days_back: int = 14, limit: int = 100) -> list[dict[str, Any]]:
        dated_after = (
            datetime.now(timezone.utc)
            - timedelta(days=days_back)
        ).isoformat().replace("+00:00", "Z")
        payload = self._request(
            "GET",
            "/get_expenses",
            params={
                "group_id": group_id,
                "dated_after": dated_after,
                "limit": limit,
            },
        )
        return list(payload.get("expenses", []))

    def find_expense_by_idempotency_key(self, group_id: int, key: str) -> dict[str, Any] | None:
        needle = f"SWARB:{key}"
        for expense in self.get_expenses(group_id=group_id):
            details = str(expense.get("details", ""))
            if needle in details:
                return expense
        return None

    def create_expense(self, operation: DebtOperation) -> dict[str, Any]:
        amount = fmt(operation.amount)
        payload: dict[str, Any] = {
            "group_id": operation.group_id,
            "cost": amount,
            "description": operation.description,
            "details": _operation_details(operation),
            "currency_code": operation.currency_code,
            "repeat_interval": "never",
        }
        if operation.shares:
            for index, share in enumerate(operation.shares):
                payload[f"users__{index}__user_id"] = self.config.user_ids[share.alias]
                payload[f"users__{index}__paid_share"] = fmt(share.paid_share)
                payload[f"users__{index}__owed_share"] = fmt(share.owed_share)
        else:
            payload.update(
                {
                    "users__0__user_id": self.config.user_ids[operation.creditor],
                    "users__0__paid_share": amount,
                    "users__0__owed_share": "0.00",
                    "users__1__user_id": self.config.user_ids[operation.debtor],
                    "users__1__paid_share": "0.00",
                    "users__1__owed_share": amount,
                }
            )
        if self.config.mark_as_payment:
            payload["payment"] = True

        response = self._request("POST", "/create_expense", json=payload)
        errors = response.get("errors") or {}
        if errors:
            raise SplitwiseApiError(f"Splitwise rejected create_expense: {errors}")
        expenses = response.get("expenses") or []
        if not expenses:
            raise SplitwiseApiError(f"Splitwise did not return an expense id: {response}")
        return dict(expenses[0])

    def create_friend(
        self,
        first_name: str,
        last_name: str = "",
        email: str = "",
    ) -> dict[str, Any]:
        payload = {
            "user_first_name": first_name,
            "user_last_name": last_name,
        }
        if email:
            payload["user_email"] = email
        response = self._request("POST", "/create_friend", json=payload)
        errors = response.get("errors") or {}
        if errors:
            raise SplitwiseApiError(f"Splitwise rejected create_friend: {errors}")
        friend = response.get("friend")
        if not friend:
            raise SplitwiseApiError(f"Splitwise did not return a friend: {response}")
        return dict(friend)

    def add_user_to_group(self, group_id: int, user_id: int) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/add_user_to_group",
            json={"group_id": group_id, "user_id": user_id},
        )
        if not response.get("success"):
            raise SplitwiseApiError(
                f"Splitwise rejected add_user_to_group: {response.get('errors') or response}"
            )
        return dict(response.get("user") or {})

    def remove_user_from_group(self, group_id: int, user_id: int) -> None:
        response = self._request(
            "POST",
            "/remove_user_from_group",
            json={"group_id": group_id, "user_id": user_id},
        )
        if not response.get("success"):
            raise SplitwiseApiError(
                f"Splitwise rejected remove_user_from_group: {response.get('errors') or response}"
            )

    def update_user(
        self,
        user_id: int,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if first_name is not None:
            payload["first_name"] = first_name
        if last_name is not None:
            payload["last_name"] = last_name
        if email is not None:
            payload["email"] = email
        if not payload:
            raise ValueError("At least one user field must be provided.")

        response = self._request("POST", f"/update_user/{user_id}", json=payload)
        errors = response.get("errors") or {}
        if errors:
            raise SplitwiseApiError(f"Splitwise rejected update_user: {errors}")
        return dict(response.get("user") or response)

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        response = self.session.request(
            method=method,
            url=url,
            params=params,
            json=json,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SplitwiseApiError(
                f"Splitwise {method} {path} failed with {response.status_code}: {response.text}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SplitwiseApiError(f"Splitwise returned non-JSON response: {response.text}") from exc
        return dict(payload)


def _operation_details(operation: DebtOperation) -> str:
    if operation.shares:
        compact_note = f"kind={operation.kind}; participants={len(operation.shares)}"
    else:
        compact_note = (
            f"kind={operation.kind}; debtor={operation.debtor}; creditor={operation.creditor}; "
            f"amount={fmt(operation.amount)} {operation.currency_code}"
        )
    return f"{operation.details}\nSWARB:{operation.idempotency_key}\n{compact_note}"


def decimal_from_splitwise(value: Any) -> Decimal:
    return Decimal(str(value or "0"))
