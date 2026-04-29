"""SCM Probe 02: drill into the SCM ServiceProviderCatalog discovered in
rootservices. The catalog should list per-component / per-project SCM
service providers, each with workspaces/changesets/components query
capabilities."""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

PROBE_DIR = os.path.dirname(os.path.abspath(__file__))
client = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
client.authenticate()

H_RDF = {"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"}
CCM = client.ccm_url

# 1) Fetch the SCM catalog
catalog_url = f"{CCM}/oslc-scm/catalog"
print(f"GET {catalog_url}")
r = client.session.get(catalog_url, headers=H_RDF, timeout=30)
print(f"  -> {r.status_code} bytes={len(r.content)} ct={r.headers.get('content-type')}")
with open(os.path.join(PROBE_DIR, "scm_02_catalog.xml"), "wb") as f:
    f.write(r.content)

# 2) Parse out all ServiceProvider URLs
provider_urls = re.findall(r'oslc:ServiceProvider rdf:about="([^"]+)"', r.text)
provider_urls += re.findall(r'<oslc:serviceProvider[^>]*rdf:resource="([^"]+)"', r.text)
provider_urls = sorted(set(provider_urls))
print(f"\nFound {len(provider_urls)} ServiceProvider URL(s) in catalog")
for u in provider_urls[:10]:
    print(f"  {u}")

# 3) Fetch first few service providers and dump
for i, sp_url in enumerate(provider_urls[:5]):
    print(f"\nGET service provider [{i}]: {sp_url}")
    rr = client.session.get(sp_url, headers=H_RDF, timeout=30)
    print(f"  -> {rr.status_code} bytes={len(rr.content)}")
    out = os.path.join(PROBE_DIR, f"scm_02_provider_{i}.xml")
    with open(out, "wb") as f:
        f.write(rr.content)

    # Quick scan of the service provider for the goodies
    text = rr.text
    factories = re.findall(r'oslc:CreationFactory[\s\S]*?</oslc:CreationFactory>', text)
    queries  = re.findall(r'oslc:QueryCapability[\s\S]*?</oslc:QueryCapability>', text)
    dialogs  = re.findall(r'oslc:Dialog[\s\S]*?</oslc:Dialog>', text)
    print(f"  factories={len(factories)} queries={len(queries)} dialogs={len(dialogs)}")
    # Show titles + URLs
    for q in queries:
        title = re.search(r'<dcterms:title[^>]*>(.*?)</dcterms:title>', q, re.DOTALL)
        base  = re.search(r'oslc:queryBase rdf:resource="([^"]+)"', q)
        usages= re.findall(r'oslc:usage rdf:resource="([^"]+)"', q)
        print(f"    Q: {(title.group(1).strip() if title else '?')[:50]:<50}  base={base.group(1) if base else '?'}")
        for u in usages: print(f"        usage={u}")
    for fac in factories:
        title = re.search(r'<dcterms:title[^>]*>(.*?)</dcterms:title>', fac, re.DOTALL)
        base  = re.search(r'oslc:creation rdf:resource="([^"]+)"', fac)
        usages= re.findall(r'oslc:usage rdf:resource="([^"]+)"', fac)
        print(f"    F: {(title.group(1).strip() if title else '?')[:50]:<50}  create={base.group(1) if base else '?'}")
        for u in usages: print(f"        usage={u}")

with open(os.path.join(PROBE_DIR, "scm_02_provider_urls.json"), "w") as f:
    json.dump(provider_urls, f, indent=2)
print(f"\nSaved {len(provider_urls)} provider URLs to scm_02_provider_urls.json")
