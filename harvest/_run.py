#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lanceur du harvester avec TLS robuste.

Essaie d'abord **truststore** (utilise le magasin de certificats de l'OS — règle
les CERTIFICATE_VERIFY_FAILED derrière proxy/CA d'entreprise). À défaut, repli sur
`verify=False`. Arguments identiques au harvester :

    python _run.py <eid> [findingaid|facomponent] --out seed_xx.sql [...]
"""
import sys
import warnings
import urllib3

warnings.simplefilter("ignore")
urllib3.disable_warnings()

try:
    import truststore
    truststore.inject_into_ssl()
    sys.stderr.write("TLS via truststore (magasin OS).\n")
    _tls = "truststore"
except Exception:
    _tls = None

import harvest_francearchives as H

if _tls is None:
    H.session.verify = False
    sys.stderr.write("⚠ truststore indispo → TLS non vérifié (repli).\n")

H.main()
