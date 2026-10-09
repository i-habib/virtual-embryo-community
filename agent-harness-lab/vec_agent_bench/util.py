from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
from scipy import sparse


def dense(x) -> np.ndarray:
    return x.toarray() if sparse.issparse(x) else np.asarray(x)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finite_nonnegative(x) -> bool:
    if sparse.issparse(x):
        values = x.data
    else:
        values = np.asarray(x)
    return bool(np.isfinite(values).all() and (values >= 0).all())


REDACTED = "<redacted>"

# Words that mark a value as a credential when they appear in a flag name or
# a NAME=value pair, e.g. --api-key, OPENAI_API_KEY=..., token=..., --password.
_SECRET_WORD = r"(?:key|token|secret|password|passwd)"
_FLAG_NAME_RE = re.compile(rf"(?i)^--?[A-Za-z0-9_-]*{_SECRET_WORD}$")
_FLAG_VALUE_RE = re.compile(rf"(?i)(--?[A-Za-z0-9_-]*{_SECRET_WORD})(\s+)(\S+)")
_ASSIGN_RE = re.compile(rf"(?i)([A-Za-z0-9_.-]*{_SECRET_WORD})=(\S+)")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)(\S+)")
# Bare tokens with well-known prefixes (OpenAI/Anthropic-style sk-, GitHub, Hugging Face, Slack).
_TOKEN_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}"
    r"|hf_[A-Za-z0-9]{16,}|xox[abprs]-[A-Za-z0-9-]{8,})"
)


def redact_text(text: str) -> str:
    """Mask secret-looking values in a command string before it is logged.

    This only affects what is written to trace.jsonl. The command that runs is unchanged.
    """
    text = _FLAG_VALUE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    text = _ASSIGN_RE.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    text = _BEARER_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    return _TOKEN_PREFIX_RE.sub(REDACTED, text)


def redact_argv(argv: list[str]) -> list[str]:
    """Redact an argv list for logging. The value after a secret-named flag is masked."""
    out: list[str] = []
    hide_next = False
    for arg in argv:
        if hide_next:
            out.append(REDACTED)
            hide_next = False
        elif _FLAG_NAME_RE.match(arg):
            out.append(arg)
            hide_next = True
        else:
            out.append(redact_text(arg))
    return out
