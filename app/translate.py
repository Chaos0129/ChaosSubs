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


def polish_batch(texts: list, context_before: list = None, context_after: list = None) -> list:
    """Polish Chinese subtitle translations with surrounding context for better quality."""
    # Build context section
    context_parts = []
    if context_before:
        context_parts.append("【前文（仅供参考，不要润色）】")
        for t in context_before[-3:]:  # last 3 lines before
            context_parts.append(f"  {t}")

    context_parts.append("\n【需要润色的字幕】")
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    context_parts.append(numbered)

    if context_after:
        context_parts.append("\n【后文（仅供参考，不要润色）】")
        for t in context_after[:3]:  # first 3 lines after
            context_parts.append(f"  {t}")

    context_text = "\n".join(context_parts)

    prompt = (
        "你是字幕润色专家。根据上下文语境，将【需要润色的字幕】改写为更自然、口语化的中文。\n"
        "规则：\n"
        "- 结合前后文理解对话语境，确保润色后的语义连贯\n"
        "- 调整为符合中文习惯的语序\n"
        "- 把书面语改为口语\n"
        "- 保持原意不变\n"
        "- 润色后的字数不能超过原文的120%，也不能少于原文的80%\n"
        "- 只输出润色结果，保持编号格式：'1. 润色内容'\n"
        "- 不要输出前文和后文，只输出需要润色的部分\n\n"
        f"{context_text}"
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
    polished = _parse_numbered_response(response_text, len(texts))

    # Safety check: if polished text is way too long/short, keep original
    # Returns list of (text, was_polished, reason)
    results = []
    for orig, pol in zip(texts, polished):
        orig_len = len(orig)
        pol_len = len(pol)
        if orig_len > 0 and pol_len > orig_len * 2.0:
            results.append((orig, False, f"润色后过长({pol_len}字 > 原文{orig_len}字×200%)"))
        elif orig_len > 0 and pol_len < orig_len * 0.3:
            results.append((orig, False, f"润色后过短({pol_len}字 < 原文{orig_len}字×30%)"))
        elif pol == orig:
            results.append((pol, False, "润色结果与原文相同"))
        else:
            results.append((pol, True, ""))
    return results
