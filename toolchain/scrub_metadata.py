#!/usr/bin/env python3
"""Scrub a bloated/derived IDML XMP packet down to a clean template packet.

Removes the descriptive metadata InDesign regenerates on save (edit history,
placed-file ingredients/manifest, page-preview thumbnails, derived-from lineage)
and resets the document identity to a fresh UUID lineage so manuals built from
the template are NOT fingerprinted as the source document.

Keeps the exact XMP wrapper / namespaces / dates / font list InDesign wrote.

Usage: python3 scrub_metadata.py [path-to-metadata.xml]
       (default: template_build/META-INF/metadata.xml)
"""
import os, re, sys, uuid
import xml.etree.ElementTree as ET

P = sys.argv[1] if len(sys.argv) > 1 else "template_build/META-INF/metadata.xml"
before = os.path.getsize(P)
t = open(P, encoding="utf-8").read()

# --- remove descriptive-bloat blocks (paired or self-closing, incl. indent) ---
KILL = ["xmpMM:History", "xmpMM:Ingredients", "xmpMM:Manifest",
        "xmpMM:DerivedFrom", "xmpMM:Pantry", "xmp:PageInfo"]
for q in KILL:
    t = re.sub(r'[ \t]*<' + q + r'(?:\s[^>]*)?>.*?</' + q + r'>\r?\n?', '', t, flags=re.S)
    t = re.sub(r'[ \t]*<' + q + r'(?:\s[^>]*)?/>\r?\n?', '', t, flags=re.S)

# --- reset identity to a fresh, self-originating lineage ----------------------
new_did = "xmp.did:" + str(uuid.uuid4())
new_iid = "xmp.iid:" + str(uuid.uuid4())
t = re.sub(r'<xmpMM:DocumentID>[^<]*</xmpMM:DocumentID>',
           f'<xmpMM:DocumentID>{new_did}</xmpMM:DocumentID>', t)
t = re.sub(r'<xmpMM:OriginalDocumentID>[^<]*</xmpMM:OriginalDocumentID>',
           f'<xmpMM:OriginalDocumentID>{new_did}</xmpMM:OriginalDocumentID>', t)
t = re.sub(r'<xmpMM:InstanceID>[^<]*</xmpMM:InstanceID>',
           f'<xmpMM:InstanceID>{new_iid}</xmpMM:InstanceID>', t)

open(P, "w", encoding="utf-8").write(t)

# --- verify the packet is still well-formed XML (strip xpacket PIs first) -----
core = re.sub(r'<\?xpacket.*?\?>', '', t, flags=re.S)
ET.fromstring(core)   # raises if malformed

after = os.path.getsize(P)
print(f"metadata.xml: {before:,} -> {after:,} bytes  (removed {before-after:,})")
print("removed blocks :", ", ".join(KILL))
print("new DocumentID :", new_did)
print("new InstanceID :", new_iid)
print("XMP well-formed: OK")
