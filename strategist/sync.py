r"""Sync the hosted copy (D25) to the dashboard database, and check what is there.

Usage (from the Tribe folder):
    python -m strategist.sync export [--out DIR]    write every payload to DIR for a look
                                                    (default %TEMP%\tribe-export), nothing sent
    python -m strategist.sync push [--allow-empty]  build, re-run the privacy scan, then upsert the
                                                    pages, the peak pictures and the brain assets and
                                                    remove the ones whose source is gone
    python -m strategist.sync audit                 pull every row back and re-run the privacy scan

Every payload comes from strategist/hosted.py (field-by-field projections, each checked
against strategist/hosted_schema/). push scans the whole bundle again just before it
writes and refuses on any hit, so nothing private reaches the database: one bad page
stops the push and nothing is sent. Pages are upserted with a sha256 of their canonical
JSON, so an unchanged page is left alone. push manages board, reel, patterns, lab, tribe,
brain and meta; the spend page is the runner's (it reads the ledger and Apify's usage).

Brain assets (D28, strategist/brain_assets.py) go in the same transaction, after the pages:
push reads the stored hashes first and upserts only the assets whose gzip bytes changed, then
removes the ones no brain page uses. A brain page follows its source: a link that is gone or a
missing preds.npy removes the page and its frames; the shared mesh and atlas stay while one
brain page uses them. A linked job with preds.npy while the atlas or the mesh is missing
refuses the whole push (run scoring/build_atlas.py), so nothing is wiped by accident.

The database is only reached through strategist/db.py (the tribe_runner role, URL from
the Tribe .env, never printed). push builds while holding the swipe lock (store.locked,
re-entrant, so the runner can call it inside a job). A run with no reels on the laptop
would remove every reel page, so push keeps them unless --allow-empty says it is meant.

Exit codes: 0 ok, 1 the audit found problems, 2 refused. Standard library only (push and
audit need psycopg, as strategist/db.py says).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from . import contract, db, hosted, store

DEFAULT_OUT = Path(tempfile.gettempdir()) / "tribe-export"
WEB = store.PROJECT_ROOT / "web"
MANIFEST = "manifest.json"


class SyncError(Exception):
    """A sync step was refused. The message says why and holds no private words."""


# ---------------------------------------------------------------- building

def build(today: dt.date | None = None, now: dt.datetime | None = None) -> tuple[dict, hosted.PrivateRuns]:
    """The checked bundle and the private runs it was scanned against."""
    private = hosted.private_runs()
    try:
        return hosted.build_all(today, now, private), private
    except hosted.HostedError as e:
        raise SyncError(str(e)) from None


def scan(bundle: dict, private: hosted.PrivateRuns) -> None:
    """The privacy scan, run again over the whole bundle right before it leaves. Refuses on any hit."""
    problems = hosted.bundle_problems(bundle, private)
    if problems:
        raise SyncError("the privacy scan refused the push, nothing was sent: " + "; ".join(problems))


def sizes(bundle: dict) -> list[tuple[str, int]]:
    """(kind/key, image key or asset key, bytes) for every page, image and brain asset (gzip bytes,
    as the database stores them)."""
    out = [(f"{kind}/{key}", hosted.size_of(page)) for kind, key, page in bundle["pages"]]
    out += [(key, len(png)) for key, png in sorted(bundle["images"].items())]
    return out + [(f"{key} (gzip; {a.raw_bytes:,} B unpacked)", len(a.data))
                  for key, a in sorted((bundle.get("assets") or {}).items())]


# ---------------------------------------------------------------- export

def export(bundle: dict, out=None) -> Path:
    """Write the payloads to out/<kind>/<key>.json, the pictures to out/images/..., the brain
    assets decompressed to out/assets/<key>, and a manifest with sizes and hashes. Clears what an
    earlier export wrote there first."""
    out = Path(out) if out else DEFAULT_OUT
    resolved = out.resolve()
    if resolved == WEB.resolve() or WEB.resolve() in resolved.parents:
        raise SyncError("web/ holds synthetic fixtures only: export somewhere else")
    for kind in hosted.SYNC_KINDS:
        for p in (out / kind).glob("*.json") if (out / kind).is_dir() else []:
            p.unlink()
    for p in (out / "images").rglob("*.png") if (out / "images").is_dir() else []:
        p.unlink()
    for p in (out / "assets").rglob("*") if (out / "assets").is_dir() else []:
        if p.is_file() and p.suffix in (".i8", ".bin"):
            p.unlink()
    rows = []
    for kind, key, page in bundle["pages"]:
        path = out / kind / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(page, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        rows.append({"kind": kind, "key": key, "bytes": hosted.size_of(page), "hash": db.page_hash(page)})
    images = []
    for key, png in sorted(bundle["images"].items()):
        path = out / "images" / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        images.append({"key": key, "bytes": len(png), "hash": hashlib.sha256(png).hexdigest()})
    assets = []
    for key, a in sorted((bundle.get("assets") or {}).items()):
        path = out / "assets" / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(a.raw)
        assets.append({"key": key, "kind": a.kind, "bytes": len(a.data), "raw_bytes": a.raw_bytes, "hash": a.hash})
    manifest = {"exported_at": store.now_iso(), "pages": rows, "images": images, "assets": assets,
                "total_bytes": sum(r["bytes"] for r in rows) + sum(i["bytes"] for i in images)
                + sum(a["bytes"] for a in assets)}
    (out / MANIFEST).write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    return out


# ---------------------------------------------------------------- push

def _transaction(conn):
    tx = getattr(conn, "transaction", None)
    return tx() if callable(tx) else contextlib.nullcontext()


def push(conn, bundle: dict, private: hosted.PrivateRuns, allow_empty: bool = False, log=print) -> dict:
    """Scan, then upsert every page (content hash), picture and brain asset (only the ones whose
    hash changed), and remove pages, pictures and assets whose source is gone, in one transaction.
    Returns what changed."""
    scan(bundle, private)
    keys = {kind: [] for kind in hosted.SYNC_KINDS}
    for kind, key, _ in bundle["pages"]:
        if kind not in keys:
            raise SyncError(f"push does not manage {kind} pages")
        keys[kind].append(key)
    assets = bundle.get("assets") or {}
    done = {"changed": [], "same": 0, "removed": [], "images": [], "images_removed": [], "kept": [],
            "assets": [], "assets_same": 0, "assets_removed": []}
    try:
        with _transaction(conn):
            for kind, key, page in bundle["pages"]:
                if db.upsert_page(conn, kind, key, page["v"], page, db.page_hash(page)):
                    done["changed"].append(f"{kind}/{key}")
                else:
                    done["same"] += 1
            for kind, wanted in keys.items():
                if not wanted and kind in ("board", "patterns", "meta", "reel") and not allow_empty:
                    done["kept"].append(kind)   # nothing built: never wipe the site by accident
                    continue
                done["removed"] += [f"{kind}/{k}" for k in db.delete_missing(conn, kind, wanted, allow_empty=True)]
            for key, png in sorted(bundle["images"].items()):
                if db.upsert_image(conn, key, png):
                    done["images"].append(key)
            done["images_removed"] = db.delete_missing_images(conn, list(bundle["images"]))
            stored = db.brain_asset_hashes(conn)
            for key, a in sorted(assets.items()):
                if stored.get(key) == a.hash:
                    done["assets_same"] += 1
                elif db.upsert_brain_asset(conn, a.key, a.kind, a.mime, a.data, a.raw_bytes, a.hash):
                    done["assets"].append(key)
            done["assets_removed"] = db.delete_missing_brain_assets(conn, list(assets))
    except db.DbError as e:
        raise SyncError(f"push stopped, nothing was saved: {e}") from None
    for kind in done["kept"]:
        log(f"Note: no {kind} pages were built, so the old ones were kept (--allow-empty removes them).")
    return done


# ---------------------------------------------------------------- audit

def audit(conn, private: hosted.PrivateRuns | None = None) -> list[str]:
    """Every problem with what the database holds: schema, key, hash, the rule checks, paths,
    private runs, pictures that are not clean PNGs under 1 MB, and brain assets (kind and mime
    agree with the key, sha256 matches, the gzip unpacks to raw_bytes and passes the structure
    check; every brain page's keys are stored with its hashes, no asset is left without a page,
    every brain page has a tribe page with the same seconds)."""
    private = private if private is not None else hosted.private_runs()
    problems, images = [], {}
    try:
        rows, stored, assets = db.list_pages(conn), db.list_images(conn), db.list_brain_assets(conn)
    except db.DbError as e:
        raise SyncError(f"audit could not read the database: {e}") from None
    for img in stored:
        images[img["key"]] = img
        what = f"image {img['key']}"
        if img["mime"] != "image/png":
            problems.append(f"{what}: stored as {img['mime']!r}, not image/png")
        if hashlib.sha256(img["bytes"]).hexdigest() != img["hash"]:
            problems.append(f"{what}: hash does not match its bytes")
    problems += hosted.bundle_problems({"pages": [], "images": {k: v["bytes"] for k, v in images.items()}}, private)
    for row in rows:
        kind, key, page = row["kind"], row["key"], row["page"]
        where = f"{kind}/{key}"
        if kind not in contract.page_kinds():
            problems.append(f"{where}: not a page kind")
            continue
        if not isinstance(page, dict):
            problems.append(f"{where}: not a JSON object")
            continue
        if page.get("v") != row["v"]:
            problems.append(f"{where}: v {row['v']!r} does not match the page's own v")
        if db.page_hash(page) != row["hash"]:
            problems.append(f"{where}: hash does not match its JSON")
        try:
            if contract.page_key(kind, page) != key:
                problems.append(f"{where}: stored under the wrong key")
        except contract.ContractError as e:
            problems.append(f"{where}: {e}")
        problems += hosted.page_problems(kind, page, private)
        img = (page.get("peak_image") or {}).get("key") if kind == "tribe" else None
        if img and img not in images:
            problems.append(f"{where}: its peak picture {img} is not in images")
    for a in assets:
        if a.get("encoding") != "gzip":
            problems.append(f"asset {a['key']}: stored with encoding {a.get('encoding')!r}, not gzip")
    problems += hosted.brain_problems([(r["kind"], r["key"], r["page"]) for r in rows],
                                      {a["key"]: {"kind": a["kind"], "mime": a["mime"], "data": a["bytes"],
                                                  "raw_bytes": a["raw_bytes"], "hash": a["hash"]} for a in assets})
    return problems


# ---------------------------------------------------------------- CLI

def _connect():
    db.load_env()
    return db.connect()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strategist.sync",
                                 description="Export, push or audit the hosted copy of the swipe pages (D25).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write every payload to a folder for a look (nothing is sent)")
    ex.add_argument("--out", default=None, help=f"folder (default {DEFAULT_OUT})")
    pu = sub.add_parser("push", help="scan, then upsert pages and pictures into the dashboard database")
    pu.add_argument("--allow-empty", action="store_true", help="remove every reel page when the laptop has none")
    sub.add_parser("audit", help="pull every row back and re-run the privacy scan")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "audit":
            conn = _connect()
            try:
                problems = audit(conn)
            finally:
                conn.close()
            for p in problems:
                print(f"Problem: {p}")
            print("Audit clean: every row passed the schema and privacy checks." if not problems
                  else f"Audit found {len(problems)} problem(s).")
            return 1 if problems else 0
        if args.cmd == "push":
            with store.locked():   # one consistent read of swipe/ (re-entrant when the runner holds it)
                bundle, private = build()
        else:
            bundle, private = build()
        if args.cmd == "export":
            scan(bundle, private)
            out = export(bundle, args.out)
            for name, n in sizes(bundle):
                print(f"{n:>9,} B  {name}")
            print(f"Wrote {len(bundle['pages'])} pages, {len(bundle['images'])} pictures and "
                  f"{len(bundle.get('assets') or {})} brain assets to {out}")
            return 0
        conn = _connect()
        try:
            done = push(conn, bundle, private, allow_empty=args.allow_empty)
        finally:
            conn.close()
        print(f"Pushed {len(done['changed'])} changed page(s), {done['same']} unchanged, removed "
              f"{len(done['removed'])}; pictures: {len(done['images'])} changed, {len(done['images_removed'])} removed; "
              f"brain assets: {len(done['assets'])} changed, {done['assets_same']} unchanged, "
              f"{len(done['assets_removed'])} removed.")
        for name in done["changed"] + done["assets"] + [f"removed {r}" for r in done["removed"] + done["images_removed"]
                                                         + done["assets_removed"]]:
            print(f"  {name}")
        return 0
    except (SyncError, db.DbError, store.StoreError) as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    except Exception as e:   # e.g. a database error mid-push: the transaction rolled back; the URL is never shown
        print(f"Refused: {args.cmd} failed ({type(e).__name__}: "
              f"{db.scrub(str(e), os.environ.get(db.DSN_ENV, ''))})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
