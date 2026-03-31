#!/usr/bin/env python3
"""
mediamtx Simulcast Egress Patch — v2
======================================
Extends setupVideoTracks() to support simulcast for:
  - H264  (was already done in v1)
  - H265  (new)
  - AV1   (new)
  - VP9   (new — less common but possible)

Run from the mediamtx repo root:
  python3 patch_simulcast_v2.py
"""
import re, sys
from pathlib import Path

FROM_STREAM = Path("internal/protocols/webrtc/from_stream.go")

def fatal(msg):
    print(f"FEHLER: {msg}", file=sys.stderr)
    sys.exit(1)

if not FROM_STREAM.exists():
    fatal(f"{FROM_STREAM} not found — run from mediamtx repo root")

src = FROM_STREAM.read_text()

if "setupVideoTracks" not in src:
    fatal("v1 patch not applied yet — run patch_simulcast.py first")

if "simulcast_v2" in src:
    print("v2 patch already applied — nothing to do")
    sys.exit(0)

# ──────────────────────────────────────────────────────────────────────
# Find setupVideoTracks function and replace the H264-only loop
# with a codec-agnostic loop that handles H264, H265, AV1, VP9.
# ──────────────────────────────────────────────────────────────────────

# The function currently looks like:
#
# func setupVideoTracks(...) ([]*OutgoingTrack, error) {
#     var tracks []*OutgoingTrack
#
#     // AV1, VP9, VP8, H265: wie bisher (erster Match)
#     singleTrack, err := setupFirstVideoTrack(desc, r)
#     ...
#     if singleTrack != nil { return ..., nil }
#
#     // H264: ALLE Medias durchlaufen (Simulcast)
#     for _, media := range desc.Medias {
#         var h264Format *format.H264
#         for _, f := range media.Formats {
#             if v, ok := f.(*format.H264); ok { h264Format = v; break }
#         }
#         if h264Format == nil { continue }
#         ... build track ...
#         tracks = append(tracks, track)
#     }
#     return tracks, nil
# }

# We replace the entire body of setupVideoTracks with a version that:
# 1. Detects which codec is used for simulcast (finds codec with >1 media)
# 2. Builds a track per media for that codec
# 3. Falls back to setupFirstVideoTrack for single-track codecs

old_fn_start = "func setupVideoTracks("
if old_fn_start not in src:
    fatal("setupVideoTracks not found in from_stream.go")

fn_start = src.index(old_fn_start)

# Find the end of setupVideoTracks (next top-level func)
next_fn = re.search(r'\nfunc ', src[fn_start + 1:])
if not next_fn:
    fatal("Could not find end of setupVideoTracks")
fn_end = fn_start + 1 + next_fn.start()

old_fn = src[fn_start:fn_end]

new_fn = '''// simulcast_v2
// setupVideoTracks returns one OutgoingTrack per video rendition.
// Supports simulcast for H264, H265, AV1, VP9 — any codec that appears
// in more than one media section is forwarded as separate tracks.
func setupVideoTracks(
\tdesc *description.Session,
\tr *stream.Reader,
) ([]*OutgoingTrack, error) {
\t// Count how many media sections exist per codec
\tcodecCount := map[string]int{}
\tfor _, media := range desc.Medias {
\t\tfor _, f := range media.Formats {
\t\t\tswitch f.(type) {
\t\t\tcase *format.H264:
\t\t\t\tcodecCount["h264"]++
\t\t\tcase *format.H265:
\t\t\t\tcodecCount["h265"]++
\t\t\tcase *format.AV1:
\t\t\t\tcodecCount["av1"]++
\t\t\tcase *format.VP9:
\t\t\t\tcodecCount["vp9"]++
\t\t\t}
\t\t}
\t}

\t// Find the simulcast codec (most media sections > 1)
\tsimulcastCodec := ""
\tsimulcastCount := 0
\tfor codec, count := range codecCount {
\t\tif count > simulcastCount {
\t\t\tsimulcastCount = count
\t\t\tsimulcastCodec = codec
\t\t}
\t}

\t// Single track or no simulcast — use original behavior
\tif simulcastCount <= 1 {
\t\tt, err := setupFirstVideoTrack(desc, r)
\t\tif err != nil {
\t\t\treturn nil, err
\t\t}
\t\tif t != nil {
\t\t\treturn []*OutgoingTrack{t}, nil
\t\t}
\t\treturn nil, nil
\t}

\t// Simulcast: build one track per media section for the detected codec
\tvar tracks []*OutgoingTrack
\tfor _, media := range desc.Medias {
\t\tvar track *OutgoingTrack
\t\tvar err error

\t\tswitch simulcastCodec {
\t\tcase "h264":
\t\t\ttrack, err = buildH264Track(media, r)
\t\tcase "h265":
\t\t\ttrack, err = buildH265Track(media, r)
\t\tcase "av1":
\t\t\ttrack, err = buildAV1Track(media, r)
\t\tcase "vp9":
\t\t\ttrack, err = buildVP9Track(media, r)
\t\t}
\t\tif err != nil {
\t\t\treturn nil, err
\t\t}
\t\tif track != nil {
\t\t\ttracks = append(tracks, track)
\t\t}
\t}
\treturn tracks, nil
}

// buildH264Track builds an OutgoingTrack for an H264 media section.
func buildH264Track(
\tmedia *description.Media,
\tr *stream.Reader,
) (*OutgoingTrack, error) {
\tvar h264Format *format.H264
\tfor _, f := range media.Formats {
\t\tif v, ok := f.(*format.H264); ok {
\t\t\th264Format = v
\t\t\tbreak
\t\t}
\t}
\tif h264Format == nil {
\t\treturn nil, nil
\t}

\ttrack := &OutgoingTrack{
\t\tCaps: webrtc.RTPCodecCapability{
\t\t\tMimeType:    webrtc.MimeTypeH264,
\t\t\tClockRate:   90000,
\t\t\tSDPFmtpLine: "level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f",
\t\t},
\t}
\tencoder := &rtph264.Encoder{
\t\tPayloadType:    96,
\t\tPayloadMaxSize: webrtcPayloadMaxSize,
\t}
\tif err := encoder.Init(); err != nil {
\t\treturn nil, err
\t}
\tfirstReceived := false
\tvar lastPTS int64
\tr.OnData(media, h264Format, func(u *unit.Unit) error {
\t\tif u.NilPayload() {
\t\t\treturn nil
\t\t}
\t\tif !firstReceived {
\t\t\tfirstReceived = true
\t\t} else if u.PTS < lastPTS {
\t\t\treturn fmt.Errorf("WebRTC doesn\'t support H264 streams with B-frames")
\t\t}
\t\tlastPTS = u.PTS
\t\tpackets, err := encoder.Encode(u.Payload.(unit.PayloadH264))
\t\tif err != nil {
\t\t\treturn nil //nolint:nilerr
\t\t}
\t\tfor _, pkt := range packets {
\t\t\tntp := u.NTP.Add(timestampToDuration(int64(pkt.Timestamp), 90000))
\t\t\tpkt.Timestamp += u.RTPPackets[0].Timestamp
\t\t\ttrack.WriteRTPWithNTP(pkt, ntp) //nolint:errcheck
\t\t}
\t\treturn nil
\t})
\treturn track, nil
}

// buildH265Track builds an OutgoingTrack for an H265 media section.
func buildH265Track(
\tmedia *description.Media,
\tr *stream.Reader,
) (*OutgoingTrack, error) {
\tvar h265Format *format.H265
\tfor _, f := range media.Formats {
\t\tif v, ok := f.(*format.H265); ok {
\t\t\th265Format = v
\t\t\tbreak
\t\t}
\t}
\tif h265Format == nil {
\t\treturn nil, nil
\t}

\ttrack := &OutgoingTrack{
\t\tCaps: webrtc.RTPCodecCapability{
\t\t\tMimeType:    webrtc.MimeTypeH265,
\t\t\tClockRate:   90000,
\t\t\tSDPFmtpLine: "level-id=93;profile-id=1;tier-flag=0;tx-mode=SRST",
\t\t},
\t}
\tencoder := &rtph265.Encoder{
\t\tPayloadType:    96,
\t\tPayloadMaxSize: webrtcPayloadMaxSize,
\t}
\tif err := encoder.Init(); err != nil {
\t\treturn nil, err
\t}
\tfirstReceived := false
\tvar lastPTS int64
\tr.OnData(media, h265Format, func(u *unit.Unit) error {
\t\tif u.NilPayload() {
\t\t\treturn nil
\t\t}
\t\tif !firstReceived {
\t\t\tfirstReceived = true
\t\t} else if u.PTS < lastPTS {
\t\t\treturn fmt.Errorf("WebRTC doesn\'t support H265 streams with B-frames")
\t\t}
\t\tlastPTS = u.PTS
\t\tpackets, err := encoder.Encode(u.Payload.(unit.PayloadH265))
\t\tif err != nil {
\t\t\treturn nil //nolint:nilerr
\t\t}
\t\tfor _, pkt := range packets {
\t\t\tntp := u.NTP.Add(timestampToDuration(int64(pkt.Timestamp), 90000))
\t\t\tpkt.Timestamp += u.RTPPackets[0].Timestamp
\t\t\ttrack.WriteRTPWithNTP(pkt, ntp) //nolint:errcheck
\t\t}
\t\treturn nil
\t})
\treturn track, nil
}

// buildAV1Track builds an OutgoingTrack for an AV1 media section.
func buildAV1Track(
\tmedia *description.Media,
\tr *stream.Reader,
) (*OutgoingTrack, error) {
\tvar av1Format *format.AV1
\tfor _, f := range media.Formats {
\t\tif v, ok := f.(*format.AV1); ok {
\t\t\tav1Format = v
\t\t\tbreak
\t\t}
\t}
\tif av1Format == nil {
\t\treturn nil, nil
\t}

\ttrack := &OutgoingTrack{
\t\tCaps: webrtc.RTPCodecCapability{
\t\t\tMimeType:  webrtc.MimeTypeAV1,
\t\t\tClockRate: 90000,
\t\t},
\t}
\tencoder := &rtpav1.Encoder{
\t\tPayloadType:    105,
\t\tPayloadMaxSize: webrtcPayloadMaxSize,
\t}
\tif err := encoder.Init(); err != nil {
\t\treturn nil, err
\t}
\tr.OnData(media, av1Format, func(u *unit.Unit) error {
\t\tif u.NilPayload() {
\t\t\treturn nil
\t\t}
\t\tpackets, err := encoder.Encode(u.Payload.(unit.PayloadAV1))
\t\tif err != nil {
\t\t\treturn nil //nolint:nilerr
\t\t}
\t\tfor _, pkt := range packets {
\t\t\tntp := u.NTP.Add(timestampToDuration(int64(pkt.Timestamp), 90000))
\t\t\tpkt.Timestamp += u.RTPPackets[0].Timestamp
\t\t\ttrack.WriteRTPWithNTP(pkt, ntp) //nolint:errcheck
\t\t}
\t\treturn nil
\t})
\treturn track, nil
}

// buildVP9Track builds an OutgoingTrack for a VP9 media section.
func buildVP9Track(
\tmedia *description.Media,
\tr *stream.Reader,
) (*OutgoingTrack, error) {
\tvar vp9Format *format.VP9
\tfor _, f := range media.Formats {
\t\tif v, ok := f.(*format.VP9); ok {
\t\t\tvp9Format = v
\t\t\tbreak
\t\t}
\t}
\tif vp9Format == nil {
\t\treturn nil, nil
\t}

\ttrack := &OutgoingTrack{
\t\tCaps: webrtc.RTPCodecCapability{
\t\t\tMimeType:    webrtc.MimeTypeVP9,
\t\t\tClockRate:   90000,
\t\t\tSDPFmtpLine: "profile-id=0",
\t\t},
\t}
\tencoder := &rtpvp9.Encoder{
\t\tPayloadType:      96,
\t\tPayloadMaxSize:   webrtcPayloadMaxSize,
\t\tInitialPictureID: ptrOf(uint16(8445)),
\t}
\tif err := encoder.Init(); err != nil {
\t\treturn nil, err
\t}
\tr.OnData(media, vp9Format, func(u *unit.Unit) error {
\t\tif u.NilPayload() {
\t\t\treturn nil
\t\t}
\t\tpackets, err := encoder.Encode(u.Payload.(unit.PayloadVP9))
\t\tif err != nil {
\t\t\treturn nil //nolint:nilerr
\t\t}
\t\tfor _, pkt := range packets {
\t\t\tntp := u.NTP.Add(timestampToDuration(int64(pkt.Timestamp), 90000))
\t\t\tpkt.Timestamp += u.RTPPackets[0].Timestamp
\t\t\ttrack.WriteRTPWithNTP(pkt, ntp) //nolint:errcheck
\t\t}
\t\treturn nil
\t})
\treturn track, nil
}

'''

# Replace the old setupVideoTracks function
new_src = src[:fn_start] + new_fn + src[fn_end:]

# Also remove the old H264-only helper functions that are now inlined
# (buildH264Track replaces the inline loop we added in v1)
# The setupFirstVideoTrack function stays — it handles single-track fallback

FROM_STREAM.write_text(new_src)
print(f"✓ {FROM_STREAM} patched with H264/H265/AV1/VP9 simulcast support")

# ── Syntax check ──────────────────────────────────────────────────────
import subprocess
result = subprocess.run(
    ["go", "vet", "./internal/protocols/webrtc/..."],
    capture_output=True, text=True
)
if result.returncode != 0:
    print("\nWARNING: go vet errors — manual review needed:")
    print(result.stdout)
    print(result.stderr)
else:
    print("✓ go vet passed")

print("""
Done! Now build:
  go generate ./...
  go build -o mediamtx-simulcast ./

OBS simulcast with H265: requires OBS 31+ with HEVC simulcast support.
AV1 simulcast: requires OBS 31+ with AV1 encoder (e.g. SVT-AV1).
""")
