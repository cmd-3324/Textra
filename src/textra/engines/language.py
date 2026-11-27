"""Language-name translation for the engine adapters.

The rest of the application speaks one vocabulary - the code in
``TEXTRA_OCR_LANGUAGE`` - and each adapter maps it into whatever its own
library expects. Keeping the translation here, rather than inline in an engine,
makes the mapping reviewable and testable without loading a model.
"""

from __future__ import annotations

from ..domain.errors import ConfigurationError

#: RapidOCR recognition models, taken from its ``LangRec`` enumeration.
RAPIDOCR_LANGUAGES = frozenset(
    {
        "arabic",
        "ch",
        "chinese_cht",
        "cyrillic",
        "devanagari",
        "el",
        "en",
        "eslav",
        "japan",
        "ka",
        "korean",
        "latin",
        "ta",
        "te",
        "th",
    }
)

#: Convenience aliases for the codes users actually type.
_ALIASES: dict[str, str] = {
    "ar": "arabic",
    "az": "latin",
    "de": "latin",
    "en-us": "en",
    "en_gb": "en",
    "es": "latin",
    "fa": "arabic",
    "fr": "latin",
    "he": "arabic",
    "hi": "devanagari",
    "it": "latin",
    "ja": "japan",
    "ko": "korean",
    "nl": "latin",
    "pl": "latin",
    "pt": "latin",
    "ru": "cyrillic",
    "sv": "latin",
    "tr": "latin",
    "uk": "cyrillic",
    "ur": "arabic",
    "zh": "ch",
    "zh-cn": "ch",
    "zh-hans": "ch",
    "zh-hant": "chinese_cht",
    "zh-tw": "chinese_cht",
}


def rapidocr_language(code: str) -> str:
    """Map a language code to a RapidOCR ``lang_type``.

    A code RapidOCR has no model for is a configuration error, not a silent
    fallback to English: recognising Persian with an English model produces
    confident nonsense, which is worse than refusing to run.
    """
    cleaned = code.strip().lower()
    if cleaned in RAPIDOCR_LANGUAGES:
        return cleaned
    alias = _ALIASES.get(cleaned)
    if alias is not None:
        return alias
    # A Tesseract-style compound code such as "eng+fas" cannot map to one
    # RapidOCR model either.
    raise ConfigurationError(
        f"RapidOCR has no model for the language '{code}'. "
        f"Use one of: {', '.join(sorted(RAPIDOCR_LANGUAGES))}, or switch to the "
        "tesseract engine for that script.",
        context={"language": code, "engine": "rapidocr"},
    )


__all__ = ["RAPIDOCR_LANGUAGES", "rapidocr_language"]
