"""Unit tests — run: python -m pytest tests/test_bot.py -v"""
import sys, os, time, tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest.mock as mock

# Comprehensive discord mock — must cover all sub-modules before any bot import
_discord_mock = mock.MagicMock()
_discord_mock.ui = mock.MagicMock()
_discord_mock.ui.View = object
_discord_mock.ui.Button = mock.MagicMock()
_discord_mock.ui.Select = mock.MagicMock()
_discord_mock.ui.Modal = mock.MagicMock()
_discord_mock.ui.TextInput = mock.MagicMock()
_discord_mock.ui.UserSelect = mock.MagicMock()
_discord_mock.ui.ChannelSelect = mock.MagicMock()
_discord_mock.ui.RoleSelect = mock.MagicMock()
_discord_mock.ui.LayoutView = object
_discord_mock.ui.Container  = mock.MagicMock()
_discord_mock.ui.TextDisplay = mock.MagicMock()
_discord_mock.ui.Separator  = mock.MagicMock()
_discord_mock.ui.ActionRow  = mock.MagicMock()
_discord_mock.ui.Section    = mock.MagicMock()
_discord_mock.ui.Thumbnail  = mock.MagicMock()
_discord_mock.ui.MediaGallery = mock.MagicMock()
_discord_mock.components = mock.MagicMock()
_discord_mock.app_commands = mock.MagicMock()
_discord_mock.ButtonStyle   = mock.MagicMock()
_discord_mock.TextStyle     = mock.MagicMock()
_discord_mock.SelectOption  = mock.MagicMock()
_discord_mock.ChannelType   = mock.MagicMock()
_discord_mock.Intents       = mock.MagicMock()
_discord_mock.Intents.default.return_value = mock.MagicMock()
_discord_mock.Forbidden     = Exception
_discord_mock.HTTPException = Exception
_discord_mock.Member        = mock.MagicMock()
_discord_mock.Interaction   = mock.MagicMock()
_discord_mock.File          = mock.MagicMock()
_discord_mock.Embed         = mock.MagicMock()
_discord_mock.PermissionOverwrite = mock.MagicMock()

sys.modules["discord"]                 = _discord_mock
sys.modules["discord.ui"]              = _discord_mock.ui
sys.modules["discord.ext"]             = mock.MagicMock()
sys.modules["discord.ext.commands"]    = mock.MagicMock()
sys.modules["discord.ext.tasks"]       = mock.MagicMock()
sys.modules["discord.app_commands"]    = _discord_mock.app_commands
sys.modules["discord.components"]      = _discord_mock.components


def test_slugify():
    from core.shared import slugify
    assert slugify("Survey Corps") == "survey_corps"
    assert slugify("  Hello World  ") == "hello_world"
    assert slugify("café") == "caf"


def test_is_url():
    from core.shared import is_url
    assert is_url("https://example.com/img.png") is True
    assert is_url("http://example.com") is True
    assert is_url("not a url") is False
    assert is_url("") is False


def test_format_currency():
    from core.shared import format_currency
    cfg = {"currency_name": "Gold", "currency_emoji": "🪙"}
    assert "Gold" in format_currency(100, cfg)
    assert "100" in format_currency(100, cfg)
    assert "🪙" in format_currency(50, cfg)

    cfg_no_emoji = {"currency_name": "Coins", "currency_emoji": ""}
    result = format_currency(0, cfg_no_emoji)
    assert "Coins" in result


def test_xp_level_functions():
    from core.shared import _xp_for_level, _get_level
    assert _xp_for_level(1) == 100
    assert _xp_for_level(2) == 400
    assert _xp_for_level(3) == 900
    assert _get_level(0) == 1
    assert _get_level(399) == 1
    assert _get_level(400) == 2
    assert _get_level(899) == 2
    assert _get_level(900) == 3
    assert _get_level(10000) >= 10


def test_json_save_load():
    from core.shared import _save_json, _load_json
    tmp = Path(tempfile.mktemp(suffix=".json"))
    data = {"key": "value", "num": 42, "list": [1, 2, 3]}
    _save_json(tmp, data)
    loaded = _load_json(tmp, {})
    assert loaded["key"] == "value"
    assert loaded["num"] == 42
    assert loaded["list"] == [1, 2, 3]
    os.unlink(tmp)


def test_default_config_keys():
    from core.shared import DEFAULT_CONFIG
    required = [
        "language", "roles", "factions", "ranks",
        "logs_channel", "mission_channels", "mission_log_channels",
        "inheritance_races", "squad_max_members", "squad_creator_ranks",
        "mindless_syringe_item", "mindless_fluid_item", "xp_enabled",
        "character_creation_role", "bloodline_mindless_eligible",
    ]
    for key in required:
        assert key in DEFAULT_CONFIG, f"Missing DEFAULT_CONFIG key: {key}"


def test_lang_keys_exist():
    from core.shared import LANG
    check_keys = [
        "mission_title", "job_title", "squad_title",
        "mindless_title", "xp_title", "backstory_tab", "journal_tab",
        "logs_setup_title", "backup_title",
        "transfer_btn", "admin_grant_btn", "admin_view_profile_btn",
        "mindless_revert_btn", "no_creation_role",
        "mindless_cannot_inject_shifter", "mindless_injected_notify",
    ]
    for lang in ("th", "en"):
        for key in check_keys:
            assert key in LANG[lang], f"Missing LANG[{lang}][{key}]"


def test_get_player_squad_no_squad():
    from core.shared import get_player_squad
    with mock.patch("core.shared._load_json", return_value={"squads": {}}):
        sid, sq = get_player_squad(12345, 67890)
        assert sid is None
        assert sq is None


def test_format_full_player_info():
    from core.shared import format_full_player_info
    player = {
        "name": "Eren",
        "age": "19",
        "gender": "Male",
        "faction": "Survey Corps",
        "rank": "Soldier",
        "bloodline": "Eldian",
        "balance": 500,
        "inventory": {},
    }
    with mock.patch("core.shared.load_items", return_value={"items": {}, "categories": {}, "category_order": []}):
        with mock.patch("core.shared.load_config", return_value={"language": "en"}):
            info = format_full_player_info(player, "Eren#1234", 1)
            assert "Eren" in info
            assert "Survey Corps" in info
            assert "500" in info


def test_can_become_mindless_shifter():
    from core.shared import can_become_mindless
    player_shifter = {"titan_power": "Attack Titan", "bloodline": "Eldian"}
    with mock.patch("core.shared.load_config", return_value={"bloodline_mindless_eligible": {}}):
        allowed, reason = can_become_mindless(1, player_shifter)
        assert allowed is False
        assert "shifter" in reason


def test_can_become_mindless_ackerman():
    from core.shared import can_become_mindless
    player_ack = {"titan_power": None, "bloodline": "Ackerman"}
    with mock.patch("core.shared.load_config", return_value={"bloodline_mindless_eligible": {}}):
        allowed, reason = can_become_mindless(1, player_ack)
        assert allowed is False


def test_can_become_mindless_normal():
    from core.shared import can_become_mindless
    player_normal = {"titan_power": None, "bloodline": "Eldian"}
    with mock.patch("core.shared.load_config", return_value={"bloodline_mindless_eligible": {}}):
        allowed, reason = can_become_mindless(1, player_normal)
        assert allowed is True


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
