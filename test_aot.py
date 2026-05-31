"""Unit tests — run: python -m pytest test_aot.py -v"""
import sys, os, json, time, tempfile
sys.path.insert(0, os.path.dirname(__file__))

# Comprehensive discord mock — must cover all sub-modules before any bot import
import unittest.mock as mock

_discord_mock = mock.MagicMock()
_discord_mock.ui = mock.MagicMock()
_discord_mock.ui.LayoutView = object
_discord_mock.ui.Container  = mock.MagicMock()
_discord_mock.ui.TextDisplay = mock.MagicMock()
_discord_mock.ui.Separator  = mock.MagicMock()
_discord_mock.ui.ActionRow  = mock.MagicMock()
_discord_mock.ui.Button     = mock.MagicMock()
_discord_mock.ui.Select     = mock.MagicMock()
_discord_mock.ui.Modal      = mock.MagicMock()
_discord_mock.ui.TextInput  = mock.MagicMock()
_discord_mock.ui.Section    = mock.MagicMock()
_discord_mock.ui.Thumbnail  = mock.MagicMock()
_discord_mock.ui.MediaGallery = mock.MagicMock()
_discord_mock.ui.UserSelect = mock.MagicMock()
_discord_mock.ui.ChannelSelect = mock.MagicMock()
_discord_mock.ui.RoleSelect = mock.MagicMock()
_discord_mock.components = mock.MagicMock()
_discord_mock.app_commands = mock.MagicMock()
_discord_mock.ButtonStyle   = mock.MagicMock()
_discord_mock.TextStyle     = mock.MagicMock()
_discord_mock.SelectOption  = mock.MagicMock()
_discord_mock.ChannelType   = mock.MagicMock()
_discord_mock.Intents       = mock.MagicMock()
_discord_mock.Intents.default.return_value = mock.MagicMock()
_discord_mock.Forbidden     = Exception
_discord_mock.Member        = mock.MagicMock()
_discord_mock.Interaction   = mock.MagicMock()
_discord_mock.File          = mock.MagicMock()
_discord_mock.PermissionOverwrite = mock.MagicMock()
sys.modules["discord"]                 = _discord_mock
sys.modules["discord.ui"]              = _discord_mock.ui
sys.modules["discord.ext"]             = mock.MagicMock()
sys.modules["discord.ext.commands"]    = mock.MagicMock()
sys.modules["discord.ext.tasks"]       = mock.MagicMock()
sys.modules["discord.app_commands"]    = _discord_mock.app_commands
sys.modules["discord.components"]      = _discord_mock.components


def test_slugify():
    from aot_shared import slugify
    assert slugify("Survey Corps") == "survey_corps"
    assert slugify("  Hello World  ") == "hello_world"
    assert slugify("café") == "caf"


def test_is_url():
    from aot_shared import is_url
    assert is_url("https://example.com/img.png") is True
    assert is_url("http://example.com") is True
    assert is_url("not a url") is False
    assert is_url("") is False


def test_format_currency():
    from aot_shared import format_currency
    cfg = {"currency_name": "Gold", "currency_emoji": "🪙"}
    assert "Gold" in format_currency(100, cfg)
    assert "100" in format_currency(100, cfg)
    assert "🪙" in format_currency(50, cfg)

    cfg_no_emoji = {"currency_name": "Coins", "currency_emoji": ""}
    result = format_currency(0, cfg_no_emoji)
    assert "Coins" in result


def test_xp_level_functions():
    from aot_shared import _xp_for_level, _get_level
    # _xp_for_level(n) = 100 * n^2 — threshold to *reach* that level
    assert _xp_for_level(1) == 100
    assert _xp_for_level(2) == 400
    assert _xp_for_level(3) == 900
    # _get_level: you're level N when xp >= _xp_for_level(N) but < _xp_for_level(N+1)
    assert _get_level(0) == 1    # below level-2 threshold (400)
    assert _get_level(399) == 1  # still below 400
    assert _get_level(400) == 2  # exactly at level-2 threshold
    assert _get_level(899) == 2  # below level-3 threshold (900)
    assert _get_level(900) == 3  # exactly at level-3 threshold
    assert _get_level(10000) >= 10


def test_stamina_bar():
    from aot_shifter import _stamina_bar
    bar = _stamina_bar(50, 100)
    assert "50/100" in bar
    full = _stamina_bar(100, 100)
    assert "░" not in full

    empty = _stamina_bar(0, 100)
    assert "▓" not in empty


def test_regen_stamina():
    from aot_shifter import _regen_stamina
    now = time.time()
    player = {
        "stamina": 50,
        "max_stamina": 100,
        "stamina_last_regen": now - 400,
    }
    cfg = {"stamina_regen_interval_minutes": 5, "stamina_regen_amount": 10}
    result = _regen_stamina(player, cfg)
    assert result["stamina"] == 60

    # No regen if interval not passed
    player2 = {
        "stamina": 50,
        "max_stamina": 100,
        "stamina_last_regen": now - 60,
    }
    result2 = _regen_stamina(player2, cfg)
    assert result2["stamina"] == 50


def test_json_save_load():
    from aot_shared import DATA_DIR, _save_json, _load_json
    from pathlib import Path
    import tempfile, os
    tmp = Path(tempfile.mktemp(suffix=".json"))
    data = {"key": "value", "num": 42, "list": [1, 2, 3]}
    _save_json(tmp, data)
    loaded = _load_json(tmp, {})
    assert loaded["key"] == "value"
    assert loaded["num"] == 42
    assert loaded["list"] == [1, 2, 3]
    os.unlink(tmp)


def test_default_config_keys():
    from aot_shared import DEFAULT_CONFIG
    required = [
        "language", "roles", "factions", "ranks",
        "logs_channel", "mission_channels", "mission_log_channels",
        "inheritance_races", "squad_max_members", "squad_creator_ranks",
        "mindless_syringe_item", "mindless_fluid_item", "xp_enabled",
    ]
    for key in required:
        assert key in DEFAULT_CONFIG, f"Missing DEFAULT_CONFIG key: {key}"


def test_lang_keys_exist():
    from aot_shared import LANG
    check_keys = [
        "mission_title", "job_title", "squad_title",
        "mindless_title", "xp_title", "backstory_tab", "journal_tab",
        "logs_setup_title", "backup_title",
    ]
    for lang in ("th", "en"):
        for key in check_keys:
            assert key in LANG[lang], f"Missing LANG[{lang}][{key}]"


def test_get_player_squad_no_squad():
    from aot_shared import get_player_squad, DATA_DIR
    with mock.patch("aot_shared._load_json", return_value={"squads": {}}):
        sid, sq = get_player_squad(12345, 67890)
        assert sid is None
        assert sq is None


def test_format_full_player_info():
    from aot_shared import format_full_player_info
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
    with mock.patch("aot_shared.load_items", return_value={"items": {}, "categories": {}, "category_order": []}):
        with mock.patch("aot_shared.load_config", return_value={"language": "en"}):
            info = format_full_player_info(player, "Eren#1234", 1)
            assert "Eren" in info
            assert "Survey Corps" in info
            assert "500" in info


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
