from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from decimal import Decimal

from .config import ConfigError, load_config
from .models import ArbitragePlan
from .runner import apply_or_resume, format_plan, load_remote_plan, validate_memberships
from .scheduler import next_run_at, sleep_until
from .splitwise_client import SplitwiseApiError, SplitwiseClient


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "discover":
            return _discover(args)
        if args.command == "validate":
            return _validate(args)
        if args.command == "balances":
            return _balances(args)
        if args.command == "plan":
            return _plan(args)
        if args.command == "run":
            return _run(args)
        if args.command == "schedule":
            return _schedule(args)
    except (ConfigError, SplitwiseApiError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="splitwise-arbitrage")
    parser.add_argument("--env-file", default=".env", help="Path to .env file.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("discover", help="List Splitwise groups and members.")
    subparsers.add_parser("validate", help="Validate config against Splitwise groups.")
    subparsers.add_parser("balances", help="Print Office and Office Servicios balances.")

    plan_parser = subparsers.add_parser("plan", help="Print the planned operations.")
    plan_parser.add_argument(
        "--scope",
        choices=("all", "internal", "cross"),
        default="all",
        help="Plan all operations, only dummy cleanup, or only cross-group transfer.",
    )
    plan_parser.add_argument(
        "--granular-internal",
        action="store_true",
        help="Show/apply one internal dummy expense per pair instead of one compact multi-user expense.",
    )
    plan_parser.add_argument(
        "--granular-cross",
        action="store_true",
        help="Show/apply cross-group transfer as pairwise expenses instead of one compact expense per group.",
    )
    plan_parser.add_argument("--json", action="store_true", help="Print raw JSON.")

    run_parser = subparsers.add_parser("run", help="Apply or dry-run the plan once.")
    run_parser.add_argument(
        "--scope",
        choices=("all", "internal", "cross"),
        default="all",
        help="Run all operations, only dummy cleanup, or only cross-group transfer.",
    )
    run_parser.add_argument(
        "--granular-internal",
        action="store_true",
        help="Show/apply one internal dummy expense per pair instead of one compact multi-user expense.",
    )
    run_parser.add_argument(
        "--granular-cross",
        action="store_true",
        help="Show/apply cross-group transfer as pairwise expenses instead of one compact expense per group.",
    )
    run_parser.add_argument("--apply", action="store_true", help="Write to Splitwise even if DRY_RUN=true.")

    schedule_parser = subparsers.add_parser("schedule", help="Run daily at SCHEDULE_TIME.")
    schedule_parser.add_argument("--apply", action="store_true", help="Write to Splitwise even if DRY_RUN=true.")
    return parser


def _client(args: argparse.Namespace, require_runtime: bool = True) -> tuple[object, SplitwiseClient]:
    config = load_config(args.env_file, require_runtime=require_runtime)
    return config, SplitwiseClient(config)


def _discover(args: argparse.Namespace) -> int:
    config, client = _client(args, require_runtime=False)
    if not config.api_key:
        raise ConfigError("SPLITWISE_API_KEY is required for discover.")
    groups = client.get_groups()
    for group in groups:
        group_id = int(group.get("id") or 0)
        full_group = client.get_group(group_id) if group_id else group
        print(f"{full_group.get('name')} | group_id={full_group.get('id')}")
        for member in full_group.get("members", []) or []:
            name = " ".join(
                part for part in [member.get("first_name"), member.get("last_name")] if part
            )
            email = member.get("email") or ""
            print(f"  - user_id={member.get('id')} | {name} | {email}")
    return 0


def _validate(args: argparse.Namespace) -> int:
    config, client = _client(args)
    messages = validate_memberships(config, client)
    if messages:
        print("Validation issues:")
        for message in messages:
            print(f"- {message}")
        return 1
    print("Config OK: groups and tracked users are present.")
    return 0


def _balances(args: argparse.Namespace) -> int:
    config, client = _client(args, require_runtime=False)
    if not config.api_key:
        raise ConfigError(
            "SPLITWISE_API_KEY is required for balances."
            if config.auth_mode == "api_key"
            else "SPLITWISE_OAUTH2_ACCESS_TOKEN is required for balances."
        )
    if not config.office_group_id or not config.services_group_id:
        raise ConfigError(
            "SPLITWISE_OFFICE_GROUP_ID and SPLITWISE_OFFICE_SERVICES_GROUP_ID are required."
        )

    for label, group_id in (
        (config.office_group_name, config.office_group_id),
        (config.services_group_name, config.services_group_id),
    ):
        group = client.get_group(group_id)
        print(f"\n{label}: {group.get('name')} ({group.get('id')})")
        for member in group.get("members", []) or []:
            name = " ".join(
                part for part in [member.get("first_name"), member.get("last_name")] if part
            ) or "<sin nombre>"
            balances = [
                f"{balance.get('amount')} {balance.get('currency_code')}"
                for balance in member.get("balance", []) or []
            ]
            print(
                f"  {name} | user_id={member.get('id')} | "
                f"balance={', '.join(balances) if balances else '0.00'}"
            )
    return 0


def _plan(args: argparse.Namespace) -> int:
    config, client = _client(args)
    plan = load_remote_plan(
        config,
        client,
        scope=args.scope,
        compact_internal=not args.granular_internal,
        compact_cross=not args.granular_cross,
    )
    if args.json:
        print(_plan_json(plan))
    else:
        print(format_plan(plan))
    return 0


def _run(args: argparse.Namespace) -> int:
    config, client = _client(args)
    plan = load_remote_plan(
        config,
        client,
        scope=args.scope,
        compact_internal=not args.granular_internal,
        compact_cross=not args.granular_cross,
    )
    print(format_plan(plan))
    if not plan.operations:
        print("\nNo operations to apply.")
        return 0
    if config.dry_run and not args.apply:
        print("\nDRY_RUN=true: no writes sent to Splitwise.")
        return 0
    applied = apply_or_resume(config, client, plan)
    print(f"\nApplied {applied} new operations. Pending state is clear.")
    return 0


def _schedule(args: argparse.Namespace) -> int:
    config, _ = _client(args)
    while True:
        target = next_run_at(config)
        print(f"Next run: {target.isoformat()}")
        sleep_until(target)
        run_args = argparse.Namespace(
            env_file=args.env_file,
            apply=args.apply,
            scope="all",
            granular_internal=False,
            granular_cross=False,
            command="run",
        )
        result = _run(run_args)
        if result != 0:
            print(f"Run failed with exit code {result}", file=sys.stderr)


def _plan_json(plan: ArbitragePlan) -> str:
    def convert(value: object) -> object:
        if isinstance(value, Decimal):
            return f"{value:.2f}"
        if isinstance(value, tuple):
            return list(value)
        return value

    return json.dumps(asdict(plan), default=convert, indent=2, sort_keys=True)
