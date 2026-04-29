"""Verify write permissions on the sandbox project, with full error capture."""
import sys, os, json, urllib.parse, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from doors_client import DOORSNextClient

c = DOORSNextClient(os.environ["DOORS_URL"], os.environ["DOORS_USERNAME"], os.environ["DOORS_PASSWORD"])
c.authenticate()

with open(os.path.join(os.path.dirname(__file__), "SANDBOX_PROJECTS.json")) as f:
    sandbox = json.load(f)

project_url = sandbox["dng"]["services_url"]
project_area_id = sandbox["dng"]["project_area_id"]
project_area_url = f"{c.base_url}/process/project-areas/{project_area_id}"

print(f"Project: {sandbox['dng']['title']}")
print(f"  URL: {project_url}\n")

# Step 1: list folders to verify read works
print("[A] List folders (read test)")
ns = c._NS_OSLC
resp = c.session.get(
    f"{c.base_url}/folders",
    params={"oslc.where": f"public_rm:parent={project_area_url}", "oslc.select": "*"},
    headers={"Accept": "application/rdf+xml", "OSLC-Core-Version": "2.0"},
    timeout=30,
)
print(f"  status: {resp.status_code}  bytes: {len(resp.content)}")
import xml.etree.ElementTree as ET
root = ET.fromstring(resp.content)
folders = []
for item in root.findall(f'.//{{{ns["nav"]}}}folder'):
    title_el = item.find('dcterms:title', ns)
    about = item.get(f'{{{ns["rdf"]}}}about')
    if about:
        folders.append((title_el.text if title_el is not None else '?', about))
print(f"  found {len(folders)} root-level folder(s):")
for t, u in folders[:10]:
    print(f"    - {t!r}  {u}")

# Step 2: try to create a folder with FULL response capture
print("\n[B] Create folder (write test) -- capture full response")
folder_name = f"MCP Test Folder {time.strftime('%H%M%S')}"
root_folder_url = c._get_root_folder_url(project_url)
print(f"  root folder URL: {root_folder_url}")

folder_rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:nav="http://jazz.net/ns/rm/navigation#"
         xmlns:process="http://jazz.net/ns/process#">
  <nav:folder>
    <dcterms:title>{folder_name}</dcterms:title>
    <nav:parent rdf:resource="{root_folder_url}"/>
    <process:projectArea rdf:resource="{project_area_url}"/>
  </nav:folder>
</rdf:RDF>'''

encoded_pa = urllib.parse.quote(project_area_url, safe="")
resp = c.session.post(
    f"{c.base_url}/folders?projectURL={encoded_pa}",
    data=folder_rdf.encode("utf-8"),
    headers={
        "Content-Type": "application/rdf+xml",
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
        "X-Requested-With": "XMLHttpRequest",
    },
    timeout=30,
)
print(f"  status: {resp.status_code}")
print(f"  Location: {resp.headers.get('Location')}")
print(f"  --- body ---")
print(resp.text[:2000])
