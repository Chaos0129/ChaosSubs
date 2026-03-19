import json
import re
import urllib.request
from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL

LANG_NAMES = {
    "ja": "Japanese",
    "en": "English",
    "ko": "Korean",
}

# Common prefixes the LLM might add before the actual translation
JUNK_PREFIXES = re.compile(
    r"^(翻译字幕[：:]|翻译[：:]|译文[：:]|中文翻译[：:]|字幕[：:]|"
    r"Translation[：:]|Translated[：:]|Chinese[：:])\s*",
    re.IGNORECASE,
)


def _get_source_lang(language: str = None) -> str:
    if language and language in LANG_NAMES:
        return LANG_NAMES[language]
    return "the source language"


def _clean_translation(text: str) -> str:
    """Strip junk prefixes and quotes from LLM output."""
    text = text.strip()
    text = JUNK_PREFIXES.sub("", text)
    # Remove wrapping quotes
    if len(text) >= 2 and text[0] in "\"'「『" and text[-1] in "\"'」』":
        text = text[1:-1]
    return text.strip()


def translate_batch(texts: list, language: str = None) -> list:
    """Translate a batch of subtitle texts to Simplified Chinese via Ollama."""
    source = _get_source_lang(language)
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    prompt = (
        f"Task: Translate {source} subtitles to natural Simplified Chinese.\n"
        "Rules:\n"
        "- Output ONLY the Chinese translation for each line\n"
        "- Keep the same numbering format: '1. 翻译内容'\n"
        "- Use natural Chinese word order, not literal translation\n"
        "- Translate colloquial/slang expressions to natural Chinese equivalents\n"
        "- Do NOT add any prefix like '翻译：' or explanation\n"
        "- Do NOT add quotes around translations\n\n"
        f"{numbered}"
    )

    data = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3},
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    response_text = result.get("response", "")
    return _parse_numbered_response(response_text, len(texts))


def _parse_numbered_response(text: str, expected_count: int) -> list:
    """Parse numbered lines from LLM response."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    translations = []

    for line in lines:
        for sep in [". ", "、", ": ", "） ", ") "]:
            idx = line.find(sep)
            if idx != -1 and line[:idx].strip().isdigit():
                line = line[idx + len(sep):]
                break
        translations.append(_clean_translation(line))

    if len(translations) < expected_count:
        translations.extend(["[翻译失败]"] * (expected_count - len(translations)))
    return translations[:expected_count]


def translate_single(text: str, language: str = None) -> str:
    """Fallback: translate a single subtitle line."""
    source = _get_source_lang(language)
    prompt = (
        f"Translate the following {source} subtitle to natural Simplified Chinese.\n"
        "Rules:\n"
        "- Output ONLY the Chinese translation, nothing else\n"
        "- Use natural Chinese word order\n"
        "- Do NOT add any prefix or explanation\n\n"
        f"{text}"
    )

    data = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3},
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    return _clean_translation(result.get("response", "[翻译失败]"))
