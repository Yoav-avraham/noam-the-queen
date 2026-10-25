"""python-i18n setup for the synchronizer service.

Centralizes all localization configuration so it can be initialized once at
startup (``configure_i18n``) instead of relying on import-time side effects.
Translations are served from JSON catalogs under ``translations/`` and missing
or unknown locales fall back to Hebrew.
"""

from __future__ import annotations

from enum import StrEnum
import logging
from pathlib import Path

import i18n

logger = logging.getLogger(__name__)

_TRANSLATIONS_DIR = Path(__file__).parent / "translations"
_configured = False


class Locale(StrEnum):
    """Locales the synchronizer ships catalogs for."""

    EN = "en"
    HE = "he"

    @classmethod
    def from_tag(cls, tag: str | None) -> Locale:
        """Reduce a raw locale tag to a supported locale, defaulting to Hebrew.

        Region subtags are dropped (``en-US`` -> ``en``) and a missing or
        unsupported tag resolves to Hebrew, so callers never have to normalize
        locale strings themselves.
        """
        if not tag:
            return cls.HE
        language = tag.replace("_", "-").split("-", 1)[0].lower()
        try:
            return cls(language)
        except ValueError:
            return cls.HE


def configure_i18n() -> None:
    """Configure python-i18n for the service. Idempotent; call once at startup.

    Loads JSON catalogs named ``<namespace>.<locale>.json`` from ``translations/``
    and sets Hebrew as the fallback locale so an absent or unknown
    ``WindowPayload.locale`` still yields a localized string.
    """
    global _configured
    if _configured:
        return

    i18n.set("file_format", "json")
    i18n.set("filename_format", "{namespace}.{locale}.{format}")
    i18n.set("fallback", Locale.HE)
    i18n.set("enable_memoization", True)
    if str(_TRANSLATIONS_DIR) not in i18n.load_path:
        i18n.load_path.append(str(_TRANSLATIONS_DIR))

    _configured = True
    logger.debug(
        "i18n configured",
        extra={
            "translations_dir": str(_TRANSLATIONS_DIR),
            "fallback_locale": Locale.HE,
        },
    )
