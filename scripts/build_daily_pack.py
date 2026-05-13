#!/usr/bin/env python3
"""Build Clipping Club dated daily packs without reusing clippings.

Usage:
  python3 scripts/build_daily_pack.py --date 2026-05-14 --target 15 --collect-if-needed
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, random, re, subprocess, sys, time, urllib.parse, urllib.request, io, signal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUT_DIR = ROOT / "assets" / "cutout-clippings"
REAL_DIR = ROOT / "assets" / "real-clippings"
PACK_DIR = ROOT / "daily-packs"
USED_PATH = ROOT / "used-clippings.json"
CUT_MANIFEST = CUT_DIR / "manifest.json"
REAL_MANIFEST = REAL_DIR / "manifest.json"
LIMIT = 15
QUERIES = [
    "mask","fan","shoe","hat","vase","chair","bird","horse","dog","doll","toy","clock","vessel",
    "jewelry","brooch","ring","cup","dress","costume","armor","sculpture","shell","bottle","basket",
    "umbrella","instrument","teapot","animal sculpture","ceramic animal","wood figure","decorative object",
    "miniature","figurine","pitcher","plate","textile fragment","coin","statue","lamp","box","jar"
]

def load_json(path: Path, fallback):
    if not path.exists(): return fallback
    return json.loads(path.read_text())

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def slugify(s: str) -> str:
    s = (s or "object").lower().replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:58].strip("-") or "object")

def tomorrow_eastern() -> str:
    # GitHub Pages/app rotates at America/New_York midnight. This script usually runs on Jason's Mac in ET.
    return (dt.date.today() + dt.timedelta(days=1)).isoformat()

def existing_used() -> dict:
    data = load_json(USED_PATH, {"usedSlugs": [], "packs": {}})
    data.setdefault("usedSlugs", [])
    data.setdefault("packs", {})
    return data

def clip_key(row: dict) -> str:
    return row.get("slug") or Path(row.get("file", "")).stem

def choose_pack(date_key: str, target: int) -> list[dict]:
    manifest = load_json(CUT_MANIFEST, [])
    used = existing_used()
    used_slugs = set(used.get("usedSlugs", []))
    available = [m for m in manifest if Path(ROOT / m.get("file", "")).exists() and clip_key(m) not in used_slugs]
    seed = int(hashlib.sha256(f"clipping-club-pack-{date_key}".encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    rng.shuffle(available)
    return available[:target]

def write_pack(date_key: str, rows: list[dict], force: bool=False):
    if len(rows) < LIMIT:
        raise SystemExit(f"Only {len(rows)} unused clippings available; need {LIMIT}.")
    path = PACK_DIR / f"{date_key}.json"
    if path.exists() and not force:
        print(f"Pack already exists: {path}")
        return
    pack = {
        "date": date_key,
        "limit": LIMIT,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "clippings": [
            {
                "slug": clip_key(r),
                "label": r.get("label") or clip_key(r).replace("-", " "),
                "meta": r.get("meta") or "public-domain cutout",
                "src": r["file"],
                "sourceUrl": r.get("sourceUrl") or r.get("source"),
            }
            for r in rows[:LIMIT]
        ],
    }
    save_json(path, pack)
    used = existing_used()
    used["packs"][date_key] = [c["slug"] for c in pack["clippings"]]
    merged = list(dict.fromkeys(list(used.get("usedSlugs", [])) + used["packs"][date_key]))
    used["usedSlugs"] = merged
    save_json(USED_PATH, used)
    print(f"Wrote {path} with {len(pack['clippings'])} never-used clippings.")

def ensure_cutout_tooling():
    venv = Path(os.environ.get("CLIPPING_CUTOUT_VENV", "/tmp/clipping-cutout-venv"))
    py = venv / "bin" / "python"
    if not py.exists():
        print("Creating temporary cutout tooling venv...")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
        subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([str(py), "-m", "pip", "install", "pillow", "rembg", "onnxruntime"])
    return py

def run_collector(max_add: int):
    # Execute the collector inside the venv so Pillow/rembg are available.
    py = ensure_cutout_tooling()
    code = COLLECTOR_CODE.replace("__MAX_ADD__", str(max_add))
    subprocess.check_call([str(py), "-u", "-c", code], cwd=str(ROOT))

COLLECTOR_CODE = r'''
from pathlib import Path
from PIL import Image
from rembg import remove, new_session
import urllib.request, urllib.parse, json, re, io, time, signal
ROOT=Path.cwd(); REAL_DIR=ROOT/'assets'/'real-clippings'; CUT_DIR=ROOT/'assets'/'cutout-clippings'
REAL_DIR.mkdir(parents=True, exist_ok=True); CUT_DIR.mkdir(parents=True, exist_ok=True)
REAL_MANIFEST=REAL_DIR/'manifest.json'; CUT_MANIFEST=CUT_DIR/'manifest.json'; USED_PATH=ROOT/'used-clippings.json'
def load(p,f): return json.loads(p.read_text()) if p.exists() else f
def save(p,d): p.write_text(json.dumps(d, indent=2, ensure_ascii=False)+'\n')
real=load(REAL_MANIFEST,[]); cut=load(CUT_MANIFEST,[]); used=load(USED_PATH,{"usedSlugs":[],"packs":{}})
existing={m.get('slug') for m in real} | set(used.get('usedSlugs',[]))
queries=''' + repr(QUERIES) + r'''
def slugify(s):
    s=(s or 'object').lower().replace('&','and'); s=re.sub(r'[^a-z0-9]+','-',s).strip('-'); return (s[:58].strip('-') or 'object')
def fetch_json(url):
    req=urllib.request.Request(url, headers={'User-Agent':'ClippingClubDailyCollector/1.0'})
    with urllib.request.urlopen(req, timeout=20) as r: return json.load(r)
def fetch_bytes(url):
    req=urllib.request.Request(url, headers={'User-Agent':'ClippingClubDailyCollector/1.0'})
    with urllib.request.urlopen(req, timeout=25) as r: return r.read()
class Timeout(Exception): pass
def handler(signum, frame): raise Timeout()
signal.signal(signal.SIGALRM, handler)
cands=[]; seen=set()
for q in queries:
    url='https://api.artic.edu/api/v1/artworks/search?'+urllib.parse.urlencode({'q':q,'is_public_domain':'true','fields':'id,title,image_id,artwork_type_title,department_title,is_public_domain','limit':'20'})
    try: data=fetch_json(url).get('data',[])
    except Exception as e: print('search err', q, e); continue
    for item in data:
        if not item.get('image_id') or not item.get('is_public_domain'): continue
        aid=item['id']; slug=f"aic-{aid}-{slugify(item.get('title') or q)}"
        if aid in seen or slug in existing: continue
        seen.add(aid); cands.append((q,item,slug))
    time.sleep(.05)
print('collector candidates', len(cands))
session=new_session('u2netp')
added=0; tried=0
for q,item,slug in cands:
    if added >= __MAX_ADD__ or tried >= 140: break
    tried += 1; fname=f'{slug}.png'
    try:
        print('TRY', tried, slug, flush=True)
        signal.alarm(55)
        raw=fetch_bytes(f"https://www.artic.edu/iiif/2/{item['image_id']}/full/900,/0/default.jpg")
        im=Image.open(io.BytesIO(raw)).convert('RGBA'); im.thumbnail((950,950), Image.LANCZOS)
        out=remove(im, session=session).convert('RGBA'); signal.alarm(0)
        alpha=out.getchannel('A'); bbox=alpha.getbbox()
        if not bbox: continue
        pix=list(alpha.getdata()); ratio=sum(1 for a in pix if a>18)/len(pix)
        l,t,r,b=bbox; bbox_area=((r-l)*(b-t))/(out.width*out.height); touches=sum([l<=2,t<=2,r>=out.width-2,b>=out.height-2])
        if not (0.035 <= ratio <= 0.78 and bbox_area <= 0.90 and touches < 4):
            print(' skip mask', round(ratio,2), round(bbox_area,2), touches, flush=True); continue
        pad=30; cutim=out.crop((max(0,l-pad), max(0,t-pad), min(out.width,r+pad), min(out.height,b+pad)))
        rr,gg,bb,aa=cutim.split(); aa=aa.point(lambda v: 0 if v<16 else (255 if v>248 else v)); cutim.putalpha(aa)
        im.save(REAL_DIR/fname, optimize=True); cutim.save(CUT_DIR/fname, optimize=True)
        row={'slug':slug,'label':(item.get('title') or q.title())[:70],'meta':(item.get('artwork_type_title') or item.get('department_title') or 'public-domain image')[:50],'src':f'assets/real-clippings/{fname}','source':'Art Institute of Chicago API','sourceUrl':f'https://www.artic.edu/artworks/{item["id"]}','imageId':item['image_id'],'publicDomain':True}
        crow={**row,'file':f'assets/cutout-clippings/{fname}','sourceFile':f'assets/real-clippings/{fname}','alphaRatio':round(ratio,3),'bboxArea':round(bbox_area,3)}
        real.append(row); cut.append(crow); existing.add(slug); added += 1
        print(' ADD', added, slug, flush=True)
    except Timeout:
        signal.alarm(0); print(' timeout', slug, flush=True)
    except Exception as e:
        signal.alarm(0); print(' err', type(e).__name__, e, flush=True)
    time.sleep(.05)
save(REAL_MANIFEST, real); save(CUT_MANIFEST, cut)
print('collector added', added, 'total cutouts', len(cut))
'''

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=tomorrow_eastern(), help="YYYY-MM-DD pack date; default tomorrow")
    ap.add_argument("--target", type=int, default=LIMIT)
    ap.add_argument("--collect-if-needed", action="store_true")
    ap.add_argument("--collect-count", type=int, default=25)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    PACK_DIR.mkdir(exist_ok=True)
    rows = choose_pack(args.date, args.target)
    if len(rows) < args.target and args.collect_if_needed:
        need = args.target - len(rows)
        run_collector(max(args.collect_count, need + 10))
        rows = choose_pack(args.date, args.target)
    write_pack(args.date, rows, force=args.force)

if __name__ == "__main__":
    main()
