#!/usr/bin/env python3
"""Repack an extracted IDML folder into a valid .idml file.

IDML is an OCF container: the `mimetype` file must be the FIRST entry and
stored uncompressed. Everything else is deflated.

Usage: python3 repack.py [src_dir] [out_file]
"""
import os, sys, zipfile

src = sys.argv[1] if len(sys.argv) > 1 else "extracted"
out = sys.argv[2] if len(sys.argv) > 2 else "dm32_print_manual_v1.76_repacked.idml"

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    # 1. mimetype first, STORED (no compression)
    z.write(os.path.join(src, "mimetype"), "mimetype", compress_type=zipfile.ZIP_STORED)
    # 2. everything else, deflated, with stable (sorted) ordering
    for root, _, files in os.walk(src):
        for name in sorted(files):
            full = os.path.join(root, name)
            arc = os.path.relpath(full, src).replace(os.sep, "/")
            if arc == "mimetype":
                continue
            z.write(full, arc)

print(f"Wrote {out} ({os.path.getsize(out):,} bytes)")
