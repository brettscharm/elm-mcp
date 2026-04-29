"""Final probes: confirm comments, DNG artifact OPTIONS, EWM action workflow."""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

c = DOORSNextClient(os.environ['DOORS_URL'], os.environ['DOORS_USERNAME'], os.environ['DOORS_PASSWORD'])
c.authenticate()

results = {}
def probe(name, url, accept='application/rdf+xml', method='GET'):
    h = {'Accept': accept, 'OSLC-Core-Version': '2.0', 'X-Requested-With': 'XMLHttpRequest'}
    try:
        if method == 'OPTIONS':
            r = c.session.options(url, headers=h, timeout=30, allow_redirects=False)
        else:
            r = c.session.get(url, headers=h, timeout=30, allow_redirects=True)
        snippet = (r.text or '')[:600].replace('\n',' ')
        info = {'status': r.status_code, 'len': len(r.text or ''),
                'allow': r.headers.get('Allow', ''),
                'ct': r.headers.get('Content-Type', ''),
                'snippet': snippet}
        print(f'{name}: HTTP {r.status_code} (len={len(r.text or "")} allow={info["allow"]})')
        if r.status_code == 200 and len(r.text or '') < 3000:
            print(f'    snippet: {snippet[:300]}')
        results[name] = info
        return r
    except Exception as e:
        results[name] = {'error': str(e)}
        print(f'{name}: ERR {e}')
        return None

# 1. Get a DNG requirement and inspect it for comments resource and OPTIONS
print('\n=== DNG requirement OPTIONS / comments ===')
# Use OEM-F PoC project, OSLC requirement query
proj_sp = 'https://goblue.clm.ibmcloud.com/rm/oslc_rm/_jvXPuf5-Eeqfpqm1iTtiiw/services.xml'
import xml.etree.ElementTree as ET
NS = {'rdf':'http://www.w3.org/1999/02/22-rdf-syntax-ns#','dcterms':'http://purl.org/dc/terms/','oslc':'http://open-services.net/ns/core#'}
sp = c.session.get(proj_sp, headers={'Accept':'application/rdf+xml','OSLC-Core-Version':'2.0'}, timeout=60)
root = ET.fromstring(sp.content)
req_q_url = None
for qc in root.findall('.//oslc:QueryCapability', NS):
    title = qc.find('dcterms:title', NS)
    if title is not None and (title.text or '').strip() == 'Query Capability':
        qbase = qc.find('oslc:queryBase', NS)
        req_q_url = qbase.get(f'{{{NS["rdf"]}}}resource', '')
        break
print('req_q_url:', req_q_url)
if req_q_url:
    r = probe('req_q_first', req_q_url + '?oslc.pageSize=1')
    m = re.search(r'rdf:about="([^"]*resources/[A-Z0-9_-]+)"', r.text or '')
    if m:
        req_url = m.group(1)
        print(f'sample req: {req_url}')
        probe('req_get', req_url, accept='application/rdf+xml')
        probe('req_options', req_url, method='OPTIONS')

# 2. Reportable REST for a single module's text (to see attribute defs in the data)
print('\n=== Reportable REST sample sizes ===')
proj_uri = 'https://goblue.clm.ibmcloud.com/rm/process/project-areas/_jvXPuf5-Eeqfpqm1iTtiiw'
probe('rrm_modules_total', f'{c.base_url}/publish/modules?projectURI={proj_uri}&abbreviate=false&size=1', accept='application/xml')

# 3. EWM: get workflow definition for a project (XML)
print('\n=== EWM workflow ===')
probe('ccm_workitem_types', 'https://goblue.clm.ibmcloud.com/ccm/oslc/types/_NriAMPR6EeqGRvJUHcwY_A', accept='application/rdf+xml')
probe('ccm_workitem_states_for_type', 'https://goblue.clm.ibmcloud.com/ccm/oslc/types/_NriAMPR6EeqGRvJUHcwY_A/task', accept='application/rdf+xml')
# Iteration / timeline
probe('ccm_iterations', f'{c.ccm_url}/oslc/iterations.xml', accept='application/xml')

# 4. EWM single work item — non-OSLC (just GET and look at it)
ewm_q = "https://goblue.clm.ibmcloud.com/ccm/oslc/contexts/_NriAMPR6EeqGRvJUHcwY_A/workitems?oslc.pageSize=1&oslc.select=dcterms:title,oslc_cm:status,oslc:instanceShape"
r = c.session.get(ewm_q, headers={'Accept':'application/rdf+xml','OSLC-Core-Version':'2.0'}, timeout=30)
m = re.search(r'rdf:about="(https://goblue[^"]*workitems/\d+)"', r.text or '')
if m:
    wi_url = m.group(1)
    print(f'EWM wi: {wi_url}')
    probe('ewm_wi_get', wi_url, accept='application/rdf+xml')
    probe('ewm_wi_options', wi_url, method='OPTIONS')

# 5. ETM rootservices and capabilities
print('\n=== ETM ===')
r = c.session.get(f'{c.qm_url}/rootservices', headers={'Accept':'application/rdf+xml'}, timeout=30)
# Note any URLs that look interesting (testplan, configurations)
for line in r.text.split('\n'):
    if 'http' in line and ('config' in line.lower() or 'testplan' in line.lower() or 'qm' in line.lower()):
        print('  ', line.strip()[:200])

# 6. GCM: stream/baseline operations. Try component's configurations URL
print('\n=== GCM components ===')
r = c.session.get(f'{c.gc_url}/oslc-query/components?oslc.pageSize=2',
                  headers={'Accept':'application/rdf+xml','OSLC-Core-Version':'2.0'}, timeout=30)
m = re.search(r'oslc_config:configurations rdf:resource="([^"]+)"', r.text or '')
if m:
    cfgs_url = m.group(1)
    print('cfgs_url:', cfgs_url)
    probe('gcm_component_configs', cfgs_url, accept='application/rdf+xml')

with open(os.path.join(os.path.dirname(__file__), 'oslc_final_probes.json'), 'w') as f:
    json.dump(results, f, indent=2)
print('\nDONE')
