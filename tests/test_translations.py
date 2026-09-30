# Copyright (c) 2026 Iakovosv. All rights reserved.
# Personal use only. Commercial use requires written permission.
# See LICENSE and COMMERCIAL.md. Redistribution prohibited.

"""Every string the flow can display must resolve, in every shipped language.

A missing translation does not fall back to English in the UI: Home Assistant shows the raw
key, so a Greek user reads "cannot_list" or "insufficient_permission" instead of the sentence
that names the missing device permission. Home Assistant also drops a localized string whose
placeholders differ from English, which fails the same silent way.

Rather than listing the keys by hand (which is how `insufficient_permission` shipped raw), the
keys are read back from the source: every `reason=` and `errors["base"] =` literal must exist.
"""

from __future__ import annotations

import json
import pathlib
import re
import string

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from custom_components.hikvision_access.const import DOMAIN

from tests.test_integration import _setup

COMPONENT = pathlib.Path(__file__).parent.parent / "custom_components" / DOMAIN
TRANSLATIONS = COMPONENT / "translations"
LANGUAGES = sorted(path.stem for path in TRANSLATIONS.glob("*.json") if path.stem != "en")

# The literals a user can see. `reason=` is an abort, `errors["base"] =` a form error.
_ABORT_LITERAL = re.compile(r'reason="([a-z_]+)"')
_ERROR_LITERAL = re.compile(r'errors\["base"\] = "([a-z_]+)"')


def _flatten(node, prefix: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        out: dict[str, str] = {}
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else key))
        return out
    return {prefix: node}


def _placeholders(value: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(value) if name}


def _flow_literals() -> tuple[set[str], set[str]]:
    """Return the abort reasons and error keys that appear in the flow source."""

    source = (COMPONENT / "options_flow.py").read_text(encoding="utf-8")
    return set(_ABORT_LITERAL.findall(source)), set(_ERROR_LITERAL.findall(source))


def test_every_language_has_the_english_keys() -> None:
    """A localized file must cover every English key, with the same placeholders."""

    english = _flatten(json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8")))

    for language in LANGUAGES:
        localized = _flatten(json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8")))
        assert set(english) - set(localized) == set(), f"{language} is missing keys"
        assert set(localized) - set(english) == set(), f"{language} has unknown keys"

        for key, value in localized.items():
            assert _placeholders(value) == _placeholders(english[key]), f"{language}.{key} placeholders differ"


def test_no_translation_uses_a_build_time_reference() -> None:
    """A custom integration never runs the translation build script.

    `[%key:common::...%]` is resolved by `script.translations` while Home Assistant Core is
    built. Custom components are loaded from disk as they are, so the reference reaches the
    browser untouched and the UI renders it literally. This shipped for the config-flow field
    labels: the setup dialog showed `[%key:common::config_flow::data::host%]` next to an input.
    """

    for path in (*TRANSLATIONS.glob("*.json"), COMPONENT / "strings.json"):
        for key, value in _flatten(json.loads(path.read_text(encoding="utf-8"))).items():
            assert "[%key:" not in value, f"{path.name}.{key} still holds a build-time reference"


def test_strings_json_matches_english() -> None:
    """strings.json is the file the UI is validated against and must equal English."""

    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
    assert strings == english


@pytest.mark.parametrize("language", ["en", *LANGUAGES])
def test_last_access_entities_are_translated(language: str) -> None:
    """The last-access entities have a name, and the binary sensor a word for on and off.

    The binary sensor can only read `on`/`off`, so without a state translation the UI
    shows the raw English default ("Detected"); the name of the person has its own sensor,
    which is why `sensor.last_access_person` must carry a name too.
    """

    entity = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))["entity"]

    assert entity["sensor"]["last_access_person"]["name"]
    states = entity["binary_sensor"]["last_access"]["state"]
    assert states["on"] and states["off"]
    assert states["on"] != states["off"]


@pytest.mark.parametrize("language", ["en", *LANGUAGES])
async def test_every_key_the_flow_uses_resolves(hass: HomeAssistant, monkeypatch, language) -> None:
    """No abort reason or form error can reach the user as a raw key."""

    await _setup(hass, monkeypatch)
    aborts, errors = _flow_literals()
    assert aborts and errors, "the flow literals were not found, the regex needs updating"

    options = await async_get_translations(hass, language, "options", [DOMAIN], config_flow=True)
    config = await async_get_translations(hass, language, "config", [DOMAIN], config_flow=True)

    for category, keys, table in (("abort", aborts, options), ("error", errors, options)):
        for key in sorted(keys):
            full = f"component.{DOMAIN}.options.{category}.{key}"
            assert full in table, f"{language} does not resolve {full}"

    # The config flow shares some error reasons with the options flow.
    for key in sorted(errors):
        full = f"component.{DOMAIN}.config.error.{key}"
        if full in config:
            continue
        assert f"component.{DOMAIN}.options.error.{key}" in options
