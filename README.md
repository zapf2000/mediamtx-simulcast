$(cat /mnt/user-data/outputs/README.md)

## Known Issues / Troubleshooting

**Stack overflow crash when a WebRTC client connects while a non-simulcast stream is active (e.g. MoQ)**

Cause: `setupVideoTracks` calls `setupVideoTrack` as a fallback for single-track streams. If `setupVideoTrack` is accidentally replaced with a stub that calls `setupVideoTracks` again, this creates infinite recursion.

Fix: `setupVideoTrack` (without `s`) must contain the original first-match logic (AV1 → VP9 → VP8 → H265 → H264). It must **not** call `setupVideoTracks`. This is correctly implemented in the patched files in this repo.

**OBS Linux: "No connection to server"**

Make sure the `Accept-Patch` header is removed from the WHIP 201 response (already done in the patched `http_server.go`). Also verify `pion/dtls v3.1.4` is used — v3.1.3 was retracted due to broken DTLS interoperability with libdatachannel.

**Browser player stuck at "Connecting"**

Check browser console for JavaScript errors. The player requires template literal support (all modern browsers). Make sure `read_index.html` is the patched version from this repo (40+ KB), not the original mediamtx version (~4 KB).
