# mediamtx Simulcast Egress Patch

Patches mediamtx to forward all WebRTC simulcast layers (H264) via WHEP.

## Changed files

- `internal/protocols/webrtc/from_stream.go` — iterate ALL H264 video medias
- `internal/protocols/webrtc/outgoing_track.go` — RID field for layer IDs
- `internal/servers/webrtc/read_index.html` — simulcast player with ABR, RTT

## Apply patch
```bash
git clone --depth=1 https://github.com/bluenviron/mediamtx
cd mediamtx
cp /path/to/patch/internal/protocols/webrtc/from_stream.go    internal/protocols/webrtc/
cp /path/to/patch/internal/protocols/webrtc/outgoing_track.go internal/protocols/webrtc/
cp /path/to/patch/internal/servers/webrtc/read_index.html     internal/servers/webrtc/
go generate ./...
go build -o mediamtx-simulcast ./
```

## Features
- All 3 simulcast layers (H264) forwarded in a single WHEP connection
- Layer menu HIGH/MED/LOW with live bitrate
- ABR auto-switching (packet loss + FPS based)
- RTT and estimated one-way latency in HUD
- Volume, mute, fullscreen, PiP controls
