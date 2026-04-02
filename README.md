# mediamtx Simulcast Egress Patch

Patches [mediamtx](https://github.com/bluenviron/mediamtx) to forward all WebRTC simulcast layers via WHEP, enabling per-layer selection in the browser player.

## Features

- All simulcast layers (H264, H265, AV1, VP9) forwarded in a single WHEP connection
- Layer menu (HIGH / MED / LOW) with live bitrate and resolution display
- **ABR auto-switching** based on packet loss and FPS — instant, no reconnect
- **Manual layer selection** — reconnects with `?layer=N`, server sends only that track (bandwidth saving)
- Play-on-demand: stream only starts when Play is pressed
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

# 3. Apply patches
python3 /tmp/simulcast-patch/contrib/patch_simulcast.py      # v1: H264 simulcast egress
python3 /tmp/simulcast-patch/contrib/patch_simulcast_v2.py   # v2: H265/AV1/VP9 support
python3 /tmp/simulcast-patch/contrib/patch_layer_select.py   # v3: manual layer = single track

# 4. Copy player
cp /tmp/simulcast-patch/internal/servers/webrtc/read_index.html \
   internal/servers/webrtc/read_index.html

# 5. Build
go generate ./...
go build -o mediamtx-simulcast ./

# 6. Run
./mediamtx-simulcast mediamtx.yml
```

## OBS Setup

Enable Simulcast in OBS: **Settings → Output → Streaming → Enable Simulcast**

Publish via WHIP to mediamtx:
```
http://<server>:8889/<path>/whip
```

Open player in browser:
```
http://<server>:8889/<path>
```

## How It Works

### Modes

| Mode | Connection | Bandwidth | Layer switching |
|---|---|---|---|
| **AUTO (ABR)** | 1 WHEP, all tracks | all layers | instant, no reconnect |
| **Manual** | 1 WHEP with `?layer=N` | single layer only | ~1s reconnect |

### ABR Logic

Switches down when: packet loss > 2.5% **or** FPS drops > 25% below expected (sustained 3s)

Switches up when: packet loss < 0.5% **and** FPS stable (sustained 8s)

### Server-Side Layer Filtering

When `?layer=N` is present in the WHEP URL, mediamtx only includes the Nth video track in the PeerConnection. Other tracks are registered but discarded via a nil guard in `outgoing_track.go`.

## Changed Files

| File | Change |
|---|---|
| `internal/protocols/webrtc/from_stream.go` | Iterate ALL video medias; `layerIndex` filtering |
| `internal/protocols/webrtc/outgoing_track.go` | RID field; nil guard for unselected tracks |
| `internal/servers/webrtc/session.go` | Read `?layer=N` query parameter |
| `internal/servers/webrtc/read_index.html` | Full-featured simulcast player |

## Patch Scripts

| Script | Description |
|---|---|
| `contrib/patch_simulcast.py` | v1: H264 simulcast egress (all layers via WHEP) |
| `contrib/patch_simulcast_v2.py` | v2: Extend to H265, AV1, VP9 |
| `contrib/patch_layer_select.py` | v3: `?layer=N` server-side filtering + updated player |

## Supported Simulcast Codecs

| Codec | Publisher | Notes |
|---|---|---|
| H264 | OBS 30+ | Works today |
| H265 | OBS 31+ | HEVC simulcast |
| AV1 | OBS 31+ with SVT-AV1 | Requires capable hardware |
| VP9 | GStreamer / FFmpeg | OBS doesn't natively simulcast VP9 |
