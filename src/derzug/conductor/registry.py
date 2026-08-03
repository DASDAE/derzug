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
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path

from derzug.conductor.constants import SERVER_NAME

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
    """Delete records whose server is provably gone; return the live ones.

    A probe that cannot tell dead from busy (e.g. a timeout under load) keeps
    the record on disk — one slow answer must not erase a live sibling — but
    does not report it live either.
    """
    directory = state_dir() if directory is None else directory
    live = []
    for record in list_records(directory):
        if _pid_alive(record.pid) is False:
            remove_record(record.server_id, directory)
            continue
        probe = _probe_health(record)
        if probe == "live":
            live.append(record)
        elif probe == "stale":
            remove_record(record.server_id, directory)
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


def _probe_health(record: ServerRecord, timeout: float = _HEALTH_TIMEOUT) -> str:
    """Classify a record as ``"live"``, ``"stale"``, or ``"unknown"``.

    ``"stale"`` means provably gone: nothing listens on the port, or whatever
    answered is not this server (wrong identity, non-health payload — e.g. the
    port was reused by another process). ``"unknown"`` covers probes that
    could equally hit a busy server (timeouts and the like), so callers keep
    the record.
    """
    url = record.base_url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError:
        return "stale"  # something answered, but not our health route
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            return "stale"  # nothing listens on the port anymore
        return "unknown"
    except ConnectionRefusedError:
        return "stale"
    except Exception:
        return "unknown"
    if status != 200:
        return "stale"
    try:
        payload = json.loads(body.decode())
    except ValueError:
        return "stale"
    identity_matches = (
        payload.get("status") == "healthy"
        and payload.get("server") == SERVER_NAME
        and payload.get("server_id") == record.server_id
    )
    return "live" if identity_matches else "stale"


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
