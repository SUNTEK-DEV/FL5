# FL5 README

## Overview

This repository contains basic integration materials for the **FL5** product model.

At the current stage, the folder includes:

- `bs_test_server.py`: a lightweight Python test server for the BS visible-light terminal HTTP protocol
- `Communication Protocol for Attendance, Access Control, and Elevator Control Devices - BS Visible Light - 20260313-en.docx`: the English protocol reference document

The repository is intended for development, protocol verification, and device-side connectivity testing for attendance, access control, and elevator control scenarios.

## Product Model

- **Model**: FL5
- **Protocol family**: BS visible-light terminal communication protocol
- **Main purpose**: verify communication between the FL5 device and a backend platform through HTTP-based command polling and event upload

## Repository Structure

```text
FL5-GITHUB/
+-- bs_test_server.py
+-- Communication Protocol for Attendance, Access Control, and Elevator Control Devices - BS Visible Light - 20260313-en.docx
`-- README.md
```

## Requirements

- Python 3.9 or later
- No third-party Python packages are required

The test server uses only the Python standard library.

## Included Test Server

`bs_test_server.py` is a small HTTP server that simulates a backend endpoint for the FL5 device. It supports:

- device heartbeat and command polling
- command result upload
- realtime event upload
- simple command queue management
- optional token verification
- built-in self-test

### Supported request types

The current server handles these protocol request codes:

- `receive_cmd`
- `send_cmd_result`
- `realtime_glog`
- `realtime_door_status`
- `realtime_enroll_data`
- `door_visit`
- `door_visit_check`
- `pass_online_check`
- `Opera_glog`

## Quick Start

Start the test server:

```bash
python bs_test_server.py
```

Default behavior:

- listens on `0.0.0.0:8080`
- exposes management endpoints at `/commands`, `/events`, and `/health`
- automatically returns `GET_DEVICE_INFO` to a device the first time it polls for a command

Run the built-in smoke test:

```bash
python bs_test_server.py --self-test
```

Start with token verification enabled:

```bash
python bs_test_server.py --verify-token --secret YOUR_SECRET
```

Start on a custom host or port:

```bash
python bs_test_server.py --host 127.0.0.1 --port 9000
```

Disable the automatic `GET_DEVICE_INFO` response:

```bash
python bs_test_server.py --no-auto-device-info
```

## Management Endpoints

After the server is running, the following endpoints are available:

- `GET /health`: health check
- `GET /commands`: view queued commands
- `GET /events`: view recent uploaded events
- `POST /commands`: enqueue a command for a device

### Example: enqueue a command

```bash
curl -X POST http://127.0.0.1:8080/commands ^
  -H "Content-Type: application/json" ^
  -d "{\"dev_id\":\"FL5_DEMO_001\",\"cmd_code\":\"OPEN_DOOR\",\"cmd_param\":{\"door\":1}}"
```

## Expected Device Interaction Flow

The FL5 device is expected to communicate with the server by HTTP `POST` requests:

1. The device sends `receive_cmd` to ask whether a command is available.
2. The server returns either a command or `ERROR_NO_CMD`.
3. The device executes the command and uploads the result with `send_cmd_result`.
4. The device sends realtime records such as access logs, door status, or online validation events.

## Token Verification

When `--verify-token` is enabled, the server validates the request header `token` using:

```text
MD5(dev_id + secret)
```

The generated digest is compared in uppercase format.

## Notes

- This repository currently contains a **protocol test utility** and a **reference document**, not a full production platform.
- The test server is suitable for debugging connectivity, protocol fields, and command/event exchange during FL5 integration.
- For protocol field definitions, payload structures, and business rules, refer to the included `.docx` specification.

## Document Reference

Primary reference:

- `Communication Protocol for Attendance, Access Control, and Elevator Control Devices - BS Visible Light - 20260313-en.docx`

This document is the main source for protocol definitions used by the FL5 device integration workflow.
