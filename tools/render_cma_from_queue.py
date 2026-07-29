#!/usr/bin/env python3
"""Render a CMA card from a queued JSON descriptor (run in CI by the workflow).

Usage: python3 tools/render_cma_from_queue.py cma-cards/queue/<name>.json

The JSON is the generate_cma_card.py spec (property, specs, dates, nights,
checked, panels, optional direct_line, cta) plus three control keys:
  out    - target PNG path, e.g. "cma-cards/cma-<slug>-<checkin>-<HHMM>.png"
  seed   - render seed (defaults to the file stem)
  scheme - color scheme name/int (optional)
Output: the PNG at `out`.
"""
import sys, json, os, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "g", os.path.join(HERE, "generate_cma_card.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

path = sys.argv[1]
data = json.load(open(path))
out = data["out"]
os.makedirs(os.path.dirname(out), exist_ok=True)
seed = data.get("seed", os.path.splitext(os.path.basename(path))[0])
g.make_cma_card(data, out, seed=seed, scheme=data.get("scheme"))
print("rendered", out)
