#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostic : franchit le défi JS et montre quel export renvoie du RDF.
Lance :  python diag.py    puis colle-moi la sortie."""

import re
import requests

ID = "2679af120dcec5557878b634c3701f842b1d806e"   # IR Plans du cadastre (SSD)
BASE = "https://francearchives.gouv.fr"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
REDIRECT_RE = re.compile(r"window\.location\.href='(/redirect_[^']+)'")

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "application/rdf+xml, */*"})

candidates = [
    f"{BASE}/findingaid/{ID}.rdf",
    f"{BASE}/findingaid/{ID}/rdf.xml",
    f"{BASE}/findingaid/{ID}.csv",
    f"{BASE}/findingaid/{ID}",
]

for url in candidates:
    try:
        r = s.get(url, timeout=30)
        head = r.text[:600]
        m = REDIRECT_RE.search(head)
        if m:
            r = s.get(BASE + m.group(1), timeout=30)   # suit le défi (pose cookie)
        is_rdf = "rdf:RDF" in r.text[:4000]
        print(f"\n=== {url}")
        print(f"    status={r.status_code}  type={r.headers.get('content-type','?')}  "
              f"len={len(r.text)}  RDF={is_rdf}  final={r.url}")
        print(f"    début: {r.text[:160]!r}")
    except Exception as e:
        print(f"\n=== {url}\n    ERREUR: {e}")
