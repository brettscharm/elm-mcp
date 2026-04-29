"""Probe a handful of likely-writable DNG projects to find one we can actually
create a folder in. This is the cheapest writable-permission test.

We try the same harmless 'create test folder' POST against each project; on 403
we know it's read-only, on 201 we know writes work.
"""
import sys, os, json, urllib.parse, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

c = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
c.authenticate()

with open(os.path.join(os.path.dirname(__file__), "all_projects.json")) as f:
    all_projects = json.load(f)

# Candidates: anything Brett-named or sandbox-named
candidates = [
    p for p in all_projects["dng"]
    if any(k in p["title"].lower() for k in ("brett", "sandbox"))
]
print(f"Will probe {len(candidates)} candidate DNG projects:\n")

run_tag = time.strftime("%H%M%S")

writable = []
for p in candidates:
    project_url = p["url"]
    pa_id = re.search(r'/oslc_rm/(_[A-Za-z0-9_-]+)/services', project_url).group(1)
    pa_url = f"{c.base_url}/process/project-areas/{pa_id}"

    # Get root folder URL for this project
    root = None
    try:
        rresp = c.session.get(
            f"{c.base_url}/folders",
            params={"oslc.where": f"public_rm:parent={pa_url}"},
            headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
            timeout=20,
        )
        m = re.search(r'<nav:folder[^>]*rdf:about="([^"]+)"', rresp.text)
        if m:
            root = m.group(1)
    except Exception as e:
        pass

    if not root:
        print(f"  [skip-no-root] {p['title']}")
        continue

    folder_rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:nav="http://jazz.net/ns/rm/navigation#"
         xmlns:process="http://jazz.net/ns/process#">
  <nav:folder>
    <dcterms:title>MCP-Probe-{run_tag}</dcterms:title>
    <nav:parent rdf:resource="{root}"/>
    <process:projectArea rdf:resource="{pa_url}"/>
  </nav:folder>
</rdf:RDF>'''
    encoded_pa = urllib.parse.quote(pa_url, safe="")
    try:
        resp = c.session.post(
            f"{c.base_url}/folders?projectURL={encoded_pa}",
            data=folder_rdf.encode("utf-8"),
            headers={
                "Content-Type": "application/rdf+xml",
                "Accept": "application/rdf+xml",
                "OSLC-Core-Version": "2.0",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=20,
        )
        marker = "OK" if resp.status_code in (200, 201) else f"{resp.status_code}"
        print(f"  [{marker}] {p['title']}")
        if resp.status_code in (200, 201):
            writable.append({"title": p["title"], "url": project_url})
    except Exception as e:
        print(f"  [ERR] {p['title']}: {e}")

print(f"\n{len(writable)} writable DNG project(s):")
for w in writable:
    print(f"  - {w['title']}  ({w['url']})")

with open(os.path.join(os.path.dirname(__file__), "writable_dng_projects.json"), "w") as f:
    json.dump(writable, f, indent=2)
