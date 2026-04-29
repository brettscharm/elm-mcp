"""Read-only probe: authenticate and list projects.

Usage: python3 probe/01_auth_and_projects.py
"""
import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from doors_client import DOORSNextClient

URL = os.environ["DOORS_URL"]
USER = os.environ["DOORS_USERNAME"]
PWD = os.environ["DOORS_PASSWORD"]

print(f"Connecting to {URL} as {USER}...")
client = DOORSNextClient(URL, USER, PWD)
ok = client.authenticate()
print(f"  authenticate() -> {ok}")

if not ok:
    sys.exit(1)

print("\nListing projects across domains...")
domain_calls = [
    ("dng", client.list_projects),
    ("ewm", client.list_ewm_projects),
    ("etm", client.list_etm_projects),
]
all_projects = {}
for label, fn in domain_calls:
    try:
        projects = fn()
        all_projects[label] = projects
        print(f"\n  [{label}] {len(projects)} project(s):")
        for p in projects[:15]:
            print(f"    - {p.get('title')!r}  url={p.get('url')}")
    except Exception as e:
        print(f"  [{label}] ERROR: {type(e).__name__}: {e}")

with open(os.path.join(os.path.dirname(__file__), "all_projects.json"), "w") as f:
    json.dump(all_projects, f, indent=2)
print(f"\nSaved to probe/all_projects.json")
