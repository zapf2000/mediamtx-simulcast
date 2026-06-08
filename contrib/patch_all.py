#!/usr/bin/env python3
"""
mediamtx Simulcast Egress — Complete Patch (neue Version)
==========================================================
Funktioniert mit mediamtx >= v1.12 (OutboundTrack/InboundTrack Naming).

Führe aus dem mediamtx-Root aus:
  python3 patch_all.py
  cp read_index.html internal/servers/webrtc/
  go generate ./...
  go build -o mediamtx-simulcast ./
"""
import re, subprocess, sys
from pathlib import Path

def fatal(msg):
    print(f"\nFEHLER: {msg}", file=sys.stderr); sys.exit(1)

def check_files():
    for p in [
        "internal/protocols/webrtc/from_stream.go",
        "internal/protocols/webrtc/outbound_track.go",
        "internal/protocols/webrtc/inbound_track.go",
        "internal/protocols/webrtc/to_stream.go",
        "internal/servers/webrtc/session.go",
    ]:
        if not Path(p).exists():
            fatal(f"{p} nicht gefunden — aus dem mediamtx-Root ausführen")

def go_build():
    r = subprocess.run(["go", "build", "./..."], capture_output=True, text=True)
    if r.returncode != 0:
        print("Build-Fehler:"); print(r.stdout); print(r.stderr)
        return False
    return True

# ══════════════════════════════════════════════════════════════════════
# outbound_track.go — nil guard + RID field
# ══════════════════════════════════════════════════════════════════════
def patch_outbound_track():
    f = Path("internal/protocols/webrtc/outbound_track.go")
    src = f.read_text()
    changed = False

    if "outbound_track_patched" not in src:
        src = src.replace(
            "type OutboundTrack struct {",
            "// outbound_track_patched\ntype OutboundTrack struct {\n\tRID string // Simulcast Rendition ID"
        )
        changed = True

    # nil guard in WriteRTPWithNTP
    m = re.search(r'func \(t \*OutboundTrack\) WriteRTPWithNTP\([^)]+\) error \{', src)
    if m and 'rtcpSender == nil' not in src[m.end():m.end()+60]:
        src = src[:m.end()] + '\n\tif t.rtcpSender == nil { return nil }' + src[m.end():]
        changed = True

    # nil guard in WriteRTP
    m2 = re.search(r'func \(t \*OutboundTrack\) WriteRTP\([^)]+\) error \{', src)
    if m2 and 'rtcpSender == nil' not in src[m2.end():m2.end()+60]:
        src = src[:m2.end()] + '\n\tif t.rtcpSender == nil { return nil }' + src[m2.end():]
        changed = True

    if changed:
        f.write_text(src)
        print("  [outbound_track.go] RID-Feld + nil-Guard ✓")
    else:
        print("  [outbound_track.go] bereits gepatcht")

# ══════════════════════════════════════════════════════════════════════
# inbound_track.go — RID() method
# ══════════════════════════════════════════════════════════════════════
def patch_inbound_track():
    f = Path("internal/protocols/webrtc/inbound_track.go")
    src = f.read_text()

    if "func (t *InboundTrack) RID()" in src:
        print("  [inbound_track.go] bereits gepatcht"); return

    src = src.replace(
        "func (t *InboundTrack) Codec() webrtc.RTPCodecParameters {",
        "func (t *InboundTrack) RID() string {\n\treturn t.rid\n}\n\nfunc (t *InboundTrack) Codec() webrtc.RTPCodecParameters {"
    )
    f.write_text(src)
    print("  [inbound_track.go] RID()-Methode ✓")

# ══════════════════════════════════════════════════════════════════════
# to_stream.go — sort by RID
# ══════════════════════════════════════════════════════════════════════
def patch_to_stream():
    f = Path("internal/protocols/webrtc/to_stream.go")
    src = f.read_text()

    if "Sort inbound tracks by RID" in src:
        print("  [to_stream.go] bereits gepatcht"); return

    if '"slices"' not in src:
        src = src.replace('import (', 'import (\n\t"slices"')

    # Find the main loop over inbound tracks
    # Pattern: for _, t := range pc.InboundTracks() {
    old_loop = 'for _, t := range pc.InboundTracks() {'
    if old_loop not in src:
        print("  [to_stream.go] WARNUNG: InboundTracks()-Loop nicht gefunden"); return

    # Add sort before the loop
    sort_code = (
        '\t// Sort inbound tracks by RID ascending (rid "0" = highest quality in OBS simulcast)\n'
        '\tinboundTracks := pc.InboundTracks()\n'
        '\tslices.SortStableFunc(inboundTracks, func(a, b *InboundTrack) int {\n'
        '\t\tra, rb := a.RID(), b.RID()\n'
        '\t\tif ra != "" && rb != "" {\n'
        '\t\t\tif ra < rb { return -1 }\n'
        '\t\t\tif ra > rb { return 1 }\n'
        '\t\t}\n'
        '\t\treturn 0\n'
        '\t})\n\t'
    )
    src = src.replace('\t' + old_loop, sort_code + 'for _, t := range inboundTracks {')
    f.write_text(src)
    print("  [to_stream.go] RID-Sortierung ✓")

# ══════════════════════════════════════════════════════════════════════
# from_stream.go — simulcast egress + layer select + res sort
# ══════════════════════════════════════════════════════════════════════
def patch_from_stream():
    f = Path("internal/protocols/webrtc/from_stream.go")
    src = f.read_text()

    # ── imports ──
    if 'codecsh264' not in src:
        src = src.replace(
            '"github.com/bluenviron/gortsplib/v5/pkg/description"\n\t"github.com/bluenviron/gortsplib/v5/pkg/format"',
            '"github.com/bluenviron/gortsplib/v5/pkg/description"\n\t"github.com/bluenviron/gortsplib/v5/pkg/format"\n'
            '\tcodecsh264 "github.com/bluenviron/mediacommon/v2/pkg/codecs/h264"\n'
            '\tcodecsh265 "github.com/bluenviron/mediacommon/v2/pkg/codecs/h265"'
        )
        print("  [from_stream.go] Imports ✓")

    # ── setupVideoTracks (simulcast) ──
    if "setupVideoTracks" not in src:
        old_sig = ("func setupVideoTrack(\n"
                   "\tdesc *description.Session,\n"
                   "\tr *stream.Reader,\n"
                   ") (*OutboundTrack, error) {")

        if old_sig not in src:
            fatal("setupVideoTrack Signatur nicht gefunden — andere mediamtx-Version?")

        fn_start = src.index(old_sig)
        # Find next top-level func
        rest = src[fn_start+1:]
        m = re.search(r'\nfunc ', rest)
        fn_end = fn_start + 1 + (m.start() if m else len(rest))

        new_fns = _simulcast_functions()
        src = src[:fn_start] + new_fns + src[fn_end:]
        print("  [from_stream.go] setupVideoTracks + Hilfsfunktionen ✓")

    # ── FromStream layerIndex ──
    if "layer_select_patched" not in src:
        old_sig2 = ("func FromStream(\n"
                    "\tdesc *description.Session,\n"
                    "\tr *stream.Reader,\n"
                    "\tpc *PeerConnection,\n"
                    ") error {")
        if old_sig2 in src:
            src = src.replace(old_sig2,
                "// layer_select_patched\n"
                "func FromStream(\n"
                "\tdesc *description.Session,\n"
                "\tr *stream.Reader,\n"
                "\tpc *PeerConnection,\n"
                "\tlayerIndex int,\n"
                ") error {")

        # Fix videoTrack append → videoTracks with layerIndex
        m = re.search(
            r'(\tvideoTracks?, err := setup[Vv]ideo[Tt]rack[s]?\(desc, r\)\n'
            r'\tif err != nil \{\n\t\treturn err\n\t\}\n'
            r'\n?\t(?:if videoTrack[s]? != nil \{[^}]*\}|pc\.OutgoingTracks = append[^\n]+))',
            src, re.DOTALL
        )
        if m:
            src = src[:m.start()] + (
                '\tvideoTracks, err := setupVideoTracks(desc, r)\n'
                '\tif err != nil {\n\t\treturn err\n\t}\n\n'
                '\tif layerIndex >= 0 && layerIndex < len(videoTracks) {\n'
                '\t\tpc.OutboundTracks = append(pc.OutboundTracks, videoTracks[layerIndex])\n'
                '\t} else {\n'
                '\t\tpc.OutboundTracks = append(pc.OutboundTracks, videoTracks...)\n'
                '\t}'
            ) + src[m.end():]
            print("  [from_stream.go] Layer-Filterung ✓")
        else:
            # Try simpler pattern
            old_append = '\tvideoTrack, err := setupVideoTrack(desc, r)\n\tif err != nil {\n\t\treturn err\n\t}\n\tif videoTrack != nil {\n\t\tpc.OutboundTracks = append(pc.OutboundTracks, videoTrack)\n\t}'
            if old_append in src:
                src = src.replace(old_append,
                    '\tvideoTracks, err := setupVideoTracks(desc, r)\n'
                    '\tif err != nil {\n\t\treturn err\n\t}\n'
                    '\tif layerIndex >= 0 && layerIndex < len(videoTracks) {\n'
                    '\t\tpc.OutboundTracks = append(pc.OutboundTracks, videoTracks[layerIndex])\n'
                    '\t} else {\n'
                    '\t\tpc.OutboundTracks = append(pc.OutboundTracks, videoTracks...)\n'
                    '\t}')
                print("  [from_stream.go] Layer-Filterung (alt) ✓")
            else:
                print("  [from_stream.go] WARNUNG: videoTrack-Append nicht gefunden")

    f.write_text(src)
    print("  [from_stream.go] Gespeichert ✓")

def _simulcast_functions():
    return '''// simulcast_v2
// setupVideoTracks returns one OutboundTrack per video rendition.
func setupVideoTracks(
\tdesc *description.Session,
\tr *stream.Reader,
) ([]*OutboundTrack, error) {
\tcodecCount := map[string]int{}
\tfor _, media := range desc.Medias {
\t\tfor _, f := range media.Formats {
\t\t\tswitch f.(type) {
\t\t\tcase *format.H264: codecCount["h264"]++
\t\t\tcase *format.H265: codecCount["h265"]++
\t\t\tcase *format.AV1:  codecCount["av1"]++
\t\t\tcase *format.VP9:  codecCount["vp9"]++
\t\t\t}
\t\t}
\t}
\tsimucastCodec, simulcastCount := "", 0
\tfor codec, count := range codecCount {
\t\tif count > simulcastCount {
\t\t\tsimucastCount = count
\t\t\tsimucastCodec = codec
\t\t}
\t}
\tif simulcastCount <= 1 {
\t\tt, err := setupVideoTrack(desc, r)
\t\tif err != nil { return nil, err }
\t\tif t != nil { return []*OutboundTrack{t}, nil }
\t\treturn nil, nil
\t}
\tvar tracks []*OutboundTrack
\tfor _, media := range desc.Medias {
\t\tvar (track *OutboundTrack; err error)
\t\tswitch simulcastCodec {
\t\tcase "h264": track, err = buildH264Track(media, r)
\t\tcase "h265": track, err = buildH265Track(media, r)
\t\tcase "av1":  track, err = buildAV1Track(media, r)
\t\tcase "vp9":  track, err = buildVP9Track(media, r)
\t\t}
\t\tif err != nil { return nil, err }
\t\tif track != nil { tracks = append(tracks, track) }
\t}
\treturn sortTracksByResolution(tracks, desc), nil
}

func sortTracksByResolution(tracks []*OutboundTrack, desc *description.Session) []*OutboundTrack {
\tif len(tracks) <= 1 { return tracks }
\ttype tw struct{ t *OutboundTrack; px int }
\tvar wl []tw
\tvideoMedias := []*description.Media{}
\tfor _, media := range desc.Medias {
\t\tfor _, f := range media.Formats {
\t\t\tswitch f.(type) {
\t\t\tcase *format.H264, *format.H265, *format.AV1, *format.VP9:
\t\t\t\tvideoMedias = append(videoMedias, media)
\t\t\t}
\t\t\tbreak
\t\t}
\t}
\tfor i, t := range tracks {
\t\tpx := 0
\t\tif i < len(videoMedias) {
\t\t\tfor _, f := range videoMedias[i].Formats {
\t\t\t\tswitch v := f.(type) {
\t\t\t\tcase *format.H264:
\t\t\t\t\tif len(v.SPS) > 0 {
\t\t\t\t\t\tvar s codecsh264.SPS
\t\t\t\t\t\tif e := s.Unmarshal(v.SPS); e == nil { px = s.Width() * s.Height() }
\t\t\t\t\t}
\t\t\t\tcase *format.H265:
\t\t\t\t\tif len(v.SPS) > 0 {
\t\t\t\t\t\tvar s codecsh265.SPS
\t\t\t\t\t\tif e := s.Unmarshal(v.SPS); e == nil { px = s.Width() * s.Height() }
\t\t\t\t\t}
\t\t\t\t}
\t\t\t\tbreak
\t\t\t}
\t\t}
\t\twl = append(wl, tw{t, px})
\t}
\tslices.SortStableFunc(wl, func(a, b tw) int { return b.px - a.px })
\tres := make([]*OutboundTrack, len(wl))
\tfor i, w := range wl { res[i] = w.t }
\treturn res
}

func buildH264Track(media *description.Media, r *stream.Reader) (*OutboundTrack, error) {
\tvar h264Format *format.H264
\tfor _, f := range media.Formats {
\t\tif v, ok := f.(*format.H264); ok { h264Format = v; break }
\t}
\tif h264Format == nil { return nil, nil }
\ttrack := &OutboundTrack{Caps: webrtc.RTPCodecCapability{
\t\tMimeType: webrtc.MimeTypeH264, ClockRate: 90000,
\t\tSDPFmtpLine: "level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f",
\t}}
\tencoder := &rtph264.Encoder{PayloadType: 96, PayloadMaxSize: webrtcPayloadMaxSize}
\tif err := encoder.Init(); err != nil { return nil, err }
\tfirstReceived := false; var lastPTS int64
\tr.OnData(media, h264Format, func(u *unit.Unit) error {
\t\tif u.NilPayload() { return nil }
\t\tif !firstReceived { firstReceived = true } else if u.PTS < lastPTS {
\t\t\treturn fmt.Errorf("WebRTC doesn\'t support H264 streams with B-frames")
\t\t}
\t\tlastPTS = u.PTS
\t\tpackets, err := encoder.Encode(u.Payload.(unit.PayloadH264))
\t\tif err != nil { return nil } //nolint:nilerr
\t\tfor _, pkt := range packets {
\t\t\tntp := u.NTP.Add(timestampToDuration(int64(pkt.Timestamp), 90000))
\t\t\tpkt.Timestamp += u.RTPPackets[0].Timestamp
\t\t\ttrack.WriteRTPWithNTP(pkt, ntp) //nolint:errcheck
\t\t}
\t\treturn nil
\t})
\treturn track, nil
}

func buildH265Track(media *description.Media, r *stream.Reader) (*OutboundTrack, error) {
\tvar h265Format *format.H265
\tfor _, f := range media.Formats {
\t\tif v, ok := f.(*format.H265); ok { h265Format = v; break }
\t}
\tif h265Format == nil { return nil, nil }
\ttrack := &OutboundTrack{Caps: webrtc.RTPCodecCapability{
\t\tMimeType: webrtc.MimeTypeH265, ClockRate: 90000,
\t\tSDPFmtpLine: "level-id=93;profile-id=1;tier-flag=0;tx-mode=SRST",
\t}}
\tencoder := &rtph265.Encoder{PayloadType: 96, PayloadMaxSize: webrtcPayloadMaxSize}
\tif err := encoder.Init(); err != nil { return nil, err }
\tfirstReceived := false; var lastPTS int64
\tr.OnData(media, h265Format, func(u *unit.Unit) error {
\t\tif u.NilPayload() { return nil }
\t\tif !firstReceived { firstReceived = true } else if u.PTS < lastPTS {
\t\t\treturn fmt.Errorf("WebRTC doesn\'t support H265 streams with B-frames")
\t\t}
\t\tlastPTS = u.PTS
\t\tpackets, err := encoder.Encode(u.Payload.(unit.PayloadH265))
\t\tif err != nil { return nil } //nolint:nilerr
\t\tfor _, pkt := range packets {
\t\t\tntp := u.NTP.Add(timestampToDuration(int64(pkt.Timestamp), 90000))
\t\t\tpkt.Timestamp += u.RTPPackets[0].Timestamp
\t\t\ttrack.WriteRTPWithNTP(pkt, ntp) //nolint:errcheck
\t\t}
\t\treturn nil
\t})
\treturn track, nil
}

func buildAV1Track(media *description.Media, r *stream.Reader) (*OutboundTrack, error) {
\tvar av1Format *format.AV1
\tfor _, f := range media.Formats {
\t\tif v, ok := f.(*format.AV1); ok { av1Format = v; break }
\t}
\tif av1Format == nil { return nil, nil }
\ttrack := &OutboundTrack{Caps: webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeAV1, ClockRate: 90000}}
\tencoder := &rtpav1.Encoder{PayloadType: 105, PayloadMaxSize: webrtcPayloadMaxSize}
\tif err := encoder.Init(); err != nil { return nil, err }
\tr.OnData(media, av1Format, func(u *unit.Unit) error {
\t\tif u.NilPayload() { return nil }
\t\tpackets, err := encoder.Encode(u.Payload.(unit.PayloadAV1))
\t\tif err != nil { return nil } //nolint:nilerr
\t\tfor _, pkt := range packets {
\t\t\tntp := u.NTP.Add(timestampToDuration(int64(pkt.Timestamp), 90000))
\t\t\tpkt.Timestamp += u.RTPPackets[0].Timestamp
\t\t\ttrack.WriteRTPWithNTP(pkt, ntp) //nolint:errcheck
\t\t}
\t\treturn nil
\t})
\treturn track, nil
}

func buildVP9Track(media *description.Media, r *stream.Reader) (*OutboundTrack, error) {
\tvar vp9Format *format.VP9
\tfor _, f := range media.Formats {
\t\tif v, ok := f.(*format.VP9); ok { vp9Format = v; break }
\t}
\tif vp9Format == nil { return nil, nil }
\ttrack := &OutboundTrack{Caps: webrtc.RTPCodecCapability{
\t\tMimeType: webrtc.MimeTypeVP9, ClockRate: 90000, SDPFmtpLine: "profile-id=0",
\t}}
\tencoder := &rtpvp9.Encoder{PayloadType: 96, PayloadMaxSize: webrtcPayloadMaxSize, InitialPictureID: ptrOf(uint16(8445))}
\tif err := encoder.Init(); err != nil { return nil, err }
\tr.OnData(media, vp9Format, func(u *unit.Unit) error {
\t\tif u.NilPayload() { return nil }
\t\tpackets, err := encoder.Encode(u.Payload.(unit.PayloadVP9))
\t\tif err != nil { return nil } //nolint:nilerr
\t\tfor _, pkt := range packets {
\t\t\tntp := u.NTP.Add(timestampToDuration(int64(pkt.Timestamp), 90000))
\t\t\tpkt.Timestamp += u.RTPPackets[0].Timestamp
\t\t\ttrack.WriteRTPWithNTP(pkt, ntp) //nolint:errcheck
\t\t}
\t\treturn nil
\t})
\treturn track, nil
}

// setupVideoTrack: original single-track behavior (fallback for non-simulcast)
func setupVideoTrack(
\tdesc *description.Session,
\tr *stream.Reader,
) (*OutboundTrack, error) {
'''

# ══════════════════════════════════════════════════════════════════════
# session.go — ?layer=N
# ══════════════════════════════════════════════════════════════════════
def patch_session():
    f = Path("internal/servers/webrtc/session.go")
    src = f.read_text()

    if "layer_select_patched" in src:
        print("  [session.go] bereits gepatcht"); return

    if '"strconv"' not in src:
        src = re.sub(r'(\bimport\s*\()', r'\1\n\t"strconv"', src, count=1)

    # Find FromStream call
    m = re.search(r'\berr\s*=\s*webrtc\.FromStream\(([^)]+)\)', src)
    if m:
        old_call = m.group(0)
        if 'layerIndex' not in old_call:
            new_code = (
                '// layer_select_patched\n'
                '\tlayerIndex := -1\n'
                '\tif lp := s.httpRequest.URL.Query().Get("layer"); lp != "" {\n'
                '\t\tif n, err2 := strconv.Atoi(lp); err2 == nil && n >= 0 {\n'
                '\t\t\tlayerIndex = n\n'
                '\t\t}\n'
                '\t}\n\t' + old_call.rstrip(')') + ', layerIndex)'
            )
            # Replace with proper indentation
            src = src[:m.start()] + new_code + src[m.end():]
            print("  [session.go] ?layer=N ✓")
    else:
        print("  [session.go] WARNUNG: FromStream-Aufruf nicht gefunden")

    f.write_text(src)
    print("  [session.go] Gespeichert ✓")

# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("  mediamtx Simulcast Patch (OutboundTrack/InboundTrack)")
    print("=" * 60)
    check_files()

    print("\n==> outbound_track.go")
    patch_outbound_track()
    print("\n==> inbound_track.go")
    patch_inbound_track()
    print("\n==> to_stream.go")
    patch_to_stream()
    print("\n==> from_stream.go")
    patch_from_stream()
    print("\n==> session.go")
    patch_session()

    print("\n==> Build-Check...")
    if go_build():
        print("  ✓ BUILD OK")
        print("\n  Nächste Schritte:")
        print("  cp read_index.html internal/servers/webrtc/")
        print("  go generate ./...")
        print("  go build -o mediamtx-simulcast ./")
    else:
        print("  ✗ BUILD FEHLGESCHLAGEN")
        sys.exit(1)

if __name__ == "__main__":
    main()
