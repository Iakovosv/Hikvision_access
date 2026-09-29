"""Every shipped translation must resolve, and must not lose keys to placeholder drift.

A missing or malformed translation does not fall back to English in the UI: Home Assistant
shows the raw key, so a user with a Greek interface reads "cannot_list" instead of the
sentence that names the missing device permission. Home Assistant also drops a localized
string when its placeholders differ from the English one, which is the same silent failure.
These tests guard both.
"""

from __future__ import annotations

import json
import pathlib
import string

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from custom_components.hikvision_access.const import DOMAIN

from tests.test_integration import _setup

TRANSLATIONS = pathlib.Path(__file__).parent.parent / "custom_components" / DOMAIN / "translations"
LANGUAGES = sorted(path.stem for path in TRANSLATIONS.glob("*.json") if path.stem != "en")


def _flatten(node, prefix: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        out: dict[str, str] = {}
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else key))
        return out
    return {prefix: node}


def _placeholders(value: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(value) if name}


def test_every_language_has_the_english_keys() -> None:
    """A localized file must cover every key English has, with the same placeholders."""

    english = _flatten(json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8")))

    for language in LANGUAGES:
        localized = _flatten(json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8")))
        assert set(english) - set(localized) == set(), f"{language} is missing keys"
        assert set(localized) - set(english) == set(), f"{language} has unknown keys"

        for key, value in localized.items():
            reference = english[key]
            if "::" in value:  # a [%key:...%] reference to a core string, no placeholders
                continue
            assert _placeholders(value) == _placeholders(reference), f"{language}.{key} placeholders differ"


@pytest.mark.parametrize("language", ["en", *LANGUAGES])
async def test_abort_message_resolves_in_every_language(hass: HomeAssistant, monkeypatch, language) -> None:
    """The person-list abort is a sentence in every shipped language, never a bare key."""

    await _setup(hass, monkeypatch)
    strings = await async_get_translations(hass, language, "options", [DOMAIN], config_flow=True)

    for reason in ("cannot_list", "not_loaded", "no_persons", "delete_cancelled"):
        key = f"component.{DOMAIN}.options.abort.{reason}"
        assert key in strings, f"{language} does not resolve {reason}"
        assert strings[key] != reason, f"{language} resolves {reason} to the raw key"
        assert "{error}" in strings[key] or reason != "cannot_list"
