"""Probe: fetch a binding (BI_*) artifact to see how it points to the
underlying requirement, AND fetch the project's services.xml to find
the creation factories (especially for module-bound creates)."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

PROBE_DIR = os.path.dirname(__file__)
client = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
client.authenticate()

# Pull first BI_* URL from the saved module RDF
with open(os.path.join(PROBE_DIR, "module_raw.xml")) as f:
    raw = f.read()
binding_urls = re.findall(r'rdf:resource="(https://[^"]+/resources/BI_[^"]+)"', raw)
print(f"Found {len(binding_urls)} binding URLs in module")
binding_url = binding_urls[0]
print(f"Probing binding: {binding_url}\n")

# Fetch the binding
r = client.session.get(
    binding_url,
    headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
    timeout=30,
)
print(f"  status: {r.status_code}  bytes: {len(r.content)}")
print(f"  content-type: {r.headers.get('content-type')}\n")
with open(os.path.join(PROBE_DIR, "binding_raw.xml"), "wb") as f:
    f.write(r.content)
print("--- binding RDF (first 60 lines) ---")
print("\n".join(r.text.split("\n")[:60]))

# Fetch services.xml for the project to find creation factories
print("\n\n=== PROJECT SERVICES.XML ===\n")
project_url = "https://goblue.clm.ibmcloud.com/rm/oslc_rm/_yGWz8PR5Eeq_3JxeOWm9kg/services.xml"
r = client.session.get(
    project_url,
    headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
    timeout=30,
)
print(f"  status: {r.status_code}  bytes: {len(r.content)}")
with open(os.path.join(PROBE_DIR, "services.xml"), "wb") as f:
    f.write(r.content)

# Find all CreationFactory entries
factories = re.findall(
    r'<oslc:CreationFactory>(.*?)</oslc:CreationFactory>',
    r.text,
    re.DOTALL,
)
print(f"\nFound {len(factories)} CreationFactory entries:\n")
for fac in factories:
    title = re.search(r'<dcterms:title[^>]*>(.*?)</dcterms:title>', fac, re.DOTALL)
    creation = re.search(r'oslc:creation rdf:resource="([^"]+)"', fac)
    usages = re.findall(r'oslc:usage rdf:resource="([^"]+)"', fac)
    print(f"  Title:    {title.group(1).strip() if title else '?'}")
    print(f"  creation: {creation.group(1) if creation else '?'}")
    for u in usages:
        print(f"  usage:    {u}")
    print()
