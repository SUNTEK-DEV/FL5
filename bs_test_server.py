#!/usr/bin/env python3
"""Tiny BS visible-light terminal protocol test server.

The protocol in the Word document uses HTTP POST requests from the device:

- request_code: receive_cmd       -> device heartbeat, asks server for a command
- request_code: send_cmd_result   -> device uploads command execution result
- request_code: realtime_*        -> device pushes realtime events

This sample is intentionally small and dependency-free.  It is suitable for
checking that a device can connect, fetch a command, upload the result, and push
basic realtime records.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


DEFAULT_SECRET = "CHANGE_ME"
REALTIME_CODES = {
    "realtime_glog",
    "realtime_door_status",
    "realtime_enroll_data",
    "door_visit",
    "door_visit_check",
    "pass_online_check",
    "Opera_glog",
}


@dataclass
class Command:
    trans_id: str
    cmd_code: str
    cmd_param: Any = None


@dataclass
class ServerState:
    secret: str = DEFAULT_SECRET
    verify_token: bool = False
    auto_device_info: bool = True
    next_trans_id: int = 100
    commands: dict[str, list[Command]] = field(default_factory=dict)
    auto_sent: set[str] = field(default_factory=set)
    events: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def make_trans_id(self) -> str:
        with self.lock:
            value = str(self.next_trans_id)
            self.next_trans_id += 1
            return value

    def enqueue(self, dev_id: str, cmd_code: str, cmd_param: Any = None, trans_id: str | None = None) -> Command:
        command = Command(trans_id or self.make_trans_id(), cmd_code, cmd_param)
        with self.lock:
            self.commands.setdefault(dev_id, []).append(command)
        return command

    def pop_command(self, dev_id: str) -> Command | None:
        with self.lock:
            queue = self.commands.setdefault(dev_id, [])
            if queue:
                return queue.pop(0)
            if self.auto_device_info and dev_id not in self.auto_sent:
                self.auto_sent.add(dev_id)
                return Command(self.make_trans_id(), "GET_DEVICE_INFO")
            return None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "commands": {
                    dev_id: [command.__dict__ for command in queue]
                    for dev_id, queue in self.commands.items()
                },
                "events": self.events[-100:],
            }


class BSTestHandler(BaseHTTPRequestHandler):
    server_version = "BSTestServer/0.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.write_json({"ok": True})
            return
        if path == "/commands":
            self.write_json(self.state.snapshot()["commands"])
            return
        if path == "/events":
            self.write_json(self.state.snapshot()["events"])
            return
        self.write_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self.read_body_json()

        if path == "/commands":
            self.handle_enqueue_command(body)
            return

        request_code = self.headers.get("request_code", "")
        dev_id = self.headers.get("dev_id", "")
        trans_id = self.headers.get("trans_id", "")

        if self.state.verify_token and dev_id and not self.valid_token(dev_id):
            self.write_protocol_response("ERROR", trans_id=trans_id, body={"error": "bad token"})
            return

        print(
            json.dumps(
                {
                    "request_code": request_code,
                    "dev_id": dev_id,
                    "dev_model": self.headers.get("dev_model", ""),
                    "trans_id": trans_id,
                    "cmd_return_code": self.headers.get("cmd_return_code", ""),
                    "body": body,
                },
                ensure_ascii=False,
            )
        )

        if request_code == "receive_cmd":
            self.handle_receive_cmd(dev_id)
            return

        if request_code == "send_cmd_result":
            self.record_event("cmd_result", dev_id, trans_id, body)
            self.write_protocol_response("OK", trans_id=trans_id)
            return

        if request_code in REALTIME_CODES:
            self.record_event(request_code, dev_id, trans_id, body)
            code = "OK"
            if request_code in {"door_visit_check", "pass_online_check"}:
                code = "OK" if body.get("allow", True) else "ERROR"
            self.write_protocol_response(code, trans_id=trans_id or self.state.make_trans_id())
            return

        self.record_event("unknown", dev_id, trans_id, body)
        self.write_protocol_response("ERROR", trans_id=trans_id, body={"error": f"unsupported request_code: {request_code}"})

    @property
    def state(self) -> ServerState:
        return self.server.state  # type: ignore[attr-defined]

    def handle_receive_cmd(self, dev_id: str) -> None:
        if not dev_id:
            self.write_protocol_response("ERROR", body={"error": "missing dev_id"})
            return

        command = self.state.pop_command(dev_id)
        if command is None:
            self.write_protocol_response("ERROR_NO_CMD")
            return

        self.write_protocol_response(
            "OK",
            trans_id=command.trans_id,
            cmd_code=command.cmd_code,
            body=command.cmd_param,
        )

    def handle_enqueue_command(self, body: dict[str, Any]) -> None:
        dev_id = str(body.get("dev_id", "")).strip()
        cmd_code = str(body.get("cmd_code", "")).strip()
        if not dev_id or not cmd_code:
            self.write_json({"error": "dev_id and cmd_code are required"}, status=400)
            return
        command = self.state.enqueue(
            dev_id=dev_id,
            cmd_code=cmd_code,
            cmd_param=body.get("cmd_param"),
            trans_id=str(body["trans_id"]) if "trans_id" in body else None,
        )
        self.write_json({"queued": command.__dict__})

    def record_event(self, event_type: str, dev_id: str, trans_id: str, body: dict[str, Any]) -> None:
        with self.state.lock:
            self.state.events.append(
                {
                    "type": event_type,
                    "dev_id": dev_id,
                    "trans_id": trans_id,
                    "headers": {
                        "request_code": self.headers.get("request_code", ""),
                        "cmd_return_code": self.headers.get("cmd_return_code", ""),
                    },
                    "body": body,
                    "received_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

    def valid_token(self, dev_id: str) -> bool:
        expected = hashlib.md5((dev_id + self.state.secret).encode("utf-8")).hexdigest().upper()
        return self.headers.get("token", "").upper() == expected

    def read_body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {"_raw": raw.decode("utf-8", errors="replace")}

    def write_protocol_response(
        self,
        response_code: str,
        *,
        trans_id: str = "",
        cmd_code: str = "",
        body: Any = None,
    ) -> None:
        payload = b""
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("response_code", response_code)
        self.send_header("trans_id", trans_id)
        self.send_header("cmd_code", cmd_code)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def write_json(self, body: Any, status: int = 200) -> None:
        payload = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")


class BSTestHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BSTestHandler], state: ServerState):
        super().__init__(server_address, handler_class)
        self.state = state


def run_server(host: str, port: int, state: ServerState) -> BSTestHTTPServer:
    server = BSTestHTTPServer((host, port), BSTestHandler, state)
    print(f"BS test server listening on http://{host}:{server.server_port}")
    print("Device POST target can be / ; management endpoints: /commands, /events, /health")
    server.serve_forever()
    return server


def self_test() -> None:
    state = ServerState(verify_token=False)
    server = BSTestHTTPServer(("127.0.0.1", 0), BSTestHandler, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port

    def post(path: str, headers: dict[str, str], body: Any) -> tuple[http.client.HTTPResponse, bytes]:
        payload = json.dumps(body).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", path, body=payload, headers={"Content-Type": "application/json", **headers})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    dev_headers = {
        "request_code": "receive_cmd",
        "dev_id": "C2689C470326192F",
        "dev_model": "V536",
        "token": "TEST",
    }
    resp, data = post("/", dev_headers, {"time": "201910010645"})
    print("heartbeat:", resp.status, resp.getheader("response_code"), resp.getheader("trans_id"), resp.getheader("cmd_code"), data.decode())
    assert resp.getheader("response_code") == "OK"
    assert resp.getheader("cmd_code") == "GET_DEVICE_INFO"

    result_headers = {
        "request_code": "send_cmd_result",
        "dev_id": "C2689C470326192F",
        "dev_model": "V536",
        "trans_id": resp.getheader("trans_id") or "",
        "cmd_return_code": "OK",
    }
    resp, data = post("/", result_headers, {"name": "demo-device", "deviceId": "C2689C470326192F", "firmware": "demo"})
    print("cmd result:", resp.status, resp.getheader("response_code"), data.decode())
    assert resp.getheader("response_code") == "OK"

    realtime_headers = {
        "request_code": "realtime_glog",
        "dev_id": "C2689C470326192F",
        "dev_model": "V536",
    }
    resp, data = post(
        "/",
        realtime_headers,
        {
            "userId": "1",
            "time": "20260417120000",
            "verifyMode": "Card+Face",
            "ioMode": 1,
            "inOut": "In",
            "doorMode": "hand_open",
        },
    )
    print("realtime:", resp.status, resp.getheader("response_code"), resp.getheader("trans_id"), data.decode())
    assert resp.getheader("response_code") == "OK"

    server.shutdown()
    thread.join(timeout=2)
    print("self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple BS protocol HTTP test server")
    parser.add_argument("--host", default="0.0.0.0", help="listen host, default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=8080, help="listen port, default: 8080")
    parser.add_argument("--secret", default=DEFAULT_SECRET, help="token secret for MD5(dev_id + secret)")
    parser.add_argument("--verify-token", action="store_true", help="reject requests with invalid token")
    parser.add_argument("--no-auto-device-info", action="store_true", help="do not auto-send GET_DEVICE_INFO on first heartbeat")
    parser.add_argument("--self-test", action="store_true", help="run a local protocol smoke test and exit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        self_test()
        return

    state = ServerState(
        secret=args.secret,
        verify_token=args.verify_token,
        auto_device_info=not args.no_auto_device_info,
    )
    run_server(args.host, args.port, state)


if __name__ == "__main__":
    main()
