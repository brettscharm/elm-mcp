"""Probe: do DNG requirements render tables and images in jazz_rm:primaryText?

If yes, we just need to teach the converter to emit the right XHTML.
"""
import sys, os, json, time, urllib.parse, re
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

shapes = c.get_artifact_shapes(project_url)
shape = next(s["url"] for s in shapes if s["name"].lower() == "system requirement")
folder = c.find_folder(project_url, "RichText Probe") or c.create_folder(project_url, "RichText Probe")
run = time.strftime("%H%M%S")

# Hand-build the body with table + image + bullets + link.
# Use literal Unicode characters (not HTML entities) since parseType=Literal
# is strict XML and only knows the 5 XML entities (&amp; &lt; &gt; &quot; &apos;).
xhtml_body = '''<div xmlns="http://www.w3.org/1999/xhtml">
  <p><strong>[AI Generated]</strong></p>
  <h3>Section 1: Functional Requirement</h3>
  <p>The system <em>shall</em> maintain temperature within <strong>±0.5°C</strong> of setpoint.</p>

  <h4>Acceptance criteria</h4>
  <ul>
    <li>Verified with calibrated thermometer</li>
    <li>Tested across full operating range</li>
    <li>Repeated over a 24-hour period</li>
  </ul>

  <h4>Test conditions</h4>
  <table border="1">
    <thead>
      <tr><th>Parameter</th><th>Min</th><th>Max</th><th>Tolerance</th></tr>
    </thead>
    <tbody>
      <tr><td>Temperature</td><td>-20°C</td><td>85°C</td><td>±0.5°C</td></tr>
      <tr><td>Humidity</td><td>10%</td><td>95%</td><td>±3%</td></tr>
      <tr><td>Voltage</td><td>3.0V</td><td>5.5V</td><td>±0.05V</td></tr>
    </tbody>
  </table>

  <h4>Reference diagram</h4>
  <p><img src="https://www.ibm.com/cloud/architecture/static/ibm-logo-21d0eda6cdb7f9b5e8a85d7da19f4f43.svg" alt="IBM logo"/></p>

  <p>See related <a href="https://www.example.com/spec">specification document</a>.</p>
</div>'''

# POST directly with an embedded jazz_rm:primaryText
prefixed_title = f"[AI Generated] RichText Probe {run}"
encoded_pa = urllib.parse.quote(project_area_url, safe="")

rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#"
         xmlns:oslc="http://open-services.net/ns/core#"
         xmlns:nav="http://jazz.net/ns/rm/navigation#"
         xmlns:jazz_rm="http://jazz.net/ns/rm#">
  <oslc_rm:Requirement>
    <dcterms:title>{prefixed_title}</dcterms:title>
    <dcterms:description rdf:parseType="Literal"></dcterms:description>
    <jazz_rm:primaryText rdf:parseType="Literal">{xhtml_body}</jazz_rm:primaryText>
    <oslc:instanceShape rdf:resource="{shape}"/>
    <nav:parent rdf:resource="{folder['url']}"/>
  </oslc_rm:Requirement>
</rdf:RDF>'''

resp = c.session.post(
    f"{c.base_url}/requirementFactory?projectURL={encoded_pa}",
    data=rdf.encode("utf-8"),
    headers={
        "Content-Type": "application/rdf+xml; charset=utf-8",
        "Accept": "application/rdf+xml",
        "OSLC-Core-Version": "2.0",
        "X-Requested-With": "XMLHttpRequest",
    },
    timeout=30,
)
print(f"POST status: {resp.status_code}")
if resp.status_code != 201:
    print(resp.text[:500])
    sys.exit(1)
url = resp.headers["Location"]
print(f"Created: {url}")

# Re-fetch and check what came back
r = c.session.get(url, headers={"Accept":"application/rdf+xml","OSLC-Core-Version":"2.0"}, timeout=30)
m = re.search(r'<jazz_rm:primaryText[^>]*>(.*?)</jazz_rm:primaryText>', r.text, re.DOTALL)
if m:
    body = m.group(1)
    print(f"\nBody size: {len(body)} chars")
    has_table = "<table" in body or "&lt;table" in body
    has_img = "<img" in body or "&lt;img" in body
    has_list = "<ul" in body or "&lt;ul" in body
    print(f"  contains <table>: {has_table}")
    print(f"  contains <img>:   {has_img}")
    print(f"  contains <ul>:    {has_list}")
    print(f"\nFirst 600 chars of stored body:")
    print(body[:600])
print(f"\nOpen in DNG: {url}")
