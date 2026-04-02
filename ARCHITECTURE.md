# Mirror-Space Architecture

## Overview

Mirror-Space is a Python LAN screen broadcasting system optimized for low end-to-end latency. It uses UDP transport, differential/motion encoding, adaptive quality control, and feedback-driven recovery.

## High-Level Pipeline

1. Capture source frame (full screen / region / selected window)
2. Encode as full, key, diff, or motion frame
3. Fragment into MTU-safe UDP packets
4. Fan out to one or many active receivers
5. Reassemble and decode at receiver
6. Display frame and report health/latency feedback

## Runtime Components

### Broadcaster (`broadcaster.py`)

- Captures frames from selected source
- Performs adaptive quality tuning from receiver telemetry
- Manages access-ID gated receiver authorization
- Maintains active receiver set for one-to-many fanout
- Sends key-frame and telemetry responses on feedback channel

### Encoder/Decoder (`diff_encoder.py`)

- `FULL_FRAME` / `KEY_FRAME` using JPEG
- `DIFF_FRAME` block-level updates
- `MOTION_FRAME` with optical-flow-assisted residual updates
- Key-frame escalation when diffs become inefficient or unstable

### Receiver (`receiver.py`)

- Discovers streams and handles manual selection
- Reassembles UDP fragments per frame
- Drops partial frames after strict reassembly timeout
- Decodes frame stream and renders via OpenCV
- Reports telemetry (`STREAM_STATS`) and recovery signals
- Measures `frame_ms` and `rtt_ms` for latency visibility

### Region Selection (`region_selector.py`)

- Full screen, specific window, or custom region capture
- Supports HWND-based capture paths where available

## Control and Feedback Plane

Receiver -> Broadcaster messages:

- `RECEIVER_HELLO`: access-ID based authorization
- `KEYFRAME_REQUEST`: decoder mismatch recovery
- `NETWORK_UNSTABLE`: packet loss / partial-frame pressure
- `STREAM_STATS`: receiver FPS, loss, and partial ratios
- `LATENCY_PING`: RTT probing

Broadcaster -> Receiver messages:

- `DISCOVERY_RESPONSE`
- `LATENCY_PONG`

## Multi-Receiver Fanout

In auto-connect mode, broadcaster tracks authorized receivers and sends each encoded frame to all active targets.

- New receivers join by successful `RECEIVER_HELLO` handshake
- Receiver records are refreshed by control traffic
- Stale receivers are dropped after timeout

This enables one broadcaster to serve multiple viewers concurrently.

## Latency Strategy

Key latency controls:

- MTU-safe packet size to avoid IP fragmentation pressure
- Moderate socket buffers to reduce queue buildup
- Tight receiver reassembly window to prevent stale frame drift
- Adaptive downshift on congestion (FPS/resolution/compression)
- Key-frame resync on instability and decoder mismatch

## Current Repository Layout

```text
mirror-space/
  broadcaster.py
  receiver.py
  diff_encoder.py
  region_selector.py
  README.md
  ARCHITECTURE.md
  COMPARISON.md
  WELCOME.md
  requirements.txt
  docs/
    MIRROR_SPACE_REPORT.tex
```
