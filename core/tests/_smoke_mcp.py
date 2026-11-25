"""Smoke test for MCP server tools — run without starting the stdio loop."""
import json, sys
sys.path.insert(0, '.')

from core.mcp_server import list_recordings, get_thresholds, get_live_stats, replay, set_thresholds

print("--- list_recordings ---")
recs = list_recordings()
for r in recs:
    name = r["filename"]
    label = r["label"]
    rows = r["rows"]
    dur = r["duration_s"]
    print(f"  {name:45s} label={label:10s} rows={rows} duration={dur}s")

print()
print("--- get_thresholds ---")
print(json.dumps(get_thresholds(), indent=2))

print()
print("--- get_live_stats (fresh) ---")
print(json.dumps(get_live_stats(), indent=2))

print()
print("--- replay fall ---")
result = replay("fall")
packets = result["packets_delivered"]
final = result["final_state"]
summary = result["event_summary"]
print(f"  packets={packets}  final_state={final}")
print(f"  event_summary={summary}")

print()
print("--- get_live_stats (after replay) ---")
stats = get_live_stats()
print(f"  state={stats['state']}  active_links={stats['active_links']}")
print(f"  scores (first 4): { {k: v for k, v in list(stats['scores'].items())[:4]} }")

print()
print("--- set_thresholds (round-trip test) ---")
orig = get_thresholds()["zones"]["motion_threshold"]
result2 = set_thresholds({"motion_threshold": round(orig + 0.001, 4)})
print(f"  applied={result2['applied']}")
# restore
set_thresholds({"motion_threshold": orig})
print(f"  restored to {orig}")

print()
print("--- set_thresholds (bad key) ---")
err = set_thresholds({"nonexistent_key": 99})
print(f"  status={err['status']}  message={err['message']}")

print()
print("All smoke tests passed.")
