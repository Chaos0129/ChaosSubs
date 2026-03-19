from dataclasses import dataclass
from pathlib import Path

MAX_LINE_CHARS = 20  # Max Chinese characters per line


@dataclass
class SrtEntry:
    index: int
    start: str
    end: str
    text: str


def seconds_to_srt_time(s: float) -> str:
    hours = int(s // 3600)
    minutes = int((s % 3600) // 60)
    secs = int(s % 60)
    millis = int(round((s - int(s)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def wrap_text(text: str, max_chars: int = MAX_LINE_CHARS) -> str:
    """Wrap long subtitle text into multiple lines."""
    text = text.strip()
    if len(text) <= max_chars:
        return text

    # Try to split at punctuation first
    punctuation = "，。、；！？,.;!? "
    lines = []
    current = ""

    for char in text:
        current += char
        if len(current) >= max_chars:
            # Look for nearby punctuation to break at
            best_break = -1
            for i in range(len(current) - 1, max(len(current) - 8, -1), -1):
                if i >= 0 and current[i] in punctuation:
                    best_break = i
                    break

            if best_break > 0:
                lines.append(current[:best_break + 1].strip())
                current = current[best_break + 1:]
            else:
                lines.append(current.strip())
                current = ""

    if current.strip():
        lines.append(current.strip())

    return "\n".join(lines)


def whisper_segments_to_srt(segments: list) -> list:
    entries = []
    for i, seg in enumerate(segments, 1):
        entries.append(SrtEntry(
            index=i,
            start=seconds_to_srt_time(seg["start"]),
            end=seconds_to_srt_time(seg["end"]),
            text=seg["text"].strip(),
        ))
    return entries


def write_srt(entries: list, path: Path) -> None:
    lines = []
    for entry in entries:
        lines.append(str(entry.index))
        lines.append(f"{entry.start} --> {entry.end}")
        lines.append(wrap_text(entry.text))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_srt(path: Path) -> list:
    text = path.read_text(encoding="utf-8")
    entries = []
    blocks = text.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            index = int(lines[0])
            times = lines[1].split(" --> ")
            content = "\n".join(lines[2:])
            entries.append(SrtEntry(
                index=index,
                start=times[0].strip(),
                end=times[1].strip(),
                text=content,
            ))
    return entries
