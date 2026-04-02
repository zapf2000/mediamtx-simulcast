#!/usr/bin/env python3
"""
mediamtx WHEP Layer Selection Patch
=====================================
Adds ?layer=N query parameter support to the WHEP endpoint.
When ?layer=0 is specified, only the Nth video track is sent.

Run from the mediamtx repo root:
  python3 patch_layer_select.py
"""
import re, sys, subprocess
from pathlib import Path

SESSION_GO   = Path("internal/servers/webrtc/session.go")
FROM_STREAM  = Path("internal/protocols/webrtc/from_stream.go")

def fatal(msg):
    print(f"FEHLER: {msg}", file=sys.stderr)
    sys.exit(1)

for p in [SESSION_GO, FROM_STREAM]:
    if not p.exists():
        fatal(f"{p} not found — run from mediamtx repo root")

# ──────────────────────────────────────────────────────────────────────
# PATCH 1 — from_stream.go
# Add a layerIndex parameter to FromStream() so the caller can request
# a specific video track index. -1 = all tracks (ABR mode).
# ──────────────────────────────────────────────────────────────────────
src = FROM_STREAM.read_text()

if "layer_select_patched" in src:
    print(f"[{FROM_STREAM}] already patched — skipping")
else:
    # Find FromStream function signature and add layerIndex parameter
    old_sig = '''// FromStream maps a MediaMTX stream to a WebRTC connection
func FromStream(
\tdesc *description.Session,
\tr *stream.Reader,
\tpc *PeerConnection,
) error {'''

    new_sig = '''// FromStream maps a MediaMTX stream to a WebRTC connection.
// layerIndex: -1 = all video tracks (ABR), 0/1/2/... = specific track only.
// layer_select_patched
func FromStream(
\tdesc *description.Session,
\tr *stream.Reader,
\tpc *PeerConnection,
\tlayerIndex int,
) error {'''

    if old_sig not in src:
        # Try without comment
        old_sig2 = '''func FromStream(
\tdesc *description.Session,
\tr *stream.Reader,
\tpc *PeerConnection,
) error {'''
        if old_sig2 not in src:
            fatal(f"FromStream signature not found in {FROM_STREAM}")
        old_sig = old_sig2
        new_sig = new_sig  # keep new_sig with comment

    src = src.replace(old_sig, new_sig)

    # Now patch the setupVideoTracks call to pass layerIndex
    old_call = '''\tvideoTracks, err := setupVideoTracks(desc, r)
\tif err != nil {
\t\treturn err
\t}
\tpc.OutgoingTracks = append(pc.OutgoingTracks, videoTracks...)'''

    new_call = '''\tvideoTracks, err := setupVideoTracks(desc, r)
\tif err != nil {
\t\treturn err
\t}
\t// Layer selection: if layerIndex >= 0, only include that specific track
\tif layerIndex >= 0 && layerIndex < len(videoTracks) {
\t\tpc.OutgoingTracks = append(pc.OutgoingTracks, videoTracks[layerIndex])
\t} else {
\t\tpc.OutgoingTracks = append(pc.OutgoingTracks, videoTracks...)
\t}'''

    if old_call not in src:
        fatal(f"setupVideoTracks call pattern not found in {FROM_STREAM}")

    src = src.replace(old_call, new_call)
    FROM_STREAM.write_text(src)
    print(f"[{FROM_STREAM}] layerIndex parameter added ✓")

# ──────────────────────────────────────────────────────────────────────
# PATCH 2 — session.go
# Read ?layer=N from the WHEP query string and pass it to FromStream().
# ──────────────────────────────────────────────────────────────────────
src = SESSION_GO.read_text()

if "layer_select_patched" in src:
    print(f"[{SESSION_GO}] already patched — skipping")
else:
    # Find the FromStream call in runRead and add layer parsing before it
    # Typical pattern: res.Path.Stream or similar + FromStream(...)
    from_stream_call = re.search(
        r'(err\s*(?::?=)\s*webrtc\.FromStream\((?:[^)]+)\))',
        src
    )
    if not from_stream_call:
        # Try alternate pattern
        from_stream_call = re.search(
            r'(FromStream\(\s*\w+\.Description\(\),\s*\w+,\s*\w+\))',
            src
        )

    if not from_stream_call:
        print(f"WARNING: FromStream call not found in {SESSION_GO}")
        print("         Manual edit needed — see instructions below")
        print("""
  In session.go, find the line that calls webrtc.FromStream() and change:

    err = webrtc.FromStream(desc, reader, pc)

  to:

    layerIndex := -1
    if layerParam := s.query.Get("layer"); layerParam != "" {
        if n, err2 := strconv.Atoi(layerParam); err2 == nil && n >= 0 {
            layerIndex = n
        }
    }
    err = webrtc.FromStream(desc, reader, pc, layerIndex)

  Also add "strconv" to the imports if not already present.
""")
    else:
        old_call = from_stream_call.group(0)
        # Determine the variable names used
        args = re.search(r'FromStream\((\w+)(?:\.Description\(\))?,\s*(\w+),\s*(\w+)\)', old_call)

        if args:
            desc_arg   = args.group(1)
            reader_arg = args.group(2)
            pc_arg     = args.group(3)

            new_code = f'''// layer_select_patched
\t\tlayerIndex := -1
\t\tif lp := s.req.URL.Query().Get("layer"); lp != "" {{
\t\t\tif n, err2 := strconv.Atoi(lp); err2 == nil && n >= 0 {{
\t\t\t\tlayerIndex = n
\t\t\t}}
\t\t}}
\t\t{old_call.strip().replace(f'{pc_arg})', f'{pc_arg}, layerIndex)')}'''

            src = src.replace('\t\t' + old_call.strip(), new_code, 1)
            # Also try without double-tab
            src = src.replace('\t' + old_call.strip(),
                new_code.replace('\t\t', '\t'), 1)

        # Make sure strconv is imported
        if '"strconv"' not in src:
            src = src.replace(
                '"strings"',
                '"strconv"\n\t"strings"',
                1
            )
            if '"strconv"' not in src:
                # Add to imports block
                src = re.sub(
                    r'(import \()',
                    r'\1\n\t"strconv"',
                    src, count=1
                )

        SESSION_GO.write_text(src)
        print(f"[{SESSION_GO}] layer query parameter parsing added ✓")

# ── Syntax check ──────────────────────────────────────────────────────
print("\n==> Syntax check...")
result = subprocess.run(
    ["go", "build", "./..."],
    capture_output=True, text=True
)
if result.returncode != 0:
    print("Build errors — manual review needed:")
    print(result.stdout)
    print(result.stderr)
    print("""
Common issue: FromStream() is also called from other places (e.g. whip client).
Find all calls to webrtc.FromStream() and add the layerIndex parameter:

  grep -rn "webrtc.FromStream\\|FromStream(" internal/ | grep -v "_test.go"

Each call needs the extra parameter:
  webrtc.FromStream(desc, reader, pc, -1)   // -1 = all tracks
""")
else:
    print("✓ Build OK")
    print("""
Patch applied! Rebuild:
  go build -o mediamtx-simulcast ./

WHEP URL with layer selection:
  http://server:8889/stream/whep?layer=0   ← highest quality only
  http://server:8889/stream/whep?layer=1   ← medium quality only
  http://server:8889/stream/whep?layer=2   ← lowest quality only
  http://server:8889/stream/whep           ← all tracks (ABR)
""")
