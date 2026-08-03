"""Discovery registry for running Conductor servers.

Each running server writes one JSON record into a per-user state directory and
removes it on clean shutdown; anything (an agent, a skill, another process)
can list the records and health-check each server to find live instances.
Records left behind by a crash are pruned by a process-liveness check and a
``/health`` probe. Stdlib-only: no Qt and no ``mcp`` dependency, so the module
is importable (and runnable via ``python -m derzug.conductor.registry``) from
any environment that has derzug installed.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: Timeout for one ``/health`` probe while pruning stale records.
_HEALTH_TIMEOUT = 0.5


def state_dir() -> Path:
    """Return the per-user directory holding one record per running server."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "derzug" / "servers"


@dataclass(frozen=True)
class ServerRecord:
    """One running Conductor server, as advertised to discovery."""

    server_id: str
    pid: int
    host: str
    port: int
    base_url: str
    mcp_url: str
    started_at: str
    version: str

    def to_dict(self) -> dict:
        """Return the JSON-serializable form of the record."""
        return asdict(self)


def write_record(record: ServerRecord, directory: Path | None = None) -> Path:
    """Atomically write ``record`` (pruning stale siblings); return its path."""
    directory = state_dir() if directory is None else directory
    directory.mkdir(parents=True, exist_ok=True)
    prune_stale(directory)
    path = directory / f"{record.server_id}.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record.to_dict(), indent=2))
    os.replace(tmp, path)
    return path


def remove_record(server_id: str, directory: Path | None = None) -> None:
    """Remove the record for ``server_id``, tolerating a missing file."""
    directory = state_dir() if directory is None else directory
    with suppress(OSError):
        (directory / f"{server_id}.json").unlink()


def list_records(directory: Path | None = None) -> list[ServerRecord]:
    """Return every parseable record, live or not, skipping malformed files."""
    directory = state_dir() if directory is None else directory
    records = []
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
            records.append(ServerRecord(**payload))
        except (OSError, ValueError, TypeError):
            log.warning("Skipping unreadable Conductor record %s", path)
    return records


def prune_stale(directory: Path | None = None) -> list[ServerRecord]:
    """Delete records whose server is gone; return the live ones."""
    directory = state_dir() if directory is None else directory
    live = []
    for record in list_records(directory):
        if _pid_alive(record.pid) is False or not _health_ok(record):
            remove_record(record.server_id, directory)
        else:
            live.append(record)
    return live


def discover(directory: Path | None = None) -> list[ServerRecord]:
    """Return health-checked records of the currently running servers."""
    return prune_stale(directory)


def _pid_alive(pid: int) -> bool | None:
    """Best-effort process liveness; ``None`` when unknowable (Windows)."""
    if os.name != "posix":
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # e.g. PermissionError: it exists, just not ours
        return True
    return True


def _health_ok(record: ServerRecord, timeout: float = _HEALTH_TIMEOUT) -> bool:
    """Whether the recorded server answers ``/health`` as itself."""
    url = record.base_url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode())
    except Exception:
        return False
    if payload.get("status") != "healthy":
        return False
    server_id = payload.get("server_id")
    return server_id is None or server_id == record.server_id


def _main() -> None:
    """Print live server records as JSON for scripts and agents."""
    records = [record.to_dict() for record in discover()]
    sys.stdout.write(json.dumps(records, indent=2) + "\n")


if __name__ == "__main__":
    _main()


__all__ = (
    "ServerRecord",
    "discover",
    "list_records",
    "prune_stale",
    "remove_record",
    "state_dir",
    "write_record",
)
