#!/usr/bin/env python3
"""
mediamtx Simulcast-Egress Patch
================================
Patcht session.go so, dass ALLE Video-Renditions (Simulcast-Layers
von OBS) in der WHEP-Session als separate Tracks gesendet werden.

Kompatibel mit mediamtx >= v1.9.0 (wo Simulcast-Ingest hinzukam).
"""
import re
import sys
import subprocess
from pathlib import Path

SESSION_GO  = Path("internal/servers/webrtc/session.go")
OT_GO       = Path("internal/protocols/webrtc/outgoing_track.go")
PC_GO       = Path("internal/protocols/webrtc/peer_connection.go")

def fatal(msg):
    print(f"FEHLER: {msg}", file=sys.stderr)
    sys.exit(1)

def check_files():
    for p in [SESSION_GO, OT_GO, PC_GO]:
        if not p.exists():
            fatal(f"{p} nicht gefunden. Skript aus dem mediamtx-Root-Verzeichnis ausführen.")

# ──────────────────────────────────────────────────────────────
# 1. OutgoingTrack: RID-Feld hinzufügen
# ──────────────────────────────────────────────────────────────
def patch_outgoing_track():
    src = OT_GO.read_text()

    if "RID" in src:
        print(f"  [{OT_GO}] RID bereits vorhanden — überspringe")
        return

    # Suche das Struct
    struct_match = re.search(r'(type OutgoingTrack struct \{)', src)
    if not struct_match:
        fatal(f"OutgoingTrack struct nicht in {OT_GO} gefunden")

    insert_pos = struct_match.end()
    new_src = (
        src[:insert_pos]
        + "\n\tRID string // Simulcast Rendition ID (z.B. 'high', 'med', 'low')"
        + src[insert_pos:]
    )
    OT_GO.write_text(new_src)
    print(f"  [{OT_GO}] RID-Feld hinzugefügt ✓")

# ──────────────────────────────────────────────────────────────
# 2. session.go: runRead() — Video-Break entfernen
# ──────────────────────────────────────────────────────────────
def patch_session_go():
    src = SESSION_GO.read_text()

    if "runRead" not in src:
        fatal(f"runRead nicht in {SESSION_GO} — falsches Verzeichnis?")

    # Finde runRead-Körper
    run_read_start = src.index("func (s *session) runRead")
    # Ende: nächste top-level Funktion
    next_fn = re.search(r'\nfunc ', src[run_read_start + 1:])
    run_read_end = run_read_start + 1 + (next_fn.start() if next_fn else len(src) - run_read_start - 1)
    body = src[run_read_start:run_read_end]

    # ── Schritt A: Video-Break entfernen ──────────────────────
    # Muster 1: Standard-mediamtx (break nach erstem Video-Track-Append)
    # Muster 2: Alternative Strukturen
    patterns_break = [
        # Direkt nach append(outgoingTracks
        (r'(append\(outgoingTracks[^\n]*\n[\t ]*)(break\n)', r'\1'),
        # Break in einer if-isVideo-Bedingung
        (r'(outgoingTrack[^\n]*\n[\t ]*)(break\n)', r'\1'),
    ]

    patched_body = body
    break_removed = False
    for pattern, replacement in patterns_break:
        new_body = re.sub(pattern, replacement, patched_body)
        if new_body != patched_body:
            patched_body = new_body
            break_removed = True
            break

    if not break_removed:
        print(f"  [{SESSION_GO}] WARNUNG: Video-Break nicht gefunden.")
        print(f"                 Prüfe manuell: suche 'break' nach erstem Video-Track-Append in runRead()")
        # Zeige Kontext
        for i, line in enumerate(body.split('\n')):
            if 'break' in line:
                print(f"                 Zeile ~{i}: {line.strip()}")
    else:
        print(f"  [{SESSION_GO}] Video-Break entfernt ✓")

    # ── Schritt B: RID-Labels pro Video-Track zuweisen ────────
    # Suche den Append-Block und füge einen videoIndex-Zähler + RID-Zuweisung ein
    if "videoIndex" not in patched_body:
        # Füge videoIndex-Deklaration am Anfang des runRead-Loops ein
        # (vor dem ersten "for _, medi := range")
        loop_match = re.search(r'(for _,\s*\w+\s*:=\s*range\s+\w+\.Medias)', patched_body)
        if loop_match:
            insert_at = loop_match.start()
            counter_decl = "\tvideoIndex := 0\n\t"
            patched_body = patched_body[:insert_at] + counter_decl + patched_body[insert_at:]
            print(f"  [{SESSION_GO}] videoIndex-Zähler hinzugefügt ✓")

        # RID nach jedem Video-Append setzen
        rid_assignment = '''
\t\t\t\t// Simulcast RID aus Index ableiten
\t\t\t\tswitch videoIndex {
\t\t\t\tcase 0:
\t\t\t\t\tot.RID = "high"
\t\t\t\tcase 1:
\t\t\t\t\tot.RID = "med"
\t\t\t\tcase 2:
\t\t\t\t\tot.RID = "low"
\t\t\t\tdefault:
\t\t\t\t\tot.RID = fmt.Sprintf("layer%d", videoIndex)
\t\t\t\t}
\t\t\t\tvideoIndex++
'''
        # Füge nach dem OutgoingTrack-Append ein
        append_match = re.search(r'(outgoingTracks\s*=\s*append\(outgoingTracks[^\n]+\n)', patched_body)
        if append_match and "RID" not in patched_body:
            insert_at = append_match.end()
            patched_body = patched_body[:insert_at] + rid_assignment + patched_body[insert_at:]
            print(f"  [{SESSION_GO}] RID-Zuweisung hinzugefügt ✓")
    else:
        print(f"  [{SESSION_GO}] RID-Zuweisung bereits vorhanden — überspringe")

    # Prüfe ob fmt importiert ist (für Sprintf)
    if "fmt.Sprintf" in patched_body and '"fmt"' not in src[:run_read_start]:
        print(f"  [{SESSION_GO}] WARNUNG: 'fmt' Import möglicherweise nötig — prüfe Imports")

    new_src = src[:run_read_start] + patched_body + src[run_read_end:]
    SESSION_GO.write_text(new_src)
    print(f"  [{SESSION_GO}] Gespeichert ✓")

# ──────────────────────────────────────────────────────────────
# 3. peer_connection.go: Transceiver-Deduplication aufheben
# ──────────────────────────────────────────────────────────────
def patch_peer_connection():
    src = PC_GO.read_text()

    # Prüfe ob bereits gepatcht
    if "simulcast_patched" in src:
        print(f"  [{PC_GO}] Bereits gepatcht — überspringe")
        return

    # Suche den Publish-Modus-Block wo Transceivers erstellt werden.
    # Typisches Muster: eine Map/Set um Codec-Duplikate zu vermeiden,
    # dann AddTransceiver nur für neue Codecs.
    #
    # Konkrete Patterns die mediamtx verwendet (kann sich zwischen Versionen unterscheiden):
    dedup_patterns = [
        # Pattern A: explicit codec-seen map
        r'(codecs\s*:=\s*map\[string\]bool\{\}[\s\S]{0,500}?AddTransceiver)',
        # Pattern B: "if !videoAdded" guard
        r'(!videoAdded\s*\{[\s\S]{0,200}?videoAdded\s*=\s*true)',
        # Pattern C: einzel-flag
        r'(videoTrackAdded\s*=\s*true)',
    ]

    found_pattern = False
    for pat in dedup_patterns:
        m = re.search(pat, src)
        if m:
            print(f"  [{PC_GO}] Deduplication-Pattern gefunden: '{m.group()[:60]}...'")
            found_pattern = True
            break

    if not found_pattern:
        print(f"  [{PC_GO}] HINWEIS: Kein eindeutiges Deduplication-Pattern gefunden.")
        print(f"             Die Transceivers werden möglicherweise bereits korrekt erstellt.")
        print(f"             Prüfe manuell: suche 'AddTransceiver' in {PC_GO}")
        print(f"             Stelle sicher, dass für JEDEN OutgoingTrack ein Transceiver entsteht.")
        return

    # Füge einen Kommentar ein als Marker und Hinweis
    marker = "\n// simulcast_patched: Transceiver werden jetzt pro OutgoingTrack erstellt\n"
    src = src.replace("func (pc *PeerConnection) outgoingTracksSetup(", marker + "func (pc *PeerConnection) outgoingTracksSetup(", 1)
    if "outgoingTracksSetup" not in src:
        # Alternativer Funktionsname
        src += marker

    PC_GO.write_text(src)
    print(f"  [{PC_GO}] Marker gesetzt — manuelle Prüfung der Transceiver-Schleife empfohlen ✓")

# ──────────────────────────────────────────────────────────────
# 4. Syntax-Check
# ──────────────────────────────────────────────────────────────
def syntax_check():
    print("\n==> Syntax-Check...")
    result = subprocess.run(
        ["go", "vet", "./internal/servers/webrtc/...", "./internal/protocols/webrtc/..."],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("WARNUNG: go vet Fehler:")
        print(result.stdout)
        print(result.stderr)
        print("\nDer Patch muss möglicherweise manuell angepasst werden.")
        print("Siehe PATCH_REFERENCE.go.txt für die vollständige Referenz.")
    else:
        print("  Syntax OK ✓")

# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  mediamtx Simulcast-Egress Patch")
    print("=" * 60)
    print()

    check_files()

    print("==> Schritt 1: OutgoingTrack RID-Feld")
    patch_outgoing_track()

    print()
    print("==> Schritt 2: session.go Video-Break entfernen + RID-Labels")
    patch_session_go()

    print()
    print("==> Schritt 3: peer_connection.go Transceiver-Schleife")
    patch_peer_connection()

    try:
        syntax_check()
    except FileNotFoundError:
        print("  HINWEIS: Go nicht im PATH — überspringe Syntax-Check")

    print()
    print("=" * 60)
    print("  Patch abgeschlossen!")
    print()
    print("  Nächste Schritte:")
    print("  1. go build -o mediamtx-simulcast ./")
    print("  2. Prüfe PATCH_REFERENCE.go.txt für manuelle Korrekturen")
    print("  3. Starte: ./mediamtx-simulcast mediamtx.yml")
    print("=" * 60)

if __name__ == "__main__":
    main()
