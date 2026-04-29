"""Probe additional ELM endpoints to confirm capabilities the MCP could expose:
- Reportable REST API on DNG (separate from OSLC)
- EWM workflow/state actions
- ETM test environments / execution records query
- DNG attribute definitions / link validity
- Process API
Read-only.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

c = DOORSNextClient(os.environ['DOORS_URL'], os.environ['DOORS_USERNAME'], os.environ['DOORS_PASSWORD'])
print('auth:', c.authenticate())

results = {}
def probe(name, url, headers=None, accept='application/rdf+xml'):
    h = {'Accept': accept, 'OSLC-Core-Version': '2.0', 'X-Requested-With': 'XMLHttpRequest'}
    if headers:
        h.update(headers)
    try:
        r = c.session.get(url, headers=h, timeout=30, allow_redirects=False)
        snippet = (r.text or '')[:500].replace('\n', ' ')
        info = {'status': r.status_code, 'len': len(r.text or ''), 'ct': r.headers.get('Content-Type', ''), 'snippet': snippet}
        print(f'{name}: HTTP {r.status_code} ({len(r.text or "")} bytes, ct={info["ct"]})')
        results[name] = info
        return r
    except Exception as e:
        results[name] = {'error': str(e)}
        print(f'{name}: ERR {e}')
        return None

# === Reportable REST API on DNG (NOT OSLC) ===
# Endpoint: /rm/publish/<resource>?projectURI=<uri>
# Resources: requirements, modules, collections, comments, links, screenflows, etc.
publish_base = f"{c.base_url}/publish"
print('\n--- DNG Reportable REST ---')
probe('publish_requirements_root', publish_base + '/requirements', accept='application/xml')
probe('publish_modules_root',      publish_base + '/modules',      accept='application/xml')
probe('publish_text_root',         publish_base + '/text',         accept='application/xml')
probe('publish_comments_root',     publish_base + '/comments',     accept='application/xml')
probe('publish_links_root',        publish_base + '/links',        accept='application/xml')
probe('publish_collections_root',  publish_base + '/collections',  accept='application/xml')
probe('publish_views_root',        publish_base + '/views',        accept='application/xml')
probe('publish_folders_root',      publish_base + '/folders',      accept='application/xml')

# === Process API ===
print('\n--- Process API ---')
probe('rm_process_areas',  f"{c.base_url}/process/project-areas", accept='application/xml')
probe('ccm_process_areas', f"{c.ccm_url}/process/project-areas", accept='application/xml')
probe('qm_process_areas',  f"{c.qm_url}/process/project-areas", accept='application/xml')

# === EWM workflow / current user ===
print('\n--- EWM workflow & queries ---')
probe('ccm_whoami', f"{c.ccm_url}/whoami", accept='application/json')
probe('ccm_rootservices', f"{c.ccm_url}/rootservices")
# OSLC query: get a few work items from sandbox project
ewm_q = ("https://goblue.clm.ibmcloud.com/ccm/oslc/contexts/_NriAMPR6EeqGRvJUHcwY_A"
         "/workitems?oslc.pageSize=3&oslc.select=dcterms:title,oslc_cm:status")
probe('ewm_oslc_query_3', ewm_q)
# Workflow: an arbitrary work item URL — try a known shape to see if action API reachable
# /ccm/oslc/workflow/<projectId>/states  (proprietary)
probe('ccm_workflow_states_proj', f"{c.ccm_url}/oslc/workflow/_NriAMPR6EeqGRvJUHcwY_A/states", accept='application/xml')
probe('ccm_workflow_actions_proj', f"{c.ccm_url}/oslc/workflow/_NriAMPR6EeqGRvJUHcwY_A/actions", accept='application/xml')

# === ETM ===
print('\n--- ETM probes ---')
probe('qm_whoami', f"{c.qm_url}/service/com.ibm.rqm.foundation.common.service.IRepositoryService/whoami", accept='application/json')
probe('qm_rootservices', f"{c.qm_url}/rootservices")
# Try the QM REST API (proprietary) for testplans
probe('qm_testplan_query', f"{c.qm_url}/service/com.ibm.rqm.integration.service.IIntegrationService/resources", accept='application/xml')

# === DNG attribute defs + link validity ===
print('\n--- DNG advanced ---')
# Attribute definition catalog (per project)
probe('dng_rootservices', f"{c.base_url}/rootservices")
probe('dng_oslc_rm_catalog', f"{c.base_url}/oslc_rm/catalog")
probe('dng_link_validity', f"{c.base_url}/link-validity", accept='application/json')
probe('dng_terms_glossary', f"{c.base_url}/glossary", accept='application/xml')
# Comments on a known artifact (probe shape)
probe('dng_comments_resource', f"{c.base_url}/types?oslc.pageSize=1")
# History: any shape?
probe('dng_history_endpoint', f"{c.base_url}/history?oslc.pageSize=1")

# === GCM ===
print('\n--- GCM ---')
probe('gc_rootservices', f"{c.gc_url}/rootservices")
probe('gc_oslc_query_components', f"{c.gc_url}/oslc-query/components?oslc.pageSize=2")
probe('gc_oslc_query_baselines', f"{c.gc_url}/oslc-query/baselines?oslc.pageSize=2")
probe('gc_changesets', f"{c.gc_url}/oslc-query/changesets?oslc.pageSize=2")

with open(os.path.join(os.path.dirname(__file__), 'oslc_endpoint_probes.json'), 'w') as f:
    json.dump(results, f, indent=2)
print('\nWrote oslc_endpoint_probes.json')
