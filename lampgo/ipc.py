"""Local IPC layer for fast command dispatch.

POSIX hosts use a Unix domain socket. Windows uses a loopback-only TCP
endpoint because asyncio has no portable named-pipe server API.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import stat
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_SOCKET_PATH = "/tmp/lampgo.sock"
DEFAULT_TCP_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 28420
TCP_PORT_BASE = 20000
TCP_PORT_SPAN = 20000
DARWIN_SUN_PATH_MAX = 103
LINUX_SUN_PATH_MAX = 107


@dataclass(frozen=True)
class _Endpoint:
    kind: str
    address: str | tuple[str, int]


def _get_socket_path() -> str:
    return os.environ.get("LAMPGO_SOCKET", DEFAULT_SOCKET_PATH)


def _max_unix_socket_path_len() -> int:
    """Return a conservative AF_UNIX path length per platform."""
    if os.name != "posix":
        return LINUX_SUN_PATH_MAX
    if hasattr(os, "uname") and os.uname().sysname == "Darwin":
        return DARWIN_SUN_PATH_MAX
    return LINUX_SUN_PATH_MAX


def _parse_tcp_uri(path: str) -> tuple[str, int] | None:
    """Parse an explicit tcp://host:port endpoint."""
    raw = str(path or "").strip()
    if not raw.lower().startswith("tcp://"):
        return None
    parsed = urlsplit(raw)
    host = parsed.hostname or DEFAULT_TCP_HOST
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("LampGo IPC TCP endpoints must bind to the loopback address")
    if parsed.port is None or not 0 <= parsed.port <= 65535:
        raise ValueError("LampGo IPC TCP port must be between 0 and 65535")
    return host, parsed.port


def _tcp_port_for_path(path: str) -> int:
    """Return a stable local TCP port for a Windows socket-path setting."""
    explicit = _parse_tcp_uri(path)
    if explicit is not None:
        return explicit[1]

    override = os.environ.get("LAMPGO_IPC_PORT", "").strip()
    if override:
        try:
            port = int(override)
        except ValueError as exc:
            raise ValueError("LAMPGO_IPC_PORT must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ValueError("LAMPGO_IPC_PORT must be between 1 and 65535")
        return port

    if path == DEFAULT_SOCKET_PATH:
        return DEFAULT_TCP_PORT
    digest = hashlib.sha1(path.encode("utf-8")).digest()
    return TCP_PORT_BASE + int.from_bytes(digest[:4], "big") % TCP_PORT_SPAN


def _endpoint_for_path(path: str) -> _Endpoint:
    """Resolve a configured path to the actual local transport."""
    explicit = _parse_tcp_uri(path)
    if explicit is not None:
        return _Endpoint("tcp", explicit)
    if os.name == "nt":
        return _Endpoint("tcp", (DEFAULT_TCP_HOST, _tcp_port_for_path(path)))
    return _Endpoint("unix", _normalize_unix_socket_path(path))


def _normalize_unix_socket_path(path: str) -> str:
    """Map long Unix socket paths to a deterministic short /tmp path."""
    if len(path.encode("utf-8")) <= _max_unix_socket_path_len():
        return path
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]
    fallback = f"/tmp/lampgo-{digest}.sock"
    logger.warning("ipc.socket_path_too_long", original=path, fallback=fallback)
    return fallback


def _normalize_socket_path(path: str) -> str:
    """Return the actual endpoint identifier used by server and client."""
    endpoint = _endpoint_for_path(str(path or _get_socket_path()))
    if endpoint.kind == "tcp":
        host, port = endpoint.address
        return _tcp_uri(host, port)
    return str(endpoint.address)


def _tcp_uri(host: str, port: int) -> str:
    display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"tcp://{display_host}:{port}"


def _is_socket_file(path: Path) -> bool:
    try:
        return stat.S_ISSOCK(path.stat().st_mode)
    except OSError:
        return False


class IPCServer:
    """Asyncio local IPC server."""

    def __init__(
        self,
        handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        socket_path: str | None = None,
    ) -> None:
        self._handler = handler
        raw_socket_path = socket_path or _get_socket_path()
        self._socket_path = _normalize_socket_path(raw_socket_path)
        self._endpoint = _endpoint_for_path(self._socket_path)
        self._server: asyncio.AbstractServer | None = None

    @property
    def socket_path(self) -> str:
        """Actual endpoint identifier after normalization."""
        return self._socket_path

    async def start(self) -> None:
        if self._endpoint.kind == "tcp":
            host, port = self._endpoint.address
            self._server = await asyncio.start_server(self._handle_connection, host=host, port=port)
            sockets = self._server.sockets or []
            if sockets:
                actual_port = int(sockets[0].getsockname()[1])
                self._endpoint = _Endpoint("tcp", (host, actual_port))
                self._socket_path = _tcp_uri(host, actual_port)
            logger.info("ipc.started", endpoint=self._socket_path, transport="tcp")
            return

        path = Path(self._endpoint.address)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if not _is_socket_file(path):
                raise RuntimeError(f"IPC path exists and is not a socket: {path}")
            path.unlink()
        self._server = await asyncio.start_unix_server(self._handle_connection, path=str(path))
        try:
            os.chmod(str(path), 0o660)
        except OSError:
            pass
        logger.info("ipc.started", endpoint=self._socket_path, transport="unix")

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._endpoint.kind == "unix":
            path = Path(self._endpoint.address)
            if path.exists() and _is_socket_file(path):
                path.unlink()
        logger.info("ipc.stopped")

    async def _write_json(self, writer: asyncio.StreamWriter, payload: dict[str, Any]) -> bool:
        """Write one JSON line; ignore disconnects from short-lived clients."""
        try:
            writer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
            await writer.drain()
            return True
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("ipc.client_disconnected")
            return False

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if not raw:
                return
            request = json.loads(raw.decode("utf-8"))
            response = await self._handler(request)
            await self._write_json(writer, response)
        except TimeoutError:
            await self._write_json(writer, {"ok": False, "error": "timeout"})
        except json.JSONDecodeError as exc:
            await self._write_json(writer, {"ok": False, "error": f"invalid json: {exc}"})
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("ipc.client_disconnected")
        except Exception:
            logger.exception("ipc.handler_error")
            try:
                await self._write_json(writer, {"ok": False, "error": "internal error"})
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


def ipc_send(request: dict[str, Any], socket_path: str | None = None, timeout: float = 30.0) -> dict[str, Any]:
    """Synchronous IPC client. Raises ConnectionRefusedError if absent."""
    raw_path = socket_path or _get_socket_path()
    endpoint = _endpoint_for_path(raw_path)
    if endpoint.kind == "tcp":
        sock = socket.create_connection(endpoint.address, timeout=timeout)
    else:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(endpoint.address)
    try:
        sock.sendall(json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n")
        buf = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                break
        return json.loads(buf.strip().decode("utf-8"))
    finally:
        sock.close()


def is_daemon_running(socket_path: str | None = None) -> bool:
    """Check whether a daemon is listening on the configured endpoint."""
    raw_path = socket_path or _get_socket_path()
    endpoint = _endpoint_for_path(raw_path)
    if endpoint.kind == "unix" and not Path(endpoint.address).exists():
        return False
    try:
        result = ipc_send({"cmd": "ping"}, socket_path=raw_path, timeout=2.0)
        return bool(result.get("ok", False))
    except (ConnectionRefusedError, FileNotFoundError, OSError, TimeoutError, ValueError):
        return False


def cleanup_ipc_endpoint(socket_path: str | None = None) -> bool:
    """Remove a stale Unix socket; TCP endpoints need no filesystem cleanup."""
    raw_path = socket_path or _get_socket_path()
    endpoint = _endpoint_for_path(raw_path)
    if endpoint.kind != "unix":
        return False
    path = Path(endpoint.address)
    if path.exists() and _is_socket_file(path):
        path.unlink()
        return True
    return False
