#!/usr/bin/env python3
"""
Sonde les endpoints ARK/IIIF de l'AD21 pour un image_id connu.
image_id 791649749 = TA Agencourt
item_id  791649731 = notice EAD correspondante
"""
import requests, urllib3
urllib3.disable_warnings()

s = requests.Session()
s.verify = False
s.headers["User-Agent"] = "Mozilla/5.0"

BASE   = "https://archives.cotedor.fr"
IR     = "23318"
IMG_ID = "791649749"
ITEM_ID= "791649731"

probes = [
    # Permalien AJAX avec image_id
    f"{BASE}/v2/ad21/permalien_ajax.html?id={IMG_ID}",
    f"{BASE}/v2/ad21/permalien_ajax.html?id={IMG_ID}&ir={IR}",
    # Idem avec item_id (notice EAD)
    f"{BASE}/v2/ad21/permalien_ajax.html?id={ITEM_ID}",
    # IIIF manifest via IR + image_id (pattern Ligeo)
    f"{BASE}/v2/iiif/{IR}/{IMG_ID}/manifest",
    f"{BASE}/v2/iiif/manifest/{IMG_ID}",
    # genereImage (vu dans les HAR)
    f"{BASE}/v2/ad21/visualiseur/genereImage.html?ir={IR}&id={IMG_ID}",
]

# On initialise d'abord la session
s.get(f"{BASE}/console/ir_ead_visu.php?eadid=FRAD021_000000905&ir={IR}", timeout=15)

for url in probes:
    try:
        r = s.get(url, timeout=10)
        snippet = r.text[:300].replace("\n", " ")
        print(f"{r.status_code}  {url}")
        if r.status_code == 200 and r.text.strip():
            print(f"     => {snippet}")
    except Exception as e:
        print(f"ERR  {url}  ({e})")
