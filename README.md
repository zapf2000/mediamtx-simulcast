# mediamtx Simulcast Egress Patch

Patches [mediamtx](https://github.com/bluenviron/mediamtx) to forward all WebRTC simulcast layers via WHEP, enabling per-layer selection in the browser player. Also fixes OBS Linux WHIP publishing compatibility.

## Features

- All simulcast layers (H264, H265, AV1, VP9) forwarded in a single WHEP connection
- Layer menu (HIGH / MED / LOW) with live bitrate and resolution display
- **ABR auto-switching** based on packet loss — instant switching, no reconnect
- **Manual layer selection** — reconnects with `?layer=N`, server sends only that track (saves bandwidth)
- Tracks automatically sorted by resolution (highest quality first) — important for downstream transcoders
- Play-on-demand: no stream data until Play is pressed
- Pause closes the WHEP connection entirely (zero bandwidth)
- RTT and estimated one-way latency in HUD
- Volume, mute, fullscreen, Picture-in-Picture controls

## Quick Start

```bash
# 1. Clone mediamtx
git clone --depth=1 https://github.com/bluenviron/mediamtx
cd mediamtx

# 2. Clone this patch repo
git clone https://github.com/zapf2000/mediamtx-simulcast /tmp/simulcast-patch

# 3. Copy patched files
cp /tmp/simulcast-patch/internal/protocols/webrtc/from_stream.go    internal/protocols/webrtc/
cp /tmp/simulcast-patch/internal/protocols/webrtc/outbound_track.go internal/protocols/webrtc/
cp /tmp/simulcast-patch/internal/protocols/webrtc/inbound_track.go  internal/protocols/webrtc/
cp /tmp/simulcast-patch/internal/protocols/webrtc/to_stream.go      internal/protocols/webrtc/
cp /tmp/simulcast-patch/internal/protocols/webrtc/peer_connection.go internal/protocols/webrtc/
cp /tmp/simulcast-patch/internal/servers/webrtc/session.go          internal/servers/webrtc/
cp /tmp/simulcast-patch/internal/servers/webrtc/http_server.go      internal/servers/webrtc/
cp /tmp/simulcast-patch/internal/servers/webrtc/read_index.html     internal/servers/webrtc/

# 4. Pin pion versions (required for OBS Linux compatibility)
cp /tmp/simulcast-patch/go.mod .
cp /tmp/simulcast-patch/go.sum .

# 5. Build
go generate ./...
go build -o mediamtx-simulcast ./

# 6. Run
./mediamtx-simulcast mediamtx.yml
```

## OBS Setup

Enable Simulcast in OBS: **Settings → Output → Streaming → Enable Simulcast**

Publish via WHIP:
```
https://<server>:8889/<path>/whip
```

Open player in browser:
```
https://<server>:8889/<path>
```

## How It Works

### Playback Modes

| Mode | Connection | Bandwidth | Layer switching |
|---|---|---|---|
| **AUTO (ABR)** | 1 WHEP, all tracks received | all layers | instant, no reconnect |
| **Manual** | 1 WHEP with `?layer=N` | single layer only | ~1s reconnect |

### ABR Logic

Switches **down** when: packet loss > 8% sustained for 10 seconds

Switches **up** when: packet loss < 1% sustained for 45 seconds

### Server-Side Layer Filtering

When `?layer=N` is present in the WHEP URL, mediamtx only sends the Nth video track to the client. Unselected tracks are registered but discarded via a nil guard — no RTP packets are forwarded for them.

### Track Ordering

Incoming simulcast tracks are sorted by RID (`rid:0` = highest quality in OBS). If SPS data is available, tracks are additionally sorted by decoded resolution. This ensures index 0 is always the best quality — important for downstream transcoders that pick the first track.

## Changed Files

| File | Change |
|---|---|
| `internal/protocols/webrtc/from_stream.go` | Simulcast egress; H264/H265/AV1/VP9 support; layer filtering; resolution sort |
| `internal/protocols/webrtc/outbound_track.go` | RID field; nil guard for unselected tracks |
| `internal/protocols/webrtc/inbound_track.go` | `RID()` method |
| `internal/protocols/webrtc/to_stream.go` | Sort incoming tracks by RID before building media description |
| `internal/protocols/webrtc/peer_connection.go` | DTLS passive role for WHIP; strip non-standard `ufrag` from candidates |
| `internal/servers/webrtc/session.go` | Read `?layer=N` query parameter |
| `internal/servers/webrtc/http_server.go` | Remove `Accept-Patch` header (breaks OBS Linux ICE) |
| `internal/servers/webrtc/read_index.html` | Full-featured simulcast player |

## OBS Linux Compatibility

OBS on Linux uses **libdatachannel** instead of libwebrtc. Several fixes were required:

| Fix | Reason |
|---|---|
| Remove `Accept-Patch` response header | libdatachannel stops ICE when this header is present |
| DTLS passive role for WHIP sessions | libdatachannel requires the server to be DTLS passive |
| `pion/dtls` pinned to v3.1.4 | v3.1.3 was retracted due to broken DTLS interoperability |
| Strip `ufrag XXXX` extension from candidates | pion appends non-standard extension that libdatachannel rejects |

## Supported Simulcast Codecs

| Codec | Publisher | Notes |
|---|---|---|
| H264 | OBS 30+ | Fully tested |
| H265 | OBS 31+ | HEVC simulcast |
| AV1 | OBS 31+ with SVT-AV1 | Requires capable hardware |
| VP9 | GStreamer / FFmpeg | OBS doesn't natively simulcast VP9 |

## Pinned Dependencies

```
github.com/pion/dtls/v3  v3.1.4   — fixes DTLS interop regression
github.com/pion/webrtc/v4 v4.2.15
github.com/pion/ice/v4   v4.2.7
```
