from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .models import AppConfig, BusinessGroup
from .money import money


class ConfigError(ValueError):
    pass


def load_config(env_file: str = ".env", require_runtime: bool = True) -> AppConfig:
    env_path = Path(env_file)
    if env_path.exists():
        load_dotenv(env_path, override=False)

    auth_mode = os.getenv("SPLITWISE_AUTH_MODE", "api_key").strip().lower()
    if auth_mode not in {"api_key", "oauth2"}:
        raise ConfigError("SPLITWISE_AUTH_MODE must be api_key or oauth2.")

    consumer_key = os.getenv("SPLITWISE_CONSUMER_KEY", "").strip()
    consumer_secret = os.getenv("SPLITWISE_CONSUMER_SECRET", "").strip()
    api_key = _auth_token_for_mode(auth_mode)

    office_group_id = _int_env("SPLITWISE_OFFICE_GROUP_ID", required=require_runtime)
    services_group_id = _int_env("SPLITWISE_OFFICE_SERVICES_GROUP_ID", required=require_runtime)

    user_ids = _parse_user_ids(os.getenv("SPLITWISE_USERS_JSON", "{}"))
    business_groups = _parse_business_groups(os.getenv("BUSINESS_GROUPS_JSON", "{}"))
    cross_group_aliases = tuple(_csv_env("CROSS_GROUP_ALIASES"))

    if require_runtime:
        missing: list[str] = []
        if not api_key:
            missing.append(
                "SPLITWISE_API_KEY" if auth_mode == "api_key" else "SPLITWISE_OAUTH2_ACCESS_TOKEN"
            )
        if office_group_id == 0:
            missing.append("SPLITWISE_OFFICE_GROUP_ID")
        if services_group_id == 0:
            missing.append("SPLITWISE_OFFICE_SERVICES_GROUP_ID")
        if not business_groups:
            missing.append("BUSINESS_GROUPS_JSON")
        if not cross_group_aliases:
            missing.append("CROSS_GROUP_ALIASES")
        if missing:
            raise ConfigError("Missing required config: " + ", ".join(missing))

        required_aliases = set(cross_group_aliases)
        for group in business_groups:
            required_aliases.update(group.admins)
            required_aliases.update(group.employees)

        missing_users = sorted(alias for alias in required_aliases if user_ids.get(alias, 0) <= 0)
        if missing_users:
            raise ConfigError(
                "Missing Splitwise user ids in SPLITWISE_USERS_JSON for: "
                + ", ".join(missing_users)
            )

    return AppConfig(
        api_key=api_key,
        auth_mode=auth_mode,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        base_url=os.getenv("SPLITWISE_BASE_URL", "https://secure.splitwise.com/api/v3.0").rstrip("/"),
        office_group_id=office_group_id,
        services_group_id=services_group_id,
        office_group_name=os.getenv("SPLITWISE_OFFICE_GROUP_NAME", "Office"),
        services_group_name=os.getenv("SPLITWISE_OFFICE_SERVICES_GROUP_NAME", "Office Servicios"),
        user_ids=user_ids,
        business_groups=business_groups,
        cross_group_aliases=cross_group_aliases,
        currency_code=os.getenv("CURRENCY_CODE", "ARS").strip().upper(),
        min_amount=money(os.getenv("MIN_AMOUNT", "0.01")),
        dry_run=_bool_env("DRY_RUN", True),
        mark_as_payment=_bool_env("SPLITWISE_MARK_AS_PAYMENT", False),
        state_file=os.getenv("STATE_FILE", "state/pending_run.json"),
        schedule_time=os.getenv("SCHEDULE_TIME", "06:00"),
        schedule_timezone=os.getenv("SCHEDULE_TIMEZONE", "America/Buenos_Aires"),
    )


def _int_env(name: str, required: bool) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError as exc:
        if required:
            raise ConfigError(f"{name} must be an integer.") from exc
        return 0


def _auth_token_for_mode(auth_mode: str) -> str:
    if auth_mode == "oauth2":
        return (
            os.getenv("SPLITWISE_OAUTH2_ACCESS_TOKEN")
            or os.getenv("SPLITWISE_ACCESS_TOKEN")
            or ""
        ).strip()
    return (os.getenv("SPLITWISE_API_KEY") or "").strip()


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _loads_json(raw: str, env_name: str) -> Any:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{env_name} is not valid JSON: {exc}") from exc


def _parse_user_ids(raw: str) -> dict[str, int]:
    data = _loads_json(raw, "SPLITWISE_USERS_JSON")
    if not isinstance(data, dict):
        raise ConfigError("SPLITWISE_USERS_JSON must be an object.")

    result: dict[str, int] = {}
    for alias, value in data.items():
        user_id: int
        if isinstance(value, dict):
            raw_id = value.get("id", value.get("splitwise_id", value.get("user_id", 0)))
            user_id = int(raw_id or 0)
        else:
            user_id = int(value or 0)
        result[str(alias)] = user_id
    return result


def _parse_business_groups(raw: str) -> tuple[BusinessGroup, ...]:
    data = _loads_json(raw, "BUSINESS_GROUPS_JSON")
    if not isinstance(data, dict):
        raise ConfigError("BUSINESS_GROUPS_JSON must be an object.")

    groups: list[BusinessGroup] = []
    for name, payload in data.items():
        if not isinstance(payload, dict):
            raise ConfigError(f"Business group {name} must be an object.")
        admins = _string_tuple(payload.get("admins", ()))
        employees = _string_tuple(payload.get("employees", ()))
        if not admins:
            raise ConfigError(f"Business group {name} must have at least one admin.")
        groups.append(BusinessGroup(str(name), admins, employees))
    return tuple(groups)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list | tuple):
        return tuple(str(part).strip() for part in value if str(part).strip())
    raise ConfigError("Expected a string or list of strings.")
