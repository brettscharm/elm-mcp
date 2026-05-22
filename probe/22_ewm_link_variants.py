"""Probe which RDF predicate EWM accepts for the 'implements requirement'
cross-domain link. We tried calm:implementsRequirement; the server
silently dropped it. IBM's elmclient test data shows three candidate
predicate URLs:

  1. http://open-services.net/xmlns/prod/jazz/calm/1.0/implementsRequirement
     (calm: prefix — the one we sent, server dropped it)
  2. http://jazz.net/xmlns/prod/jazz/rtc/cm/1.0/com.ibm.team.workitem.linktype.implementsRequirement.implements
     (rtc_cm: prefix with the long RTC linktype name)
  3. http://open-services.net/ns/cm#implementsRequirement
     (oslc_cm: standard CM domain link)

Try each in isolation and verify by re-fetching.
"""
import sys, os, json, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

c = DOORSNextClient(os.environ.get("ELM_URL") or os.environ["DOORS_URL"],
                    os.environ.get("ELM_USERNAME") or os.environ["DOORS_USERNAME"],
                    os.environ.get("ELM_PASSWORD") or os.environ["DOORS_PASSWORD"])
c.authenticate()
with open(os.path.join(os.path.dirname(__file__), "SANDBOX_PROJECTS.json")) as f:
    sandbox = json.load(f)

# Setup: existing requirement to link to
shapes = c.get_artifact_shapes(sandbox["dng"]["services_url"])
shape = next(s["url"] for s in shapes if s["name"].lower() == "system requirement")
folder = (c.find_folder(sandbox["dng"]["services_url"], "Link Probe")
          or c.create_folder(sandbox["dng"]["services_url"], "Link Probe"))
run = time.strftime("%H%M%S")
req = c.create_requirement(
    project_url=sandbox["dng"]["services_url"],
    title=f"Link probe req {run}",
    content="Test req for link probe",
    shape_url=shape, folder_url=folder["url"],
)
req_url = req["url"]
print(f"DNG req: {req_url}\n")

ewm_projects = c.list_ewm_projects()
ewm_proj = next(p for p in ewm_projects if p["title"] == sandbox["ewm"]["title"])
factories = c._get_ewm_creation_factories(ewm_proj["url"])
creation_url = factories["Task"]
print(f"Task creation factory: {creation_url}\n")

variants = [
    ("A: calm:implementsRequirement (the one that's failing)",
     'xmlns:calm="http://open-services.net/xmlns/prod/jazz/calm/1.0/"',
     '<calm:implementsRequirement rdf:resource="{u}"/>'),
    ("B: oslc_cm:implementsRequirement (OSLC CM standard)",
     'xmlns:oslc_cm="http://open-services.net/ns/cm#"',
     '<oslc_cm:implementsRequirement rdf:resource="{u}"/>'),
    ("C: rtc_cm full linktype name (the IBM internal form)",
     'xmlns:rtc_cm="http://jazz.net/xmlns/prod/jazz/rtc/cm/1.0/"',
     '<rtc_cm:com.ibm.team.workitem.linktype.implementsRequirement.implements rdf:resource="{u}"/>'),
    ("D: oslc_cm:relatedChangeRequest (generic CM cross-domain link)",
     'xmlns:oslc_cm="http://open-services.net/ns/cm#"',
     '<oslc_cm:relatedChangeRequest rdf:resource="{u}"/>'),
]

for label, ns_decl, link_template in variants:
    title = f"Probe {label[:1]} {run}"
    link_xml = link_template.format(u=req_url)
    rdf = f"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         {ns_decl}>
  <rdf:Description>
    <dcterms:title>{title}</dcterms:title>
    <dcterms:description>{label}</dcterms:description>
    {link_xml}
  </rdf:Description>
</rdf:RDF>"""
    resp = c.session.post(
        creation_url,
        data=rdf.encode("utf-8"),
        headers={
            "Content-Type": "application/rdf+xml",
            "Accept": "application/rdf+xml",
            "OSLC-Core-Version": "2.0",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"[{label}] CREATE FAILED: {resp.status_code} — {resp.text[:200]}")
        continue
    task_url = resp.headers.get("Location", "")
    # Re-fetch and look for the link
    r = c.session.get(task_url, headers={"Accept":"application/rdf+xml","OSLC-Core-Version":"2.0"},
                       allow_redirects=True, timeout=30)
    # Search for any predicate whose value is our req URL
    refs = re.findall(r'<([a-zA-Z_0-9.]+:[a-zA-Z_0-9.]+)\s+rdf:resource="' + re.escape(req_url) + '"', r.text)
    reified = re.search(r'rdf:object\s+rdf:resource="' + re.escape(req_url) + '"', r.text)
    has_predicate = re.search(r'<rdf:predicate\s+rdf:resource="([^"]*implementsRequirement[^"]*)"', r.text)
    print(f"[{label}]")
    print(f"  task: {task_url}")
    print(f"  direct triples to req: {refs}")
    print(f"  reified rdf:object→req: {bool(reified)}")
    if has_predicate:
        print(f"  reified predicate URI: {has_predicate.group(1)}")
    print(f"  RESULT: {'LINKED' if (refs or reified) else 'DROPPED'}\n")
