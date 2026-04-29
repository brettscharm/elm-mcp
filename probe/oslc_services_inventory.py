"""Probe: enumerate every CreationFactory + QueryCapability + Dialog
across a sample of EWM and ETM projects, plus DNG. Read-only."""
import os, sys, json, xml.etree.ElementTree as ET
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

NS = {
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'dcterms': 'http://purl.org/dc/terms/',
    'oslc': 'http://open-services.net/ns/core#',
}

client = DOORSNextClient(os.environ['DOORS_URL'], os.environ['DOORS_USERNAME'], os.environ['DOORS_PASSWORD'])
res = client.authenticate()
print('auth:', res)

with open(os.path.join(os.path.dirname(__file__), 'all_projects.json')) as f:
    projects = json.load(f)

# Sample one EWM + one ETM + one DNG project (with content) — and 2 extras
sample = {
    'dng': [projects['dng'][3], projects['dng'][6]],   # OEM-F PoC, Automotive SPICE
    'ewm': [projects['ewm'][0], projects['ewm'][3] if len(projects['ewm']) > 3 else None],
    'etm': [projects['etm'][0], projects['etm'][3] if len(projects['etm']) > 3 else None],
}

inventory = defaultdict(lambda: {'factories': [], 'queries': [], 'dialogs': []})

def enumerate_services(domain, project):
    if not project: return
    sp_url = project['url']
    print(f'\n=== {domain.upper()} :: {project["title"]} ===')
    print(f'    {sp_url}')
    try:
        r = client.session.get(sp_url, headers={
            'Accept': 'application/rdf+xml',
            'OSLC-Core-Version': '2.0',
        }, timeout=60)
        if r.status_code != 200:
            print(f'    HTTP {r.status_code}')
            return
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f'    err: {e}')
        return

    for cf in root.findall('.//oslc:CreationFactory', NS):
        title = cf.find('dcterms:title', NS)
        creation = cf.find('oslc:creation', NS)
        rtypes = cf.findall('oslc:resourceType', NS)
        title_t = title.text if title is not None else '?'
        creation_url = creation.get(f'{{{NS["rdf"]}}}resource', '') if creation is not None else ''
        types = [rt.get(f'{{{NS["rdf"]}}}resource', '') for rt in rtypes]
        inventory[domain]['factories'].append({
            'title': title_t, 'creation': creation_url, 'types': types,
        })
        print(f'   FACTORY  {title_t!r}  -> types={types[-1] if types else None}')

    for qc in root.findall('.//oslc:QueryCapability', NS):
        title = qc.find('dcterms:title', NS)
        qbase = qc.find('oslc:queryBase', NS)
        rtypes = qc.findall('oslc:resourceType', NS)
        title_t = title.text if title is not None else '?'
        qbase_url = qbase.get(f'{{{NS["rdf"]}}}resource', '') if qbase is not None else ''
        types = [rt.get(f'{{{NS["rdf"]}}}resource', '') for rt in rtypes]
        inventory[domain]['queries'].append({
            'title': title_t, 'queryBase': qbase_url, 'types': types,
        })
        print(f'   QUERY    {title_t!r}  -> types={types[-1] if types else None}')

    for d in root.findall('.//oslc:Dialog', NS):
        title = d.find('dcterms:title', NS)
        usages = d.findall('oslc:usage', NS)
        rtypes = d.findall('oslc:resourceType', NS)
        title_t = title.text if title is not None else '?'
        types = [rt.get(f'{{{NS["rdf"]}}}resource', '') for rt in rtypes]
        usage_uris = [u.get(f'{{{NS["rdf"]}}}resource', '') for u in usages]
        inventory[domain]['dialogs'].append({
            'title': title_t, 'usages': usage_uris, 'types': types,
        })

for domain in ['dng', 'ewm', 'etm']:
    for proj in sample[domain]:
        enumerate_services(domain, proj)

# Save inventory
out = os.path.join(os.path.dirname(__file__), 'oslc_services_inventory.json')
with open(out, 'w') as f:
    json.dump(inventory, f, indent=2)

# Summarize unique resource types found
print('\n\n=== UNIQUE RESOURCE TYPES PER DOMAIN ===')
for domain in ['dng', 'ewm', 'etm']:
    types = set()
    for f in inventory[domain]['factories']:
        types.update(f['types'])
    for q in inventory[domain]['queries']:
        types.update(q['types'])
    print(f'\n{domain.upper()}:')
    for t in sorted(types):
        print(f'   {t}')
print(f'\nWrote inventory to {out}')
