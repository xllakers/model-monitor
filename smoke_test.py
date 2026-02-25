"""Quick smoke test — run from project root."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from fetchers import lmarena
from analyzer import analyze

print("Fetching lmarena...")
data = lmarena.fetch()

current = data["current"]
for cat in ("general", "coding"):
    rows = current.get(cat, [])
    print(f"{cat}: {len(rows)} models")
    for r in rows[:3]:
        print(f"  #{r['rank']} {r['model_id']} score={r['score']}")

print("\nRunning analyzer...")
result = analyze(data, {}, {})

for win in ("7d", "30d"):
    for cat in ("general", "coding"):
        risers = result["fast_risers"][win][cat]
        print(f"Fast risers [{win}][{cat}]: {len(risers)}")
    ns = result["new_stars"][win]
    print(f"New stars [{win}]: {len(ns)}")

print(f"General rankings:    {len(result['rankings']['general'])} models")
print(f"Last updated:        {result['last_updated']}")

print("\nTop 5 general:")
for r in result['rankings']['general'][:5]:
    print(f"  #{r['rank']} {r['model_id']} ELO={r['elo']}")

print("\nTop 5 coding:")
for r in result['rankings']['coding'][:5]:
    print(f"  #{r['rank']} {r['model_id']} ELO={r['elo']}")

print("\nOK")
