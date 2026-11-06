from unittest.mock import MagicMock, patch

import pytest
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings

from apps.identity.management.commands.seed_e2e import Command

RUN_ID = "0b67ed38-25ef-4f52-bd1e-6b2510c2f7e1"


@pytest.mark.parametrize("database_marker", [None, "another-run"])
def test_seed_e2e_rejects_database_without_matching_run_marker(database_marker):
    cursor = MagicMock()
    cursor.fetchone.return_value = (database_marker,)
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    flush = patch(
        "apps.identity.management.commands.seed_e2e.call_command",
        side_effect=CommandError("flush was reached"),
    )

    with (
        override_settings(XRAY_ENV="test", XRAY_E2E_RUN_ID=RUN_ID),
        patch.object(connection, "settings_dict", {"NAME": "xray_test"}),
        patch.object(connection, "cursor", return_value=cursor_context),
        flush as call_command,
        pytest.raises(CommandError, match="isolated E2E database marker"),
    ):
        Command().handle(reset=True)

    call_command.assert_not_called()
    cursor.execute.assert_called_once()


def test_seed_e2e_rejects_missing_run_id_before_database_access():
    with (
        override_settings(XRAY_ENV="test", XRAY_E2E_RUN_ID=""),
        patch.object(connection, "settings_dict", {"NAME": "xray_test"}),
        patch.object(connection, "cursor") as cursor,
        pytest.raises(CommandError, match="isolated E2E database marker"),
    ):
        Command().handle(reset=True)

    cursor.assert_not_called()
