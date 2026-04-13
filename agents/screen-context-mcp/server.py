import argparse
import ctypes
import json
import os
import socketserver
import subprocess
import threading
from ctypes import wintypes
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CF_UNICODETEXT = 13
MAX_HISTORY = 200
STATE_DIR = Path(__file__).resolve().parent / "state"
STATE_FILE = STATE_DIR / "context_history.jsonl"


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def get_foreground_window_context() -> dict:
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"window_title": "", "window_class": "", "process_id": None, "process_name": "", "executable_path": ""}
        title_buffer = ctypes.create_unicode_buffer(1024)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        process_name = ""
        executable_path = ""
        handle = kernel32.OpenProcess(0x1000 | 0x0400, False, process_id.value)
        if handle:
            try:
                image_buffer = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(len(image_buffer))
                if kernel32.QueryFullProcessImageNameW(handle, 0, image_buffer, ctypes.byref(size)):
                    executable_path = image_buffer.value
                    process_name = os.path.basename(executable_path)
                else:
                    name_buffer = ctypes.create_unicode_buffer(1024)
                    if psapi.GetModuleBaseNameW(handle, None, name_buffer, len(name_buffer)):
                        process_name = name_buffer.value
            finally:
                kernel32.CloseHandle(handle)
        return {
            "window_title": title_buffer.value.strip(),
            "window_class": class_buffer.value.strip(),
            "process_id": int(process_id.value) if process_id.value else None,
            "process_name": process_name,
            "executable_path": executable_path,
        }
    except Exception as exc:
        return {
            "window_title": "",
            "window_class": "",
            "process_id": None,
            "process_name": "",
            "executable_path": "",
            "context_error": f"foreground_window_failed: {exc}",
        }


def get_clipboard_text(max_chars: int = 4000) -> str:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            text = ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
    text = text.replace("\r\n", "\n").strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text


def get_active_console_snippet(max_chars: int = 2000) -> str:
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "$line = Get-History -Count 1 | Select-Object -ExpandProperty CommandLine -ErrorAction SilentlyContinue; if ($line) { $line }",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        text = result.stdout.strip()
    except Exception:
        text = ""
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


def format_context_text(context: dict) -> str:
    lines = [
        "Current non-visual screen context:",
        f"- Timestamp: {context['timestamp']}",
        f"- Window title: {context['window_title'] or '(empty)'}",
        f"- Window class: {context['window_class'] or '(empty)'}",
        f"- Process: {context['process_name'] or '(unknown)'}",
        f"- Process ID: {context['process_id'] if context['process_id'] is not None else '(unknown)'}",
    ]
    if context.get("executable_path"):
        lines.append(f"- Executable path: {context['executable_path']}")
    if context.get("recent_command"):
        lines.append(f"- Recent PowerShell command: {context['recent_command']}")
    if context.get("clipboard_text"):
        lines.append("- Clipboard text:")
        lines.append(context["clipboard_text"])
    if context.get("manual_note"):
        lines.append(f"- Manual note: {context['manual_note']}")
    return "\n".join(lines)


def append_history(context: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(context, ensure_ascii=True) + "\n")
    try:
        lines = STATE_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_HISTORY:
            STATE_FILE.write_text("\n".join(lines[-MAX_HISTORY:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def read_recent_history(limit: int) -> list[dict]:
    if not STATE_FILE.exists():
        return []
    try:
        lines = STATE_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    items = []
    for line in lines[-max(limit, 1):]:
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def build_context(include_clipboard: bool, max_clipboard_chars: int) -> dict:
    context = get_foreground_window_context()
    context["timestamp"] = utc_now()
    try:
        context["recent_command"] = get_active_console_snippet()
    except Exception as exc:
        context["recent_command"] = ""
        context["context_error"] = f"recent_command_failed: {exc}"
    try:
        context["clipboard_text"] = get_clipboard_text(max_chars=max_clipboard_chars) if include_clipboard else ""
    except Exception as exc:
        context["clipboard_text"] = ""
        context["context_error"] = f"clipboard_failed: {exc}"
    return context


TOOLS = [
    {
        "name": "get_active_context",
        "description": "Capture the current foreground window, process, recent command, and optional clipboard text as plain text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_clipboard": {"type": "boolean", "description": "Whether to include clipboard text.", "default": True},
                "max_clipboard_chars": {"type": "integer", "description": "Maximum clipboard characters to include.", "default": 2000}
            }
        }
    },
    {
        "name": "get_recent_context",
        "description": "Return the most recent captured non-visual screen context entries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many entries to return.", "default": 5}
            }
        }
    },
    {
        "name": "record_manual_step",
        "description": "Store a manual note about what the user just did.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "A short textual description of the user action."}
            },
            "required": ["note"]
        }
    }
]


def handle_tool_call(tool_name: str, arguments: dict) -> dict:
    if tool_name == "get_active_context":
        context = build_context(bool(arguments.get("include_clipboard", True)), int(arguments.get("max_clipboard_chars", 2000)))
        append_history(context)
        return {"content": [{"type": "text", "text": format_context_text(context)}]}
    if tool_name == "get_recent_context":
        entries = read_recent_history(int(arguments.get("limit", 5)))
        if not entries:
            text = "No recent non-visual context history is available yet."
        else:
            blocks = []
            for index, entry in enumerate(entries, start=1):
                blocks.append(f"Entry {index}")
                blocks.append(format_context_text(entry))
            text = "\n\n".join(blocks)
        return {"content": [{"type": "text", "text": text}]}
    if tool_name == "record_manual_step":
        note = str(arguments.get("note", "")).strip()
        if not note:
            return {"content": [{"type": "text", "text": "Missing note."}], "isError": True}
        entry = {
            "timestamp": utc_now(),
            "window_title": "",
            "window_class": "",
            "process_id": None,
            "process_name": "",
            "executable_path": "",
            "recent_command": "",
            "clipboard_text": "",
            "manual_note": note
        }
        append_history(entry)
        return {"content": [{"type": "text", "text": f"Recorded note: {note}"}]}
    return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}


class MCPHandler(BaseHTTPRequestHandler):
    server_version = "screen-context-mcp/1.0"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._write_json(400, {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Invalid JSON"}, "id": None})
            return
        request_id = payload.get("id")
        method = payload.get("method", "")
        params = payload.get("params", {}) or {}
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "screen-context-mcp", "version": "1.0.0"}
            }
            self._write_json(200, {"jsonrpc": "2.0", "result": result, "id": request_id})
            return
        if method == "tools/list":
            self._write_json(200, {"jsonrpc": "2.0", "result": {"tools": TOOLS}, "id": request_id})
            return
        if method == "tools/call":
            try:
                result = handle_tool_call(str(params.get("name", "")), params.get("arguments", {}) or {})
            except Exception as exc:
                result = {"content": [{"type": "text", "text": f"Tool call failed: {exc}"}], "isError": True}
            self._write_json(200, {"jsonrpc": "2.0", "result": result, "id": request_id})
            return
        if request_id is None:
            self.send_response(202)
            self.end_headers()
            return
        self._write_json(200, {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Method not found: {method}"}, "id": request_id})

    def log_message(self, format, *args):
        return

    def _write_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadedHTTPServer((args.host, args.port), MCPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"screen-context-mcp listening on http://{args.host}:{args.port}/mcp")
    thread.join()


if __name__ == "__main__":
    main()

