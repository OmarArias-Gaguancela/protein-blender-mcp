"""Protein Blender MCP - Blender side.

Runs a small TCP server on localhost. The MCP server (``protein-blender-mcp``)
connects to it and sends newline-delimited JSON commands such as
``{"command": "add_style", "params": {...}}``. Commands are queued and executed
on Blender's main thread through ``bpy.app.timers``, because the Blender API is
not thread-safe.
"""

from __future__ import annotations

import json
import queue
import socket
import threading

import bpy

from . import commands

DEFAULT_PORT = 9877

_server: "BridgeServer | None" = None


class _Job:
    def __init__(self, command: str, params: dict | None):
        self.command = command
        self.params = params
        self.done = threading.Event()
        self.response: dict | None = None


class BridgeServer:
    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.jobs: "queue.Queue[_Job]" = queue.Queue()
        self._sock: socket.socket | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(4)
        self._sock.settimeout(1.0)
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        if not bpy.app.timers.is_registered(self.process_jobs):
            bpy.app.timers.register(self.process_jobs, persistent=True)
        print(f"[protein-blender-mcp] listening on {self.host}:{self.port}")

    def stop(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if bpy.app.timers.is_registered(self.process_jobs):
            bpy.app.timers.unregister(self.process_jobs)
        print("[protein-blender-mcp] stopped")

    @property
    def running(self) -> bool:
        return self._running

    # -- networking (background threads) ------------------------------------
    def _accept_loop(self) -> None:
        while self._running and self._sock is not None:
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._client_loop, args=(conn,), daemon=True).start()

    def _client_loop(self, conn: socket.socket) -> None:
        buffer = b""
        with conn:
            conn.settimeout(None)
            while self._running:
                try:
                    chunk = conn.recv(65536)
                except OSError:
                    break
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    response = self._handle_line(line)
                    try:
                        conn.sendall(json.dumps(response).encode() + b"\n")
                    except OSError:
                        return

    def _handle_line(self, line: bytes) -> dict:
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            return {"status": "error", "message": f"Bad JSON: {exc}"}
        job = _Job(message.get("command", ""), message.get("params"))
        self.jobs.put(job)
        # rendering can take a while, so allow a generous timeout
        if not job.done.wait(timeout=600):
            return {"status": "error", "message": "Timed out waiting for Blender"}
        return job.response or {"status": "error", "message": "No response"}

    # -- main thread --------------------------------------------------------
    def process_jobs(self) -> float:
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            job.response = commands.dispatch(job.command, job.params)
            job.done.set()
        return 0.05


def get_server() -> "BridgeServer | None":
    return _server


def start_server(port: int | None = None) -> BridgeServer:
    global _server
    if _server is None or not _server.running:
        prefs_port = port or bpy.context.scene.protein_mcp_port
        _server = BridgeServer(port=prefs_port)
        _server.start()
    return _server


def stop_server() -> None:
    global _server
    if _server is not None:
        _server.stop()
        _server = None


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------


class PROTEINMCP_OT_start(bpy.types.Operator):
    bl_idname = "protein_mcp.start"
    bl_label = "Start MCP Bridge"
    bl_description = "Listen on localhost for commands from the Protein Blender MCP server"

    def execute(self, context):
        try:
            start_server(context.scene.protein_mcp_port)
        except OSError as exc:
            self.report({"ERROR"}, f"Could not start: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Listening on port {context.scene.protein_mcp_port}")
        return {"FINISHED"}


class PROTEINMCP_OT_stop(bpy.types.Operator):
    bl_idname = "protein_mcp.stop"
    bl_label = "Stop MCP Bridge"

    def execute(self, context):
        stop_server()
        return {"FINISHED"}


class PROTEINMCP_PT_panel(bpy.types.Panel):
    bl_label = "Protein MCP"
    bl_idname = "PROTEINMCP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Protein MCP"

    def draw(self, context):
        layout = self.layout
        server = get_server()
        running = server is not None and server.running
        layout.prop(context.scene, "protein_mcp_port", text="Port")
        if running:
            layout.label(text=f"Running on port {server.port}", icon="CHECKMARK")
            layout.operator("protein_mcp.stop", icon="PAUSE")
        else:
            layout.label(text="Not running", icon="X")
            layout.operator("protein_mcp.start", icon="PLAY")


_classes = (PROTEINMCP_OT_start, PROTEINMCP_OT_stop, PROTEINMCP_PT_panel)


def register():
    bpy.types.Scene.protein_mcp_port = bpy.props.IntProperty(
        name="Port", default=DEFAULT_PORT, min=1024, max=65535
    )
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    stop_server()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.protein_mcp_port
