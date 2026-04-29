"""Deeper probes — confirm Reportable REST works with projectURI, and inspect a real EWM work item."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

c = DOORSNextClient(os.environ['DOORS_URL'], os.environ['DOORS_USERNAME'], os.environ['DOORS_PASSWORD'])
c.authenticate()

results = {}
def probe(name, url, accept='application/xml', headers=None):
    h = {'Accept': accept, 'OSLC-Core-Version': '2.0', 'X-Requested-With': 'XMLHttpRequest'}
    if headers: h.update(headers)
    try:
        r = c.session.get(url, headers=h, timeout=60, allow_redirects=False)
        snippet = (r.text or '')[:600].replace('\n', ' ')
        info = {'status': r.status_code, 'len': len(r.text or ''), 'ct': r.headers.get('Content-Type', ''), 'snippet': snippet}
        print(f'{name}: HTTP {r.status_code} ({len(r.text or "")} bytes)')
        if r.status_code == 200:
            print(f'    snippet: {snippet[:250]}')
        results[name] = info
        return r
    except Exception as e:
        results[name] = {'error': str(e)}
        print(f'{name}: ERR {e}')
        return None

# --- Reportable REST with projectURI ---
# Pick OEM-F PoC — a real DNG project
proj_uri = 'https://goblue.clm.ibmcloud.com/rm/process/project-areas/_jvXPuf5-Eeqfpqm1iTtiiw'
print(f'\n=== Reportable REST (DNG) for project {proj_uri} ===')
probe('rrm_modules', f'{c.base_url}/publish/modules?projectURI={proj_uri}&size=2')
probe('rrm_text', f'{c.base_url}/publish/text?projectURI={proj_uri}&size=1')
probe('rrm_collections', f'{c.base_url}/publish/collections?projectURI={proj_uri}&size=2')
probe('rrm_links', f'{c.base_url}/publish/links?projectURI={proj_uri}&size=2')
probe('rrm_comments', f'{c.base_url}/publish/comments?projectURI={proj_uri}&size=2')
probe('rrm_views', f'{c.base_url}/publish/views?projectURI={proj_uri}&size=2')
probe('rrm_folders', f'{c.base_url}/publish/folders?projectURI={proj_uri}&size=2')

# --- DNG types catalog (attribute defs) ---
print('\n=== DNG types ===')
proj_sp = 'https://goblue.clm.ibmcloud.com/rm/oslc_rm/_jvXPuf5-Eeqfpqm1iTtiiw/services.xml'
probe('dng_services', proj_sp, accept='application/rdf+xml')

# --- Run an OSLC query for an actual work item ---
print('\n=== EWM work item GET ===')
ewm_q = "https://goblue.clm.ibmcloud.com/ccm/oslc/contexts/_NriAMPR6EeqGRvJUHcwY_A/workitems?oslc.pageSize=1"
r = probe('ewm_q1', ewm_q, accept='application/rdf+xml')
# Extract a single workitem URL from the response and GET it
import re
match = re.search(r'rdf:about="([^"]*workitem[^"]*)"', r.text or '')
wi_url = None
if match:
    wi_url = match.group(1)
    print(f'Found work item: {wi_url}')
    probe('ewm_workitem_full', wi_url, accept='application/rdf+xml')
    # Try the actions/workflow endpoint for this work item
    probe('ewm_wi_actions',  wi_url + '?_oslc_cm.properties=oslc:status', accept='application/rdf+xml')

# --- ETM testcase actual ---
print('\n=== ETM TestCase query ===')
etm_q = "https://goblue.clm.ibmcloud.com/qm/oslc_qm/contexts/_V07wQPR6EeqC750T623lOQ/resources/com.ibm.rqm.planning.VersionedTestCase?oslc.pageSize=1"
probe('etm_testcase_q', etm_q, accept='application/rdf+xml')

# --- DNG attribute definition + artifact format query ---
print('\n=== DNG attribute defs query ===')
# Use the AttributeDefinition Query Capability we found in services.xml
# Discover its URL by re-parsing services.xml
r2 = c.session.get(proj_sp, headers={'Accept': 'application/rdf+xml', 'OSLC-Core-Version': '2.0'}, timeout=60)
import xml.etree.ElementTree as ET
NS = {'rdf':'http://www.w3.org/1999/02/22-rdf-syntax-ns#','dcterms':'http://purl.org/dc/terms/','oslc':'http://open-services.net/ns/core#'}
root = ET.fromstring(r2.content)
for qc in root.findall('.//oslc:QueryCapability', NS):
    title = qc.find('dcterms:title', NS)
    qbase = qc.find('oslc:queryBase', NS)
    if title is not None and 'AttributeDefinition' in (title.text or ''):
        url = qbase.get(f'{{{NS["rdf"]}}}resource', '')
        probe('dng_attrdef_query', url + '?oslc.pageSize=2', accept='application/rdf+xml')
        break
for qc in root.findall('.//oslc:QueryCapability', NS):
    title = qc.find('dcterms:title', NS)
    qbase = qc.find('oslc:queryBase', NS)
    if title is not None and 'LinkType' in (title.text or ''):
        url = qbase.get(f'{{{NS["rdf"]}}}resource', '')
        probe('dng_linktype_query', url + '?oslc.pageSize=2', accept='application/rdf+xml')
        break

with open(os.path.join(os.path.dirname(__file__), 'oslc_deep_probes.json'), 'w') as f:
    json.dump(results, f, indent=2)
print('\nDone')
