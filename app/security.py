from __future__ import annotations

import re

INSTRUCTION_OVERRIDE = re.compile(
    r"\b(?:ignore|disregard|override|bypass)\b.{0,60}"
    r"\b(?:previous|prior|system|developer|safety)\b.{0,30}\binstructions?\b",
    re.IGNORECASE,
)
SECRET_EXFILTRATION = re.compile(
    r"\b(?:reveal|print|return|show|send|exfiltrate)\b.{0,60}"
    r"\b(?:system prompt|developer message|api[-_ ]?key|password|secret|token)\b",
    re.IGNORECASE,
)
ROLE_IMPERSONATION = re.compile(
    r"\b(?:you are now|act as)\b.{0,40}\b(?:system|developer|administrator|root)\b",
    re.IGNORECASE,
)
REMOTE_IMAGE = re.compile(
    r"!\[[^\]]*]\(\s*https?://|<img\b[^>]*\bsrc\s*=\s*['\"]?https?://",
    re.IGNORECASE,
)
SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


class UnsafePromptError(ValueError):
    pass


def security_flags(text: str) -> tuple[str, ...]:
    flags: list[str] = []
    if INSTRUCTION_OVERRIDE.search(text) or ROLE_IMPERSONATION.search(text):
        flags.append("instruction_override")
    if SECRET_EXFILTRATION.search(text):
        flags.append("secret_exfiltration")
    if REMOTE_IMAGE.search(text):
        flags.append("remote_content")
    return tuple(flags)


def reject_direct_prompt_injection(question: str) -> None:
    flags = security_flags(question)
    if "instruction_override" in flags or "secret_exfiltration" in flags:
        raise UnsafePromptError(
            "The question contains instruction-override or secret-extraction language."
        )


def sanitize_untrusted_text(text: str) -> tuple[str, tuple[str, ...]]:
    flags = security_flags(text)
    if not flags:
        return text, ()
    safe_segments: list[str] = []
    for segment in SENTENCE_BOUNDARY.split(text):
        segment = segment.strip()
        if not segment:
            continue
        if security_flags(segment):
            safe_segments.append("[Potential embedded instruction removed].")
        else:
            safe_segments.append(segment)
    return " ".join(safe_segments), flags


def validate_model_output(content: str) -> None:
    if REMOTE_IMAGE.search(content):
        raise RuntimeError("The configured model returned unsafe remote image markup.")
