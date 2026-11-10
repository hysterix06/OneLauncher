from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any

import keyring.errors
import pytest
import tomlkit
from pytest_mock import MockerFixture

import onelauncher.config_manager
from onelauncher import install_game
from onelauncher.config import ConfigFieldMetadata, ConfigValWithMetadata
from onelauncher.game_account_config import GameAccountConfig
from onelauncher.program_config import ProgramConfig

test_key_val_params: list[tuple[dict[str, Any], str]] = [
    ({"key": "val"}, 'key = "val"\n'),
    (
        {"key": ConfigValWithMetadata(value="val", metadata=ConfigFieldMetadata(None))},
        'key = "val"\n',
    ),
    (
        {
            "key": ConfigValWithMetadata(
                value="val", metadata=ConfigFieldMetadata("Helpful words")
            )
        },
        dedent(
            text="""\
            # Helpful words
            key = "val"
            """
        ),
    ),
    (
        {"key": ConfigValWithMetadata(value=None, metadata=ConfigFieldMetadata(None))},
        "# key = \n",
    ),
    (
        {
            "key": ConfigValWithMetadata(
                value=None, metadata=ConfigFieldMetadata("Helpful words")
            )
        },
        dedent(
            text="""\
            # Helpful words
            # key = 
            """
        ),
    ),
]

test_table_params = [
    ({"table": data_dict}, f"[table]\n{final_output}")
    for data_dict, final_output in test_key_val_params
]

test_table_and_comments_order_params: list[tuple[dict[str, Any], str]] = [
    (
        {
            "table": {
                "table_key": ConfigValWithMetadata(
                    value=0, metadata=ConfigFieldMetadata("Table key comment")
                )
            },
            "key": ConfigValWithMetadata(
                value=1, metadata=ConfigFieldMetadata("Comment")
            ),
        },
        dedent(
            text="""\
            # Comment
            key = 1

            [table]
            # Table key comment
            table_key = 0
            """
        ),
    ),
]

test_val_types_params: list[tuple[dict[str, Any], str]] = [
    ({"key": "val"}, 'key = "val"\n'),
    ({"key": 123}, "key = 123\n"),
    ({"key": 123.456}, "key = 123.456\n"),
    ({"key": True}, "key = true\n"),
    ({"key": False}, "key = false\n"),
    ({"key": ["a", 2, True]}, 'key = ["a", 2, true]\n'),
    ({"array": [1, 2]}, "array = [1, 2]\n"),
    ({"empty_array": []}, "empty_array = []\n"),
    (
        {
            "key": datetime(
                year=2000,
                month=2,
                day=12,
                hour=2,
                minute=24,
                second=19,
                tzinfo=timezone(timedelta(hours=7)),
            )
        },
        "key = 2000-02-12T02:24:19+07:00\n",
    ),
    # Table
    (
        {"table": {"key": "val"}},
        dedent(
            text="""\
            [table]
            key = "val"
            """
        ),
    ),
    ({"empty_table": {}}, ""),
    # Table with description
    (
        {
            "table": ConfigValWithMetadata(
                value={"key": "val"}, metadata=ConfigFieldMetadata(help="Helpful words")
            )
        },
        dedent(
            text="""\
            [table]
            key = "val"
            """
        ),
    ),
    # List of tables
    (
        {"tables": [{"key": "value"}, {"key": "value"}]},
        dedent(
            text="""\
            [[tables]]
            key = "value"

            [[tables]]
            key = "value"
            """
        ),
    ),
]


@pytest.mark.parametrize(
    ("data_dict", "final_toml_output"),
    test_key_val_params
    + test_table_params
    + test_table_and_comments_order_params
    + test_val_types_params,
)
def test_convert_to_toml(  # type: ignore[misc]
    data_dict: dict[str, Any | ConfigValWithMetadata], final_toml_output: str
) -> None:
    container = tomlkit.document()
    onelauncher.config_manager.convert_to_toml(data_dict=data_dict, container=container)
    assert container.as_string() == final_toml_output


def test_allow_unknown_config_keys(tmp_path: Path) -> None:
    UNKNOWN_KEY_NAME = "test_unknown_key_name"
    assert not hasattr(ProgramConfig, UNKNOWN_KEY_NAME)

    config_path = tmp_path / "test_config.toml"
    # Initialize the config file
    onelauncher.config_manager.update_config_file(
        config=ProgramConfig(), config_file_path=config_path
    )
    with config_path.open(mode="a") as f:
        f.write(f"{UNKNOWN_KEY_NAME} = 3.14")

    onelauncher.config_manager.read_config_file(
        config_class=ProgramConfig, config_file_path=config_path
    )


class TestConfigManager:
    def test_delete_game_config(
        self,
        config_manager: onelauncher.config_manager.ConfigManager,
    ) -> None:
        game_id = config_manager.get_game_config_ids()[0]
        game_config_dir = config_manager.get_game_config_dir(game_id)
        assert next(game_config_dir.iterdir(), False)

        config_manager.delete_game_config(game_id)
        assert not game_config_dir.exists()

    def test_delete_game_config_exclude_install_dir(
        self,
        config_manager: onelauncher.config_manager.ConfigManager,
    ) -> None:
        game_id, game_config = install_game.get_default_game_config(
            installer=install_game.GAME_INSTALLERS[0], config_manager=config_manager
        )
        config_manager.update_game_config_file(game_id=game_id, config=game_config)
        game_config.game_directory.mkdir(parents=True)
        config_manager.delete_game_config(game_id, exclude_install_dir=True)
        assert game_config.game_directory.exists()


class TestConfigManagerKeyring:
    """Every keyring read can show a system password prompt to the user."""

    ACCOUNT = GameAccountConfig(username="player")

    def test_password_read_once_per_session(
        self,
        config_manager: onelauncher.config_manager.ConfigManager,
        mocker: MockerFixture,
    ) -> None:
        get_password = mocker.patch("keyring.get_password", return_value="secret")
        game_id = config_manager.get_game_config_ids()[0]

        for _ in range(5):
            assert (
                config_manager.get_game_account_password(game_id, self.ACCOUNT)
                == "secret"
            )
        get_password.assert_called_once()

    def test_missing_password_read_once_per_session(
        self,
        config_manager: onelauncher.config_manager.ConfigManager,
        mocker: MockerFixture,
    ) -> None:
        get_password = mocker.patch("keyring.get_password", return_value=None)
        game_id = config_manager.get_game_config_ids()[0]

        for _ in range(3):
            assert (
                config_manager.get_game_account_password(game_id, self.ACCOUNT) is None
            )
        get_password.assert_called_once()

    def test_denied_keyring_access_only_asked_once(
        self,
        config_manager: onelauncher.config_manager.ConfigManager,
        mocker: MockerFixture,
    ) -> None:
        get_password = mocker.patch(
            "keyring.get_password", side_effect=keyring.errors.KeyringLocked
        )
        game_id = config_manager.get_game_config_ids()[0]

        for _ in range(3):
            assert (
                config_manager.get_game_account_password(game_id, self.ACCOUNT) is None
            )
        get_password.assert_called_once()

    def test_saved_password_replaces_cached_value(
        self,
        config_manager: onelauncher.config_manager.ConfigManager,
        mocker: MockerFixture,
    ) -> None:
        get_password = mocker.patch("keyring.get_password", return_value="old")
        set_password = mocker.patch("keyring.set_password")
        game_id = config_manager.get_game_config_ids()[0]

        config_manager.get_game_account_password(game_id, self.ACCOUNT)
        config_manager.save_game_account_password(game_id, self.ACCOUNT, "new")

        assert config_manager.get_game_account_password(game_id, self.ACCOUNT) == "new"
        set_password.assert_called_once()
        get_password.assert_called_once()

    def test_failed_save_does_not_cache_unsaved_password(
        self,
        config_manager: onelauncher.config_manager.ConfigManager,
        mocker: MockerFixture,
    ) -> None:
        get_password = mocker.patch("keyring.get_password", return_value="old")
        mocker.patch("keyring.set_password", side_effect=keyring.errors.KeyringLocked)
        game_id = config_manager.get_game_config_ids()[0]

        config_manager.save_game_account_password(game_id, self.ACCOUNT, "new")

        assert config_manager.get_game_account_password(game_id, self.ACCOUNT) == "old"
        get_password.assert_called_once()

    def test_deleted_password_is_removed_from_cache(
        self,
        config_manager: onelauncher.config_manager.ConfigManager,
        mocker: MockerFixture,
    ) -> None:
        get_password = mocker.patch("keyring.get_password", return_value="secret")
        delete_password = mocker.patch("keyring.delete_password")
        game_id = config_manager.get_game_config_ids()[0]

        config_manager.get_game_account_password(game_id, self.ACCOUNT)
        config_manager.delete_game_account_password(game_id, self.ACCOUNT)
        get_password.return_value = None

        assert config_manager.get_game_account_password(game_id, self.ACCOUNT) is None
        delete_password.assert_called_once()
