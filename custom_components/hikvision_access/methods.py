"""Human-readable names for the verify modes the terminal reports.

`hassfest` forbids a `logbook` translation category and the notification templates are built
at runtime, so the labels live here rather than in the translation files. Both the logbook
and the notifier read them, keyed by language with an English fallback.
"""

from __future__ import annotations

from typing import Final

EN: Final[dict[str, str]] = {
    "access": "access",
    "card": "card",
    "fp": "fingerprint",
    "cardAndPw": "card + PIN",
    "fpAndPw": "fingerprint + PIN",
    "fpOrCard": "fingerprint or card",
    "fpAndCard": "fingerprint + card",
    "fpAndCardAndPw": "fingerprint + card + PIN",
    "fpOrPw": "fingerprint or PIN",
    "cardOrPw": "card or PIN",
    "cardOrFpOrPw": "card, fingerprint or PIN",
}

EL: Final[dict[str, str]] = {
    "access": "πρόσβαση",
    "card": "κάρτα",
    "fp": "δακτυλικό αποτύπωμα",
    "cardAndPw": "κάρτα + PIN",
    "fpAndPw": "δακτυλικό + PIN",
    "fpOrCard": "δακτυλικό ή κάρτα",
    "fpAndCard": "δακτυλικό + κάρτα",
    "fpAndCardAndPw": "δακτυλικό + κάρτα + PIN",
    "fpOrPw": "δακτυλικό ή PIN",
    "cardOrPw": "κάρτα ή PIN",
    "cardOrFpOrPw": "κάρτα, δακτυλικό ή PIN",
}

METHODS: Final[dict[str, dict[str, str]]] = {"en": EN, "el": EL}


def method_label(language: str, key: str | None) -> str:
    """Return the label for a verify mode, falling back to the raw key and English."""

    table = METHODS.get(language, EN)
    return table.get(key or "", (key or EN["access"]))
