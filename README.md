# Mirror-Space (Python)

Ultra-low-latency screen broadcasting over LAN with adaptive streaming, diff/motion encoding, and one-to-many receiver fanout.

## Core Features

- Ultra-low-latency UDP transport (MTU-safe fragmentation)
- Adaptive streaming control (dynamic FPS, resolution, compression)
- One broadcaster to multiple receivers (fanout)
- Diff-frame and motion-assisted encoding
- Receiver-driven resilience feedback (`KEYFRAME_REQUEST`, `NETWORK_UNSTABLE`)
- Real-time latency visibility (`frame_ms`, `rtt_ms`)
- LAN discovery (mDNS + UDP beacon/query + subnet scan)
- Region/window capture support

## Quick Start

### 1. Install dependencies

```powershell
cd D:\mirror-space\mirror-space
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Start receiver(s)

```powershell
python receiver.py
```

### 3. Start broadcaster

```powershell
python broadcaster.py
```

In auto-connect mode, broadcaster prints a session access ID. Enter that ID in each receiver to authorize and join the stream.

## Multi-Receiver Broadcasting

Mirror-Space now supports one-to-many fanout in broadcast mode:

1. Broadcaster starts and waits for authenticated receiver hellos.
2. Each receiver sends `RECEIVER_HELLO` with the session access ID.
3. Broadcaster tracks active receivers and sends every encoded frame to all of them.
4. Stale/inactive receivers are removed automatically.

## Latency Metrics

Receiver prints runtime metrics each second:

- `frame_ms`: frame age at display time
- `rtt_ms`: feedback channel round-trip latency
- receive FPS

This gives you real numbers for documentation and benchmark tables.

## Run Modes

### Local loopback test

```powershell
python receiver.py 9999 127.0.0.1
python broadcaster.py 127.0.0.1 9999
```

### LAN with default discovery

```powershell
python receiver.py
python broadcaster.py
```

### Custom port

```powershell
python receiver.py 8888
python broadcaster.py 255.255.255.255 8888
```

## Important Runtime Knobs

### Broadcaster adaptive knobs

- `INITIAL_TARGET_FPS`
- `MIN_STREAM_FPS`
- `MAX_STREAM_FPS`
- `INITIAL_STREAM_WIDTH`
- `INITIAL_JPEG_QUALITY`
- `INITIAL_DIFF_THRESHOLD`

### Encoder knobs

- `block_size`
- `threshold`
- `max_changed_block_ratio`
- `max_diff_payload_ratio`
- `jpeg_quality`

## Project Structure

```text
mirror-space/
  broadcaster.py
  receiver.py
  diff_encoder.py
  region_selector.py
  ARCHITECTURE.md
  COMPARISON.md
  WELCOME.md
  requirements.txt
  docs/
    MIRROR_SPACE_REPORT.tex
```

## Notes

- Use trusted LAN environments only (no transport encryption by default).
- For best latency, prefer wired Ethernet and close heavy background apps.
- If you need publication-quality latency plots, capture logs from receiver output and compute p50/p95/p99.
