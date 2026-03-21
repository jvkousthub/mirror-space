# Multi-Viewer Broadcasting

Upgrade Mirror-Space from **1→1** (single sender, single receiver) to **1→N** (single sender, multiple receivers) for classrooms, hackathons, and workshops.

## User Review Required

> [!IMPORTANT]
> **Architecture Decision: Client Registration vs. UDP Broadcast**
>
> I'm proposing **Option A: Client Registration** over plain UDP broadcast. Here's why:
>
> | | Client Registration (Proposed) | UDP Broadcast |
> |---|---|---|
> | **How it works** | Receivers send a JOIN packet to the broadcaster; broadcaster sends frames to each registered client | Broadcaster sends to `255.255.255.255`; any receiver on the subnet picks it up |
> | **Visibility** | Broadcaster shows a live list of connected viewers (name, IP, uptime) | No way to know who's watching |
> | **Network** | Works across subnets / VPNs | Same subnet only |
> | **Bandwidth** | Sends N copies (one per client) — acceptable for classrooms with ≤30-50 viewers on Gigabit LAN | Sends 1 copy (network fans out) — more efficient |
> | **Complexity** | Medium — needs a heartbeat/registration thread | Low — just change the target IP |
>
> For classroom/hackathon use, **knowing who is connected** is very valuable. The bandwidth tradeoff is acceptable on a Gigabit LAN. If you'd prefer the simpler UDP broadcast approach, let me know.

> [!WARNING]
> **Breaking change to CLI**: The broadcaster will no longer take a single target IP. Instead:
> - `python broadcaster.py` — starts and waits for receivers to connect
> - `python broadcaster.py --port 8888` — custom port
>
> Receivers will now need the **broadcaster's IP**:
> - `python receiver.py 192.168.1.10` — connect to broadcaster
> - `python receiver.py 192.168.1.10 --port 8888` — custom port

## Proposed Changes

### Control Protocol

A lightweight registration protocol on a separate **control port** (default: `DEFAULT_PORT + 1 = 10000`):

```
Receiver → Broadcaster:  MSCP:JOIN:<client_name>\x00
Receiver → Broadcaster:  MSCP:HEARTBEAT\x00          (every 3 seconds)
Receiver → Broadcaster:  MSCP:LEAVE\x00              (on graceful shutdown)
Broadcaster → Receiver:  MSCP:WELCOME:<info>\x00      (ack after JOIN)
```

Broadcaster removes a client if no heartbeat received for **10 seconds**.

---

### Broadcaster

#### [MODIFY] [broadcaster.py](file:///s:/mirror-space/broadcaster.py)

1. **New `ClientManager` class** — thread-safe client registry
   - `add_client(addr, name)`, `remove_client(addr)`, `get_active_clients()`
   - Prunes stale clients (no heartbeat in 10s)
   - Prints client connect/disconnect events to console

2. **New control listener thread** — listens on control port for JOIN/LEAVE/HEARTBEAT messages

3. **Modified `UDPBroadcaster.send_data()`** — iterates over all active clients instead of a single target IP

4. **Updated CLI** — no longer requires a target IP; accepts `--port` flag

5. **Console dashboard** — prints connected client count alongside FPS stats

---

### Receiver

#### [MODIFY] [receiver.py](file:///s:/mirror-space/receiver.py)

1. **New registration logic** — sends JOIN on startup, HEARTBEAT every 3s (separate thread), LEAVE on shutdown

2. **Updated CLI** — first argument is now the **broadcaster's IP** (required), optional `--port` and `--name`

3. **Connection status display** — prints "Connected to broadcaster at X.X.X.X" on WELCOME receipt

---

### Diff Encoder

#### No changes to [diff_encoder.py](file:///s:/mirror-space/diff_encoder.py)

The encoding/decoding logic is completely independent of transport and requires no modifications.

---

### Documentation

#### [MODIFY] [README.md](file:///s:/mirror-space/README.md)

- Update Quick Start and Usage sections with new multi-viewer CLI
- Add "Multi-Viewer" section explaining how to connect multiple receivers

## Verification Plan

### Manual Verification (Recommended)

Since this is a real-time networking application with GUI windows, automated testing is impractical. Here's how to manually verify:

**Test 1: Single Receiver (Backward Compatibility)**
1. Open Terminal 1: `python broadcaster.py`
2. Open Terminal 2: `python receiver.py 127.0.0.1`
3. ✅ Verify receiver window shows the screen stream
4. ✅ Verify broadcaster console shows "1 client connected"

**Test 2: Multiple Receivers**
1. Open Terminal 1: `python broadcaster.py`
2. Open Terminal 2: `python receiver.py 127.0.0.1 --name Viewer1`
3. Open Terminal 3: `python receiver.py 127.0.0.1 --name Viewer2`
4. ✅ Verify both receiver windows show the stream
5. ✅ Verify broadcaster console shows "2 clients connected"

**Test 3: Graceful Disconnect**
1. Start broadcaster + 2 receivers (as above)
2. Press `q` in Viewer1's window to quit
3. ✅ Verify broadcaster shows "1 client connected" after disconnect
4. ✅ Verify Viewer2 continues streaming normally

**Test 4: Stale Client Pruning**
1. Start broadcaster + 1 receiver
2. Kill the receiver process (Ctrl+C or force close — no graceful LEAVE)
3. ✅ Verify broadcaster removes the client after ~10 seconds

> [!NOTE]
> I will do Tests 1-3 myself using the browser/terminal tools. Test 4 can be verified by reading the code logic for the timeout.
