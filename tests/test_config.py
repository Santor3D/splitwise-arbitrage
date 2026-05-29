from __future__ import annotations

from splitwise_arbitrage.config import load_config


def test_load_config_reads_auth_mode_and_group_ids(tmp_path, monkeypatch) -> None:
    for name in (
        "SPLITWISE_AUTH_MODE",
        "SPLITWISE_API_KEY",
        "SPLITWISE_OFFICE_GROUP_ID",
        "SPLITWISE_OFFICE_SERVICES_GROUP_ID",
        "SPLITWISE_USERS_JSON",
        "BUSINESS_GROUPS_JSON",
        "CROSS_GROUP_ALIASES",
    ):
        monkeypatch.delenv(name, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SPLITWISE_AUTH_MODE=api_key",
                "SPLITWISE_API_KEY=secret",
                "SPLITWISE_OFFICE_GROUP_ID=65892534",
                "SPLITWISE_OFFICE_SERVICES_GROUP_ID=82456505",
                'SPLITWISE_USERS_JSON={"Fran":46993750}',
                'BUSINESS_GROUPS_JSON={"InmoClick":{"admins":["Fran"],"employees":[]}}',
                "CROSS_GROUP_ALIASES=Fran",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(env_file))

    assert config.auth_mode == "api_key"
    assert config.api_key == "secret"
    assert config.office_group_id == 65892534
    assert config.services_group_id == 82456505
