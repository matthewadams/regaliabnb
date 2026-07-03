#!/usr/bin/env python3
"""Render a review card from a queued JSON descriptor (run in CI by the workflow).

Usage: python3 tools/render_from_queue.py review-cards/queue/airb-<id>.json
The JSON keys: id, name, quote, property, date, url  (seed defaults to id).
Output: review-cards/<id>.png
"""
import sys, json, os, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "g", os.path.join(HERE, "generate_review_card.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

data = json.load(open(sys.argv[1]))
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
)
print("rendered", out)
