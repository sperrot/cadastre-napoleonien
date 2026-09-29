#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnostic de la chaîne JPEG Jura → worker → Allmaps, maillon par maillon.

    python harvest/diag_jura_iiif.py [URL_JPEG]

Défaut : la planche de référence (Abergement-la-Ronce, TA). Lit seulement les
premiers octets de chaque réponse : dit si l'on reçoit bien un JPEG, et sinon
quoi (page HTML, captcha, erreur du worker).
"""
import sys
import urllib.parse

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WORKER = "https://iiif-allmaps.sperrot.workers.dev"
JPG = (sys.argv[1] if len(sys.argv) > 1 else
       "https://archives39.fr/ark:/36595/7kbm3w2qnglr/09015152-973c-47cf-8c36-995ca8c72371")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}


def probe(label, url, cookies=None, headers=None, show_text=False):
    try:
        r = requests.get(url, headers={**UA, **(headers or {})}, cookies=cookies,
                         timeout=90, stream=True, allow_redirects=True)
        head = r.raw.read(400, decode_content=True)
        r.close()
    except Exception as e:
        print(f"\n[{label}] ✖ {e}")
        return
    kind = ("JPEG" if head[:3] == b"\xff\xd8\xff" else
            "PNG" if head[:4] == b"\x89PNG" else
            "JSON" if head.lstrip()[:1] in (b"{", b"[") else
            "HTML" if b"<" in head[:50] else "autre")
    print(f"\n[{label}] HTTP {r.status_code} · {kind} · "
          f"type={r.headers.get('content-type')} · taille={r.headers.get('content-length')}")
    if r.history:
        print("  redirections : " + " → ".join(h.headers.get("location", "?") for h in r.history))
    for h in ("content-disposition", "access-control-allow-origin", "accept-ranges"):
        if r.headers.get(h):
            print(f"  {h}: {r.headers[h]}")
    if kind != "JPEG" or show_text:
        print("  début : " + head[:300].decode("utf-8", "replace").replace("\n", " "))


enc = urllib.parse.quote(JPG, safe="")
print(f"JPEG testé : {JPG}")
probe("1. source, sans cookie", JPG)
probe("2. source, cookie license=true (= ce qu'envoie le worker)", JPG,
      cookies={"license": "true"})
probe("3. source, Range 0-65535 + cookie", JPG, cookies={"license": "true"},
      headers={"Range": "bytes=0-65535"})
probe("4. worker /static-manifest", f"{WORKER}/static-manifest?u={enc}", show_text=True)
probe("5. worker info.json", f"{WORKER}/static-iiif/{enc}/info.json", show_text=True)
probe("6. worker image (ce que demande la vignette Allmaps)",
      f"{WORKER}/static-iiif/{enc}/full/!400,400/0/default.jpg")
