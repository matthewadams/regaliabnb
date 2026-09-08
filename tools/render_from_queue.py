#!/usr/bin/env python3
"""Render a queued card from a JSON descriptor (run in CI by the workflow).

Handles four kinds of queue entries, all under review-cards/queue/*.json:

1. Review card (original): keys id, name, quote, property, date, url; seed
   defaults to id; optional scheme. Output: review-cards/<id>.png

2. CMA card: identified by the presence of a "panels" key. The JSON is the
   generate_cma_card.py spec (property, specs, dates, nights, checked, panels,
   optional direct_line, cta) plus control keys out (target PNG path, defaults
   to review-cards/<stem>.png), seed (defaults to stem) and optional scheme.

3. Photo collage: identified by "kind": "photo_collage". The JSON is the
   render_booking_collage.py spec (id, photos, title, subtitle, theme).
   Output: review-cards/<id>.png

4. Image passthrough: identified by "kind": "image_b64". Key b64 holds a
   base64-encoded image (webp/jpeg/png) which is decoded and re-saved as PNG
   at "out". This exists because the GitHub connector stores file content as
   UTF-8 text and cannot push binary directly, so a supplied photo has to ride
   in as text and be materialized here in CI.

Usage: python3 tools/render_from_queue.py review-cards/queue/<name>.json
"""
import sys, json, os, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(modfile, name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(HERE, modfile))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


path = sys.argv[1]
data = json.load(open(path))
stem = os.path.splitext(os.path.basename(path))[0]

# --- Image passthrough branch (identified by kind == "image_b64") ---
if data.get("kind") == "image_b64":
    import base64, io, hashlib
    from PIL import Image
    out = data.get("out") or os.path.join("review-cards", f"{stem}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    raw = base64.b64decode(data["b64"], validate=True)
    src_sha = hashlib.sha256(raw).hexdigest()
    expect = data.get("sha256")
    if expect and expect != src_sha:
        raise SystemExit(
            f"payload sha256 mismatch: got {src_sha}, expected {expect}")
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.save(out, "PNG", optimize=True)
    print("rendered", out, os.path.getsize(out), "bytes", img.size,
          "payload sha256", src_sha)
    sys.exit(0)

# --- Photo collage branch (identified by kind == "photo_collage") ---
if data.get("kind") == "photo_collage":
    bc = _load("render_booking_collage.py", "bc")
    out = data.get("out") or os.path.join(
        "review-cards", "%s.png" % data.get("id", stem))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bc.collage(data).save(out, optimize=True)
    print("rendered", out, os.path.getsize(out), "bytes")
    sys.exit(0)

# --- CMA card branch (identified by "panels") ---
if "panels" in data:
    gc = _load("generate_cma_card.py", "gc")
    out = data.get("out") or os.path.join("review-cards", f"{stem}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    gc.make_cma_card(data, out, seed=data.get("seed", stem),
                     scheme=data.get("scheme"))
    print("rendered", out)
    sys.exit(0)

# --- Review card branch (original behavior) ---
g = _load("generate_review_card.py", "g")
rid = data["id"]
out = os.path.join("review-cards", f"{rid}.png")

# The verified badge derives from the cardId prefix (no separate field needed):
#   airb- -> airbnb, vrbo- -> vrbo, hosp- -> hospitable
PREFIX_PLATFORM = {"airb": "airbnb", "vrbo": "vrbo", "hosp": "hospitable"}
platform = PREFIX_PLATFORM.get(rid.split("-", 1)[0], "")

g.make_card(
    data["name"], data["quote"], data["property"], out,
    seed=data.get("seed", rid),
    date=data.get("date", ""),
    url=data.get("url", "https://regaliabnb.com"),
    platform=platform,
    scheme=data.get("scheme"),
)
print("rendered", out)
