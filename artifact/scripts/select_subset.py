# -*- coding: utf-8 -*-
"""Build the unified manifest from ReproFlake CSVs and select the FlakeAgent subset.

Inputs (in reference/): file_tc.txt (test_config.csv), file_jira.txt, file_idoft.txt, zenodo_*.json
Outputs (in artifact/data/): manifest_full.csv, subset.csv, downloads.txt
"""
import csv, sys, os, json, glob, collections, random

sys.stdout.reconfigure(encoding='utf-8')
REF = os.path.join(os.path.dirname(__file__), '..', '..', 'reference')
OUT = os.path.join(os.path.dirname(__file__), '..', 'data')
os.makedirs(OUT, exist_ok=True)
random.seed(20260927)

def load(fn, hdr):
    t = open(os.path.join(REF, fn), encoding='utf-8', errors='ignore').read()
    return list(csv.reader(t[t.find(hdr):].splitlines()))

# --- test_config.csv: test_type,result_container,zip,module,polluter,flaky_test,iterations,config,java,nondexSeed,url
tc = {(r[5], r[2]): r for r in load('file_tc.txt', 'test_type,')[1:] if len(r) >= 11}

def norm_test(t):
    """'a.b.C#m' and 'a.b.C.m' -> ('a.b.C','m')"""
    t = t.strip()
    if '#' in t:
        cls, meth = t.rsplit('#', 1)
    else:
        cls, meth = t.rsplit('.', 1)
    return cls, meth

# --- iDoFT: Type,Container,Project,TestName,FlakySHA,FixedSHA,Module,Polluter,Zip
idoft = {(norm_test(r[3]), r[8]): r for r in load('file_idoft.txt', 'Type,')[1:] if len(r) >= 9}
# --- JIRA: Type,Container,Project,FlakySHA,FixedSHA,Module,Test,Polluter,Zip
jira = {(norm_test(r[6]), r[8]): r for r in load('file_jira.txt', 'Type,')[1:] if len(r) >= 9}
# --- zenodo sizes/urls
sizes, urls = {}, {}
for f in glob.glob(os.path.join(REF, 'zenodo_*.json')):
    d = json.load(open(f, encoding='utf-8'))
    for x in d.get('files', []):
        if x['key'].endswith('.zip') and x.get('size', 0) < 2e9:
            sizes[x['key']] = x['size']
            urls[x['key']] = x['links']['self']

rows = []
for (test, zipname), r in tc.items():
    cat = r[0].lower()
    if cat == 'britle':
        cat = 'od'
    meta = idoft.get((norm_test(test), zipname)) or jira.get((norm_test(test), zipname)) or []
    fix_sha = meta[5] if len(meta) > 5 else ''
    flaky_sha = meta[4] if len(meta) > 4 else ''
    project = meta[2] if len(meta) > 2 else ''
    rows.append(dict(
        category=cat, test=test, zip=zipname, module=r[3], polluter=r[4],
        java=r[8], seed=r[9], iterations=r[6], config=r[7],
        project=project, flaky_sha=flaky_sha, fix_sha=fix_sha,
        zip_mb=sizes.get(zipname + '.zip', 0) / 1e6, url=urls.get(zipname + '.zip', ''),
    ))

# sanity: category counts must match paper (id 819, od 126, nio 125, td 36, unc 9)
cc = collections.Counter(r['category'] for r in rows)
print('total:', len(rows), 'cats:', dict(cc))
assert len(rows) == 1115

# --- subset selection ---
def pick(cat, n, max_per_zip=10 ** 9, zip_budget=10 ** 9, prefer_java=None):
    """Greedy: prefer zips holding many tests (download efficiency), cap per-zip, respect zip budget."""
    pool = [r for r in rows if r['category'] == cat]
    if prefer_java:
        pool.sort(key=lambda r: 0 if r['java'] in prefer_java else 1)
    by_zip = collections.defaultdict(list)
    for r in pool:
        by_zip[r['zip']].append(r)
    zips_sorted = sorted(by_zip, key=lambda z: (-len(by_zip[z]), by_zip[z][0]['zip_mb']))
    sel, nzips = [], 0
    for z in zips_sorted:
        if len(sel) >= n or nzips >= zip_budget:
            break
        take = min(len(by_zip[z]), max_per_zip, n - len(sel))
        sel.extend(by_zip[z][:take])
        nzips += 1
    random.shuffle(sel)
    return sel[:n]

od = pick('od', 30, max_per_zip=10, zip_budget=7)
td = pick('td', 36)          # complete TD coverage
nio = pick('nio', 25, max_per_zip=7, zip_budget=6)
idd = pick('id', 25, max_per_zip=3, zip_budget=11, prefer_java={'8', '11'})
subset = od + td + nio + idd

print('subset:', len(subset), 'tests,', collections.Counter(r['category'] for r in subset))
print('java:', dict(collections.Counter(r['java'] for r in subset)))
print('zips:', len(set(r['zip'] for r in subset)), 'total download %.1f GB' % (sum(r['zip_mb'] for r in subset) / 1024))
print('fix_sha present:', sum(1 for r in subset if r['fix_sha']))

with open(os.path.join(OUT, 'manifest_full.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)
with open(os.path.join(OUT, 'subset.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(subset[0].keys()))
    w.writeheader(); w.writerows(subset)
with open(os.path.join(OUT, 'downloads.txt'), 'w', encoding='utf-8') as f:
    seen = set()
    for r in subset:
        if r['url'] and r['url'] not in seen:
            seen.add(r['url'])
            f.write(r['url'] + '  out=' + r['zip'] + '.zip\n')

# per-zip test list for executor mapping
per_zip = collections.defaultdict(list)
for r in subset:
    per_zip[r['zip']].append(r)
print('\nper-zip:')
for z, rs in sorted(per_zip.items()):
    print(f'  {z}: {len(rs)} tests, {rs[0]["zip_mb"]:.0f}MB, java {rs[0]["java"]}')
