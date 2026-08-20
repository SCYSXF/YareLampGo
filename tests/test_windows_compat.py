from __future__ import annotations

import asyncio
import sys
import types


def test_windows_socket_path_uses_loopback_tcp(monkeypatch):
    import lampgo.ipc as ipc

    monkeypatch.setattr(ipc.os, "name", "nt")
    monkeypatch.delenv("LAMPGO_IPC_PORT", raising=False)

    endpoint = ipc._normalize_socket_path("C:/Users/test/.lampgo.sock")

    assert endpoint.startswith("tcp://127.0.0.1:")
    assert endpoint.rsplit(":", 1)[1].isdigit()


def test_windows_cli_reconfigures_console_output(monkeypatch):
    import lampgo.cli as cli

    class FakeStream:
        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    stdout = FakeStream()
    stderr = FakeStream()
    monkeypatch.setattr(cli.os, "name", "nt")
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)

    cli._configure_windows_console_encoding()

    assert stdout.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_windows_config_default_is_tcp_endpoint(monkeypatch):
    import lampgo.core.config as config

    monkeypatch.setattr(config.os, "name", "nt")

    assert config.LampgoConfig().socket_path == "tcp://127.0.0.1:28420"


def test_tcp_ipc_round_trip():
    from lampgo.ipc import IPCServer, ipc_send

    async def run() -> None:
        async def handler(request):
            return {"ok": True, "result": request}

        server = IPCServer(handler, socket_path="tcp://127.0.0.1:0")
        await server.start()
        try:
            response = await asyncio.to_thread(ipc_send, {"cmd": "ping"}, server.socket_path)
            assert response == {"ok": True, "result": {"cmd": "ping"}}
        finally:
            await server.stop()

    asyncio.run(run())


def test_windows_serial_ports_are_discovered_and_numerically_sorted(monkeypatch):
    import lampgo.autodetect as autodetect

    serial_module = types.ModuleType("serial")
    tools_module = types.ModuleType("serial.tools")
    list_ports_module = types.ModuleType("serial.tools.list_ports")
    list_ports_module.comports = lambda: [
        types.SimpleNamespace(device="COM10"),
        types.SimpleNamespace(device="COM2"),
        types.SimpleNamespace(device="COM5"),
    ]
    serial_module.tools = tools_module
    tools_module.list_ports = list_ports_module
    monkeypatch.setitem(sys.modules, "serial", serial_module)
    monkeypatch.setitem(sys.modules, "serial.tools", tools_module)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", list_ports_module)
    monkeypatch.setattr(autodetect.platform, "system", lambda: "Windows")

    assert autodetect._list_serial_ports() == ["COM2", "COM5", "COM10"]


def test_windows_serial_port_detection_skips_bluetooth_virtual_ports(monkeypatch):
    import lampgo.autodetect as autodetect

    serial_module = types.ModuleType("serial")
    tools_module = types.ModuleType("serial.tools")
    list_ports_module = types.ModuleType("serial.tools.list_ports")
    list_ports_module.comports = lambda: [
        types.SimpleNamespace(
            device="COM28",
            description="Bluetooth link standard serial",
            hwid="BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}",
        ),
        types.SimpleNamespace(device="COM5", description="USB-SERIAL CH340", hwid="USB VID:PID=1A86:7523"),
    ]
    serial_module.tools = tools_module
    tools_module.list_ports = list_ports_module
    monkeypatch.setitem(sys.modules, "serial", serial_module)
    monkeypatch.setitem(sys.modules, "serial.tools", tools_module)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", list_ports_module)
    monkeypatch.setattr(autodetect.platform, "system", lambda: "Windows")

    assert autodetect._list_serial_ports() == ["COM5"]


def test_serial_motor_detection_uses_single_port_fallback(monkeypatch):
    import lampgo.autodetect as autodetect

    monkeypatch.setattr(autodetect, "_list_serial_ports", lambda: ["COM5"])
    monkeypatch.setattr(autodetect, "_probe_feetech", lambda _port: False)
    monkeypatch.setattr(autodetect, "_probe_esp32", lambda _port: False)

    detected = autodetect.detect_motor_port()

    assert detected["motor_port"] == "COM5"
    assert detected["motor_candidates"] == ["COM5"]
    assert detected["motor_detection"] == "single_port_fallback"


def test_serial_motor_detection_keeps_multiple_ports_ambiguous(monkeypatch):
    import lampgo.autodetect as autodetect

    monkeypatch.setattr(autodetect, "_list_serial_ports", lambda: ["COM2", "COM5"])
    monkeypatch.setattr(autodetect, "_probe_feetech", lambda _port: False)
    monkeypatch.setattr(autodetect, "_probe_esp32", lambda _port: False)

    detected = autodetect.detect_motor_port()

    assert detected["motor_port"] is None
    assert detected["motor_candidates"] == ["COM2", "COM5"]
    assert detected["motor_detection"] == "ambiguous"
    assert "require confirmation" in detected["messages"][-2]


def test_windows_system_music_source_uses_recording_device(monkeypatch):
    from lampgo.perception import music

    monkeypatch.setattr(music.platform, "system", lambda: "Windows")
    source = music.make_music_source("system")

    assert isinstance(source, music.WindowsSystemAudioSource)


def test_desktop_backend_uses_windows_file_association(monkeypatch):
    from lampgo.bridge.desktop import PyAutoGUIBackend

    launched: list[str] = []
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr("os.startfile", lambda app: launched.append(app), raising=False)

    backend = PyAutoGUIBackend()
    assert backend.app_launch("calc.exe") is True
    assert launched == ["calc.exe"]
