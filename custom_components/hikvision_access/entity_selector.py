"""An entity selector that also accepts an empty selection.

The notification and announcement fields start empty and stay empty until the user picks an
entity, but the stock `EntitySelector` rejects an empty string, so submitting the settings
page with the announcement left off failed with "Entity is neither a valid entity ID nor a
valid UUID" and nothing was saved. This selector passes an empty value through untouched
and otherwise behaves exactly like the stock one, so the frontend still shows a picker.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import selector


class OptionalEntitySelector(selector.EntitySelector):
    """An entity selector whose value may be empty."""

    def __call__(self, data: Any) -> str | list[str]:
        """Validate the selection, allowing an empty one."""

        if data is None or (isinstance(data, str) and not data.strip()):
            return ""
        return super().__call__(data)
