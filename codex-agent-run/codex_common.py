#!/usr/bin/env python3
"""Shared helpers for codex_lock.py, codex_launch.py and codex_package.py.

Standard library only (Python 3.11 or later, for tomllib).
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import secrets
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

SCHEMA = "codex-agent-run/1"

# Rules section 9: "Evidence is capped at 200 MB per file and 600 MB per team in total."
# 200 MB is read as 200,000,000 bytes, the smaller of the two readings.
MAX_EVIDENCE_FILE_BYTES = 200_000_000
TEAM_EVIDENCE_CAP_BYTES = 600_000_000
# Rules section 11: "A single prediction file may not exceed 1200 MB."
MAX_PREDICTION_FILE_BYTES = 1_200_000_000

SANDBOX_MODES = ("read-only", "workspace-write")
APPROVAL_POLICIES = ("untrusted", "on-failure", "on-request", "never")
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
HARNESS_FILES = ("codex_common.py", "codex_lock.py", "codex_launch.py", "codex_package.py")
# Flags this tool relies on, checked against `codex exec --help` at lock time.
REQUIRED_EXEC_FLAGS = (
    "--json", "--model", "--sandbox", "--cd", "--config", "--skip-git-repo-check",
    "--ignore-user-config", "--output-last-message", "--color",
)
MODEL_RE = re.compile(r"[A-Za-z0-9._:/\-]+")
CREDENTIAL_GLOBS = (
    "auth.json*", "mcp-auth.json*", ".credentials*", ".env", ".env.*", "*credential*.json",
    ".netrc", ".pypirc", ".npmrc", "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*",
    "id_ecdsa", "id_ecdsa.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.db", "*.db-wal",
    "*.sqlite", "*.sqlite3",
)
_SCAN_OVERLAP = 4096


class ToolError(Exception):
    """A refusal. The message says what to fix. Nothing is written after it."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id() -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}_{secrets.token_hex(4)}"


# ---------------------------------------------------------------- hashing and files

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_new(path: Path, data: bytes) -> None:
    """Create a file. Refuses (FileExistsError) when the file is already there."""
    with open(path, "xb") as fh:
        fh.write(data)


def write_json_new(path: Path, obj) -> None:
    write_new(path, (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def write_json_replace(path: Path, obj) -> None:
    """Only for state files this tool owns (launch_state.json). Never used for the lock."""
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_bytes())


def safe_rel(value: str) -> str:
    p = PurePosixPath(value)
    if not value or p.is_absolute() or ".." in p.parts:
        raise ToolError(f"predictions dir must be a relative path inside the workspace: {value!r}")
    return p.as_posix()


def tree_listing(root: Path) -> list[dict]:
    """Relative path, size and sha256 of every regular file under root (sorted)."""
    if not root.is_dir():
        return []
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.is_file():
                rows.append({"path": p.relative_to(root).as_posix(),
                             "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    return rows


def run_text(cmd: list[str], timeout: int = 120) -> str:
    try:
        cp = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"could not run {cmd[0]}: {exc}") from exc
    if cp.returncode != 0:
        err = cp.stderr.decode("utf-8", errors="replace")[:300]
        raise ToolError(f"`{' '.join(cmd)}` exited {cp.returncode}: {err}")
    return cp.stdout.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- credentials

def credential_hashes(codex_home: Path) -> frozenset:
    """SHA-256 of credential-named files in CODEX_HOME. Inputs with the same bytes are refused."""
    out = set()
    if codex_home.is_dir():
        for p in codex_home.iterdir():
            if p.is_file() and any(fnmatch.fnmatchcase(p.name.lower(), g)
                                   for g in ("auth.json*", "mcp-auth.json*", ".credentials*")):
                out.add(sha256_file(p))
    return frozenset(out)


def credential_reason(path: Path, forbidden: frozenset = frozenset()) -> str | None:
    names = {path.name, Path(os.path.realpath(path)).name}
    for name in names:
        low = name.lower()
        for glob in CREDENTIAL_GLOBS:
            if fnmatch.fnmatchcase(low, glob):
                return f"file name matches credential pattern {glob!r}"
    if forbidden and path.is_file() and sha256_file(path) in forbidden:
        return "has the same bytes as a credential file in CODEX_HOME"
    return None


# Patterns are written in fragments so that this file does not match its own scan.
_SK = "s" + "k-"
SECRET_PATTERNS = (
    ("anthropic-key", _SK + "ant-" + r"[A-Za-z0-9_\-]{20,}"),
    ("openai-style-key", r"(?<![A-Za-z0-9+/_\-])" + _SK + r"(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    ("github-token", r"gh[pousr]_[A-Za-z0-9]{30,}"),
    ("github-fine-grained-token", "github" + "_pat_" + r"[A-Za-z0-9_]{30,}"),
    ("aws-access-key", r"AKIA[0-9A-Z]{16}"),
    ("slack-token", r"xox[abprs]-[A-Za-z0-9\-]{10,}"),
    ("private-key-block", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    ("bearer-token", r"Bearer [A-Za-z0-9._\-]{20,}"),
    ("token-json-field", r'\\*"(?:access_token|refresh_token|id_token|api_key|apiKey|OPENAI_API_KEY)\\*"'
                         r'\s*:\s*\\*"[^"\\]{8,}'),
    ("oauth-auth-entry", r'\\*"type\\*"\s*:\s*\\*"(?:oauth|api|wellknown)\\*"\s*,\s*\\*"(?:refresh|key)\\*"'),
    ("env-key-assignment", r"OPENAI_API_KEY\s*=\s*[^\s\"']{8,}"),
)
_STR_PATTERNS = [(n, re.compile(p)) for n, p in SECRET_PATTERNS]
_BYTES_PATTERNS = [(n, re.compile(p.encode("ascii"))) for n, p in SECRET_PATTERNS]


def scan_bytes(data: bytes) -> list[str]:
    """Names of the credential-shaped patterns found. Matched text is never returned."""
    return [name for name, rx in _BYTES_PATTERNS if rx.search(data)]


def inspect_file(path: Path, chunk: int = 8 << 20) -> tuple[str, list[str]]:
    """One streaming pass: SHA-256 of the file and the credential-pattern names it matches."""
    h = hashlib.sha256()
    hits: set[str] = set()
    tail = b""
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
            buf = tail + block
            hits.update(name for name, rx in _BYTES_PATTERNS if rx.search(buf))
            tail = buf[-_SCAN_OVERLAP:]
    return h.hexdigest(), sorted(hits)


# ---------------------------------------------------------------- config.toml

_SECRET_KEY = re.compile(
    r"(?i)(?:token(?!s\b)|secret|passw|pwd|api[_-]?key|apikey|auth|bearer|credential|cookie"
    r"|private[_-]?key|access[_-]?key)"
)
_SECRET_TABLE = re.compile(
    r"(?i)(?:^|\.)(?:env|env_vars|headers|http_headers|env_http_headers|auth|secrets?|credentials?)$"
)
_HEADER = re.compile(r'^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(?:#.*)?$')
_KV = re.compile(r'^(\s*)([^=#\s\[][^=]*?)\s*=\s*(.*)$')


def redact_toml(text: str) -> tuple[str, int]:
    """Return a copy of a TOML config with secret values replaced by "<redacted>".

    A value is redacted when its key looks secret (token, secret, api_key, auth, ...), when it
    sits in a secret-looking table (env, headers, ...), when it is a multi-line string, or when it
    matches a credential pattern anywhere in the line. The result is still valid TOML.
    """
    out: list[str] = []
    count = 0
    section = ""
    ml: str | None = None
    for raw in text.splitlines():
        if ml is not None:
            out.append("# <redacted multi-line string>")
            count += 1
            if raw.count(ml) % 2 == 1:
                ml = None
            continue
        if raw.count('"""') % 2 == 1 or raw.count("'''") % 2 == 1:
            ml = '"""' if raw.count('"""') % 2 == 1 else "'''"
            out.append("# <redacted multi-line string>")
            count += 1
            continue
        header = _HEADER.match(raw)
        if header:
            section = header.group(1)
            out.append(raw)
            continue
        kv = _KV.match(raw)
        if kv and (_SECRET_KEY.search(kv.group(2)) or _SECRET_TABLE.search(section)):
            out.append(f'{kv.group(1)}{kv.group(2)} = "<redacted>"')
            count += 1
            continue
        new = raw
        for _name, rx in _STR_PATTERNS:
            new, n = rx.subn("<redacted>", new)
            count += n
        out.append(new)
    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"
    return result, count


def config_summary(redacted: str) -> dict:
    """Which tools and hooks a config would switch on. Read from the redacted copy only."""
    try:
        data = tomllib.loads(redacted)
    except tomllib.TOMLDecodeError as exc:
        return {"parse_error": str(exc)}
    plugins = data.get("plugins") or {}
    features = data.get("features") or {}
    return {
        "parse_error": None,
        "mcp_servers": sorted((data.get("mcp_servers") or {}).keys()),
        "plugins_enabled": sorted(k for k, v in plugins.items() if isinstance(v, dict) and v.get("enabled") is True),
        "features_enabled": sorted(k for k, v in features.items() if v is True),
        "notify_hook_configured": "notify" in data,
    }


# ---------------------------------------------------------------- lock access

def load_lock(run: Path) -> dict:
    lock_path, sha_path = run / "lock.json", run / "lock.sha256"
    if not lock_path.is_file() or not sha_path.is_file():
        raise ToolError(f"{run} has no lock.json / lock.sha256; run codex_lock.py first")
    expected = sha_path.read_text(encoding="utf-8").split()[0]
    if sha256_file(lock_path) != expected:
        raise ToolError("lock.json does not match lock.sha256; the lock was changed after it was written")
    lock = load_json(lock_path)
    if lock.get("schema") != SCHEMA:
        raise ToolError(f"unknown lock schema {lock.get('schema')!r}")
    return lock


def check_locked_state(run: Path, lock: dict) -> list[str]:
    """Compare the lock with the files as they are now. An empty list means nothing changed."""
    problems: list[str] = []
    for rec in lock["inputs"]:
        src = Path(rec["source"])
        if not rec["present"]:
            if src.exists():
                problems.append(f"{rec['role']}: appeared after the lock ({src})")
            continue
        if not src.is_file():
            problems.append(f"{rec['role']}: source is missing ({src})")
        elif sha256_file(src) != rec["sha256"]:
            problems.append(f"{rec['role']}: source changed after the lock ({src})")
        copy = run / rec["run_copy"]
        if not copy.is_file() or sha256_file(copy) != rec["sha256"]:
            problems.append(f"{rec['role']}: locked copy changed or missing ({copy})")
    cfg = lock["config"]
    cfg_src = Path(cfg["source"])
    if cfg["present"]:
        if not cfg_src.is_file():
            problems.append(f"config.toml is missing ({cfg_src})")
        elif sha256_file(cfg_src) != cfg["sha256"]:
            problems.append(f"config.toml changed after the lock ({cfg_src})")
    elif cfg_src.exists():
        problems.append(f"config.toml appeared after the lock ({cfg_src})")
    for row in lock["data"]:
        p = Path(row["path"])
        if not p.is_file():
            problems.append(f"data file missing ({p})")
        elif sha256_file(p) != row["sha256"]:
            problems.append(f"data file changed after the lock ({p})")
    for h in lock["harness"]:
        copy = run / h["run_copy"]
        if not copy.is_file() or sha256_file(copy) != h["sha256"]:
            problems.append(f"harness file changed or missing ({copy})")
    fw = lock["framework"]
    if sha256_file(Path(fw["bin"]).resolve()) != fw["bin_sha256"]:
        problems.append(f"codex binary changed after the lock ({fw['bin']})")
    if run_text([fw["bin"], "--version"]).strip() != fw["version"]:
        problems.append("codex --version differs from the locked version")
    return problems


def thread_id_from_event(ev) -> str | None:
    """Session id from a `codex exec --json` event. Handles the thread.started shape and the older msg shape."""
    if not isinstance(ev, dict):
        return None
    if ev.get("type") == "thread.started":
        value = ev.get("thread_id") or ev.get("id") or (ev.get("thread") or {}).get("id")
        return value if isinstance(value, str) else None
    msg = ev.get("msg")
    if isinstance(msg, dict) and msg.get("type") == "session_configured":
        value = msg.get("session_id")
        return value if isinstance(value, str) else None
    return None
