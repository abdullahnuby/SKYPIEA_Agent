from __future__ import annotations

import json
import sys
from collections import Counter

path = sys.argv[1] if len(sys.argv) > 1 else "data/sim_pilot.json"
cats = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 80
data = json.loads(open(path, encoding="utf-8").read())
fails = data["failures"]
if cats:
    fails = [f for f in fails if f["cat"] in cats]
groups = Counter((f["cat"], f["kind"], f["detail"][:90]) for f in fails)
for (cat, kind, detail), count in groups.most_common(limit):
    print(f"[{count:>3}] {cat} / {kind}: {detail}")
    seen = 0
    for f in fails:
        if (f["cat"], f["kind"], f["detail"][:90]) == (cat, kind, detail) and seen < 2:
            print(f"      «{f['text'][:110]}» -> {f['reply'][:90]!r} tool={f['tool']} dec={f['decision']}")
            seen += 1
    print()
