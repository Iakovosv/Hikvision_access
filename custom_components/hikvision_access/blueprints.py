"""Install the bundled automation blueprint so it shows up in the UI.

Home Assistant only auto-populates blueprints that ship inside its own `automation`
integration, so a custom integration has to place its file in the config itself. The file is
written once and never overwritten, so a user's edits are kept and the setup never fails
because of a filesystem problem.
"""

from __future__ import annotations

import logging
import pathlib
import shutil

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_SOURCE = (
    pathlib.Path(__file__).parent
    / "blueprints"
    / "automation"
    / "hikvision_access"
    / "door_open_lights.yaml"
)
_TARGET = ("blueprints", "automation", "hikvision_access", "door_open_lights.yaml")


def _copy(target: pathlib.Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_SOURCE, target)


async def async_install_blueprint(hass: HomeAssistant) -> None:
    """Copy the lights blueprint into the config once, if it is not there yet."""

    target = pathlib.Path(hass.config.path(*_TARGET))
    if target.exists():
        return
    try:
        await hass.async_add_executor_job(_copy, target)
    except OSError as ex:
        _LOGGER.debug("Could not install the automation blueprint: %s", ex)
