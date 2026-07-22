#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Charge un fichier seed SQL (INSERT INTO document ...) dans Supabase via
PostgREST, en batches. Nécessite harvest/.env (SUPABASE_URL + service_role).

Parse chaque ligne `insert into document (col1, col2, ...) values (v1, v2, ...);`
en dict, POST vers /rest/v1/document par lots. Header
`Prefer: resolution=ignore-duplicates` : tolère les collisions si la contrainte
UNIQUE(archive_url) est déjà en place.

Usage : python harvest/load_seed_to_supabase.py harvest/seed_doubs.sql
"""
import sys, os, re, json, urllib.request, urllib.parse, urllib.error

try:                       # console Windows en cp1252 : « → » plantait le résumé
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BATCH = 500

def load_env():
    env = {}
    with open(os.path.join(os.path.dirname(__file__), '.env'), encoding='utf-8') as f:
        for l in f:
            l = l.strip()
            if '=' in l and not l.startswith('#'):
                k, v = l.split('=', 1); env[k] = v
    return env

def parse_seed(path):
    """Retourne (colonnes, [ligne_de_valeurs_dict, ...])"""
    txt = open(path, encoding='utf-8').read()
    stmts = re.findall(
        r"insert\s+into\s+document\s*\(([^)]+)\)\s*values\s*(\(.*?\))\s*;",
        txt, re.I | re.S)
    if not stmts:
        raise SystemExit(f"aucun INSERT trouvé dans {path}")
    cols = [c.strip() for c in stmts[0][0].split(',')]
    rows = []
    for _, vals in stmts:
        rows.append(parse_values(vals, cols))
    return cols, rows

def parse_values(s, cols):
    """Parse '(v1, v2, ...)' → dict {col: python_value}. Gère quotes SQL '' et NULL.

    On mémorise si la valeur était QUOTÉE dans le SQL : sans ça, '01195' était
    converti en entier 1195 et l'INSEE de l'Ain perdait son zéro initial —
    9 173 notices atterries dans des départements 10 à 14 inexistants.
    Seules les valeurs non quotées peuvent devenir des nombres.
    """
    s = s.strip()
    assert s.startswith('(') and s.endswith(')')
    s = s[1:-1]
    out, i, buf, in_str, quoted = [], 0, '', False, False
    while i < len(s):
        c = s[i]
        if in_str:
            if c == "'":
                if i+1 < len(s) and s[i+1] == "'":   # escape ''
                    buf += "'"; i += 2; continue
                in_str = False; i += 1; continue
            buf += c; i += 1
        else:
            if c == "'":
                in_str = True; quoted = True; i += 1
            elif c == ',':
                out.append((buf.strip(), quoted)); buf, quoted = '', False; i += 1
            else:
                buf += c; i += 1
    out.append((buf.strip(), quoted))
    if len(out) != len(cols):
        raise ValueError(f"{len(out)} valeurs pour {len(cols)} colonnes")
    d = {}
    for k, (v, was_quoted) in zip(cols, out):
        vs = v.strip()
        if was_quoted:
            d[k] = v                       # texte SQL : jamais converti
        elif vs.lower() == 'null':
            d[k] = None
        elif vs.lower() in ('true', 'false'):
            d[k] = (vs.lower() == 'true')
        elif vs.lstrip('-').isdigit():
            d[k] = int(vs)
        else:
            d[k] = v
    return d

def post_batch(env, batch):
    # `on_conflict` est indispensable : sans lui, `resolution=ignore-duplicates`
    # ne vise que la clé primaire et une collision sur archive_url remonte en 409.
    url = f"{env['SUPABASE_URL']}/rest/v1/document?on_conflict=archive_url"
    data = json.dumps(batch, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'apikey': env['SUPABASE_SERVICE_ROLE_KEY'],
        'Authorization': 'Bearer ' + env['SUPABASE_SERVICE_ROLE_KEY'],
        'Content-Type': 'application/json',
        'Prefer': 'resolution=ignore-duplicates,return=minimal',
    })
    try:
        r = urllib.request.urlopen(req, timeout=180)
        return r.status, ''
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')[:400]

def main():
    if len(sys.argv) < 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <seed.sql> [<seed.sql> ...]")
    env = load_env()
    for path in sys.argv[1:]:
        print(f"\n=== {path} ===")
        cols, rows = parse_seed(path)
        print(f"colonnes: {cols}")
        print(f"lignes  : {len(rows)}")
        ok = err = 0
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i+BATCH]
            code, msg = post_batch(env, batch)
            if code < 300:
                ok += len(batch)
                print(f"  batch {i//BATCH+1:>3} : HTTP {code} · +{len(batch)} · cumul {ok}")
            else:
                err += len(batch)
                print(f"  batch {i//BATCH+1:>3} : HTTP {code} · ERR {msg}")
                if err > 100: raise SystemExit("trop d'erreurs, arrêt")
        print(f"→ {path}: {ok} chargés, {err} erreurs")

if __name__ == '__main__':
    main()
