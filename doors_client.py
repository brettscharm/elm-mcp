"""
DOORS Next Generation API Client
Built by Bob & Brett Scharmett
Connects to IBM DOORS Next via OSLC and Reportable REST APIs
"""

import os
import csv
import json
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
from dotenv import load_dotenv
import requests


class DOORSNextClient:
    """Bob's client for IBM DOORS Next Generation"""

    # Request timeout in seconds
    _TIMEOUT = 60

    # Reportable REST API namespace variants (differ across DNG versions)
    _NS_VARIANTS = [
        {
            'ds': 'http://jazz.net/xmlns/prod/jazz/reporting/datasource/1.0/',
            'rrm': 'http://www.ibm.com/xmlns/rdm/reportablerest/',
        },
        {
            'ds': 'http://jazz.net/xmlns/alm/rm/datasource/v0.1',
            'rrm': 'http://www.ibm.com/xmlns/rrm/1.0/',
        },
    ]

    # OSLC namespaces (stable across versions)
    _NS_OSLC = {
        'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
        'dcterms': 'http://purl.org/dc/terms/',
        'oslc': 'http://open-services.net/ns/core#',
        'oslc_rm': 'http://open-services.net/ns/rm#',
        'nav': 'http://jazz.net/ns/rm/navigation#',
    }

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self._authenticated = False

    @property
    def _server_root(self) -> str:
        """Server root URL (without /rm, /ccm, or /qm context root)"""
        for suffix in ['/rm', '/ccm', '/qm']:
            if self.base_url.endswith(suffix):
                return self.base_url[:-len(suffix)]
        return self.base_url

    @property
    def _ccm_url(self) -> str:
        """EWM (CCM) base URL"""
        return f"{self._server_root}/ccm"

    @property
    def _qm_url(self) -> str:
        """ETM (QM) base URL"""
        return f"{self._server_root}/qm"

    @classmethod
    def from_env(cls):
        """Create client from .env file"""
        load_dotenv()
        base_url = os.getenv('DOORS_URL')
        username = os.getenv('DOORS_USERNAME')
        password = os.getenv('DOORS_PASSWORD')
        if not all([base_url, username, password]):
            raise ValueError(
                "Missing environment variables. "
                "Set DOORS_URL, DOORS_USERNAME, and DOORS_PASSWORD in your .env file."
            )
        return cls(base_url, username, password)

    def authenticate(self) -> bool:
        """Authenticate with DOORS Next using Basic Auth"""
        try:
            self.session.auth = (self.username, self.password)
            self.session.headers.update({
                'X-Requested-With': 'XMLHttpRequest'  # Prevents OIDC redirect
            })
            resp = self.session.get(
                f"{self.base_url}/rootservices",
                timeout=self._TIMEOUT,
            )
            if resp.status_code == 200:
                self._authenticated = True
                return True
            return False
        except Exception:
            return False

    def _ensure_auth(self):
        """Ensure authenticated before making requests"""
        if not self._authenticated:
            if not self.authenticate():
                raise ConnectionError("Failed to authenticate with DOORS Next")

    def _extract_project_area_id(self, service_provider_url: str) -> str:
        """Extract project area ID from service provider URL.

        Input:  https://server/rm/oslc_rm/_abc123/services.xml
        Output: _abc123
        """
        url = service_provider_url.replace('/services.xml', '')
        return url.split('/')[-1]

    # ── Projects ──────────────────────────────────────────────

    def list_projects(self) -> List[Dict]:
        """List all DNG projects from the OSLC catalog"""
        self._ensure_auth()
        try:
            resp = self.session.get(
                f"{self.base_url}/oslc_rm/catalog",
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            ns = self._NS_OSLC
            projects = []

            for sp in root.findall('.//oslc:ServiceProvider', ns):
                title_el = sp.find('dcterms:title', ns)
                about = sp.get(f'{{{ns["rdf"]}}}about')
                if title_el is not None and about:
                    projects.append({
                        'title': title_el.text,
                        'url': about,
                        'id': about.split('/')[-1] if '/' in about else about,
                    })

            return projects
        except Exception:
            return []

    # ── Modules ───────────────────────────────────────────────

    def get_modules(self, project_url: str) -> List[Dict]:
        """Get modules from a project.

        Tries the Reportable REST API first (returns actual DNG Modules),
        then falls back to OSLC folder query (returns all folders).
        """
        self._ensure_auth()
        project_area_id = self._extract_project_area_id(project_url)

        # Primary: Reportable REST API (returns real modules)
        modules = self._get_modules_reportable(project_area_id)
        if modules:
            return modules

        # Fallback: OSLC folder query
        return self._get_modules_oslc(project_url)

    def _get_modules_reportable(self, project_area_id: str) -> List[Dict]:
        """Get modules via the Reportable REST API (publish/modules endpoint).

        The /publish/modules endpoint already scopes results to module artifacts,
        so we return ALL artifacts without filtering by format string (which can
        vary across DNG versions and configurations).
        """
        project_area_url = f"{self.base_url}/process/project-areas/{project_area_id}"

        # Try different parameter names (varies by DNG version)
        for param_name in ['projectURI', 'projectURL']:
            try:
                resp = self.session.get(
                    f"{self.base_url}/publish/modules",
                    params={param_name: project_area_url},
                    headers={
                        'Accept': 'application/xml',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    timeout=self._TIMEOUT,
                )
                if resp.status_code != 200:
                    continue

                root = ET.fromstring(resp.content)

                # Try each namespace variant
                for ns_variant in self._NS_VARIANTS:
                    modules = self._parse_modules_xml(root, ns_variant)
                    if modules:
                        return modules

                # If we got a 200 but no modules parsed, try namespace-agnostic
                modules = self._parse_modules_agnostic(root)
                if modules:
                    return modules

            except requests.exceptions.Timeout:
                continue
            except Exception:
                continue

        return []

    def _parse_modules_xml(self, root: ET.Element, ns: dict) -> List[Dict]:
        """Parse modules from Reportable REST API XML.

        Returns ALL artifacts from the response — the /publish/modules endpoint
        already scopes to modules, so no format filtering needed.
        """
        modules = []
        for artifact in root.findall(f'.//{{{ns["ds"]}}}artifact'):
            title_el = artifact.find(f'{{{ns["rrm"]}}}title')
            id_el = artifact.find(f'{{{ns["rrm"]}}}identifier')
            # DNG uses <rrm:about> for the resource URL (not <rrm:url>)
            about_el = artifact.find(f'{{{ns["rrm"]}}}about')
            url_el = artifact.find(f'{{{ns["rrm"]}}}url')
            mod_el = artifact.find(f'{{{ns["rrm"]}}}modified')
            fmt_el = artifact.find(f'{{{ns["rrm"]}}}format')

            title = title_el.text if title_el is not None else 'Untitled'
            # Skip artifacts with no title and no identifier (metadata noise)
            if title == 'Untitled' and (id_el is None or not id_el.text):
                continue

            # Prefer rrm:about for URL, fall back to rrm:url
            module_url = ''
            if about_el is not None and about_el.text:
                module_url = about_el.text
            elif url_el is not None and url_el.text:
                module_url = url_el.text

            modules.append({
                'title': title,
                'id': id_el.text if id_el is not None else '',
                'url': module_url,
                'modified': mod_el.text if mod_el is not None else '',
                'format': fmt_el.text if fmt_el is not None else '',
                'source': 'reportable_api',
            })

        return modules

    def _parse_modules_agnostic(self, root: ET.Element) -> List[Dict]:
        """Namespace-agnostic fallback: look for elements by local name.

        Returns ALL artifacts — no format filtering.
        """
        modules = []
        for elem in root.iter():
            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if local == 'artifact':
                title = 'Untitled'
                identifier = ''
                about = ''
                url = ''
                modified = ''
                fmt = ''

                for child in elem.iter():
                    child_local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if child_local == 'format' and child.text:
                        fmt = child.text
                    elif child_local == 'title' and child.text:
                        title = child.text
                    elif child_local == 'identifier' and child.text:
                        identifier = child.text
                    elif child_local == 'about' and child.text:
                        about = child.text
                    elif child_local == 'url' and child.text:
                        url = child.text
                    elif child_local == 'modified' and child.text:
                        modified = child.text

                # Skip empty artifacts
                if title != 'Untitled' or identifier:
                    modules.append({
                        'title': title,
                        'id': identifier,
                        'url': about or url,
                        'modified': modified,
                        'format': fmt,
                        'source': 'reportable_api',
                    })

        return modules

    def _get_modules_oslc(self, project_url: str) -> List[Dict]:
        """Fallback: Get folders via OSLC folder query capability"""
        try:
            ns = self._NS_OSLC
            project_area_url = project_url.replace(
                '/oslc_rm/', '/process/project-areas/'
            ).replace('/services.xml', '')

            resp = self.session.get(
                f"{self.base_url}/folders",
                params={
                    'oslc.where': f'public_rm:parent={project_area_url}',
                    'oslc.select': '*',
                },
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            modules = []

            for item in root.findall(f'.//{{{ns["nav"]}}}folder'):
                title_el = item.find('dcterms:title', ns)
                about = item.get(f'{{{ns["rdf"]}}}about')
                id_el = item.find('dcterms:identifier', ns)

                if title_el is not None and about:
                    modules.append({
                        'title': title_el.text,
                        'url': about,
                        'id': id_el.text if id_el is not None else about.split('/')[-1],
                        'modified': '',
                        'format': '',
                        'source': 'oslc_folders',
                    })

                    # Get children recursively
                    children = self._get_child_folders(about, level=1)
                    modules.extend(children)

            return modules
        except Exception:
            return []

    def _get_child_folders(self, parent_url: str, level: int = 1) -> List[Dict]:
        """Recursively get child folders"""
        ns = self._NS_OSLC
        folders = []
        try:
            resp = self.session.get(
                f"{self.base_url}/folders",
                params={
                    'oslc.where': f'nav:parent={parent_url}',
                    'oslc.select': '*',
                    'oslc.pageSize': '100',
                },
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            for item in root.findall(f'.//{{{ns["nav"]}}}folder'):
                title_el = item.find('dcterms:title', ns)
                about = item.get(f'{{{ns["rdf"]}}}about')
                id_el = item.find('dcterms:identifier', ns)

                if title_el is not None and about:
                    folders.append({
                        'title': title_el.text,
                        'url': about,
                        'id': id_el.text if id_el is not None else about.split('/')[-1],
                        'modified': '',
                        'format': '',
                        'level': level,
                        'source': 'oslc_folders',
                    })
                    folders.extend(self._get_child_folders(about, level + 1))
        except Exception:
            pass
        return folders

    # ── Requirements ──────────────────────────────────────────

    def get_module_requirements(self, module_url: str, config_url: Optional[str] = None) -> List[Dict]:
        """Get requirements from a specific module by its URL.

        Uses the Reportable REST API (publish/resources?moduleURI=...).
        Falls back to OSLC parsing if Reportable namespaces don't match.

        Args:
            module_url: The module's URL
            config_url: Optional configuration context URL (baseline or stream).
                        If provided, reads requirements from that specific configuration.
        """
        self._ensure_auth()

        extra_headers = {}
        if config_url:
            extra_headers['Configuration-Context'] = config_url

        # Try both parameter names (varies by DNG version)
        for param_name in ['moduleURI', 'moduleURL']:
            try:
                headers = {
                    'Accept': 'application/xml',
                    'X-Requested-With': 'XMLHttpRequest',
                }
                headers.update(extra_headers)
                resp = self.session.get(
                    f"{self.base_url}/publish/resources",
                    params={param_name: module_url},
                    headers=headers,
                    timeout=120,  # Requirements can be large, give extra time
                )
                if resp.status_code != 200:
                    continue

                root = ET.fromstring(resp.content)

                # Try Reportable REST API namespaces
                for ns_variant in self._NS_VARIANTS:
                    reqs = self._parse_reqs_reportable(root, ns_variant)
                    if reqs:
                        return reqs

                # Try namespace-agnostic parsing
                reqs = self._parse_reqs_agnostic(root)
                if reqs:
                    return reqs

                # Try OSLC namespaces as final fallback
                reqs = self._parse_reqs_oslc(root)
                if reqs:
                    return reqs

            except requests.exceptions.Timeout:
                continue
            except Exception:
                continue

        return []

    # Known attribute namespace variants
    _NS_ATTR_VARIANTS = [
        'http://jazz.net/xmlns/alm/rm/attribute/v0.1',
        'http://jazz.net/xmlns/prod/jazz/reporting/attribute/1.0/',
    ]

    def _parse_reqs_reportable(self, root: ET.Element, ns: dict) -> List[Dict]:
        """Parse requirements from Reportable REST API XML, including custom attributes"""
        reqs = []
        for artifact in root.findall(f'.//{{{ns["ds"]}}}artifact'):
            title_el = artifact.find(f'{{{ns["rrm"]}}}title')
            id_el = artifact.find(f'{{{ns["rrm"]}}}identifier')
            desc_el = artifact.find(f'{{{ns["rrm"]}}}description')
            about_el = artifact.find(f'{{{ns["rrm"]}}}about')
            fmt_el = artifact.find(f'{{{ns["rrm"]}}}format')
            modified_el = artifact.find(f'.//{{{ns["rrm"]}}}modified')
            created_el = artifact.find(f'.//{{{ns["rrm"]}}}created')

            # Extract objectType and custom attributes
            artifact_type = ''
            custom_attributes = {}
            for ns_attr in self._NS_ATTR_VARIANTS:
                for obj_type in artifact.findall(f'.//{{{ns_attr}}}objectType'):
                    artifact_type = obj_type.get(f'{{{ns_attr}}}name', '')
                    for custom_attr in obj_type.findall(f'{{{ns_attr}}}customAttribute'):
                        attr_name = custom_attr.get(f'{{{ns_attr}}}name', '')
                        attr_value = custom_attr.get(f'{{{ns_attr}}}value', '')
                        if attr_name and attr_name != 'Identifier':
                            custom_attributes[attr_name] = attr_value
                if artifact_type:
                    break

            reqs.append({
                'id': id_el.text if id_el is not None else '',
                'title': title_el.text if title_el is not None else 'Untitled',
                'description': desc_el.text if desc_el is not None else '',
                'url': about_el.text if about_el is not None else '',
                'format': fmt_el.text if fmt_el is not None else '',
                'modified': modified_el.text if modified_el is not None else '',
                'created': created_el.text if created_el is not None else '',
                'artifact_type': artifact_type,
                'custom_attributes': custom_attributes,
            })

        return reqs

    def _parse_reqs_agnostic(self, root: ET.Element) -> List[Dict]:
        """Namespace-agnostic fallback: look for artifact elements by local name"""
        reqs = []
        for elem in root.iter():
            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if local == 'artifact':
                title = 'Untitled'
                identifier = ''
                description = ''
                about = ''
                fmt = ''
                modified = ''
                created = ''

                for child in elem.iter():
                    child_local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    text = child.text or ''
                    if child_local == 'title' and text:
                        title = text
                    elif child_local == 'identifier' and text:
                        identifier = text
                    elif child_local == 'description' and text:
                        description = text
                    elif child_local == 'about' and text:
                        about = text
                    elif child_local == 'format' and text:
                        fmt = text
                    elif child_local == 'modified' and text:
                        modified = text
                    elif child_local == 'created' and text:
                        created = text

                if title != 'Untitled' or identifier:
                    reqs.append({
                        'id': identifier,
                        'title': title,
                        'description': description,
                        'url': about,
                        'format': fmt,
                        'modified': modified,
                        'created': created,
                    })

        return reqs

    def _parse_reqs_oslc(self, root: ET.Element) -> List[Dict]:
        """Fallback: Parse requirements using OSLC namespaces"""
        ns = self._NS_OSLC
        reqs = []
        for req_el in root.findall('.//oslc_rm:Requirement', ns):
            about = req_el.get(f'{{{ns["rdf"]}}}about', '')
            title_el = req_el.find('dcterms:title', ns)
            desc_el = req_el.find('dcterms:description', ns)
            id_el = req_el.find('dcterms:identifier', ns)
            status_el = req_el.find('oslc_rm:status', ns)
            type_el = req_el.find('dcterms:type', ns)

            reqs.append({
                'id': id_el.text if id_el is not None else (about.split('/')[-1] if about else ''),
                'title': title_el.text if title_el is not None else 'Untitled',
                'description': desc_el.text if desc_el is not None else '',
                'url': about,
                'format': type_el.text if type_el is not None else '',
                'modified': '',
                'created': '',
                'status': status_el.text if status_el is not None else '',
            })

        return reqs

    # ── Write: Folders ────────────────────────────────────────

    def create_folder(self, project_url: str, folder_name: str, parent_folder_url: Optional[str] = None) -> Optional[Dict]:
        """Create a folder in a DNG project.

        If parent_folder_url is None, creates under the project root folder.
        Returns dict with 'title' and 'url' of the created folder, or None on failure.
        """
        self._ensure_auth()
        project_area_id = self._extract_project_area_id(project_url)
        project_area_url = f"{self.base_url}/process/project-areas/{project_area_id}"

        # Find parent folder (root if not specified)
        if not parent_folder_url:
            parent_folder_url = self._get_root_folder_url(project_url)
            if not parent_folder_url:
                return None

        folder_rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:nav="http://jazz.net/ns/rm/navigation#"
         xmlns:process="http://jazz.net/ns/process#"
         xmlns:oslc_config="http://open-services.net/ns/config#">
  <nav:folder>
    <dcterms:title>{folder_name}</dcterms:title>
    <nav:parent rdf:resource="{parent_folder_url}"/>
    <process:projectArea rdf:resource="{project_area_url}"/>
  </nav:folder>
</rdf:RDF>'''

        import urllib.parse
        encoded_pa = urllib.parse.quote(project_area_url, safe='')

        try:
            resp = self.session.post(
                f"{self.base_url}/folders?projectURL={encoded_pa}",
                data=folder_rdf.encode('utf-8'),
                headers={
                    'Content-Type': 'application/rdf+xml',
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code in [200, 201]:
                return {
                    'title': folder_name,
                    'url': resp.headers.get('Location', ''),
                }
            return None
        except Exception:
            return None

    def _get_root_folder_url(self, project_url: str) -> Optional[str]:
        """Get the root folder URL for a project"""
        ns = self._NS_OSLC
        project_area_url = project_url.replace(
            '/oslc_rm/', '/process/project-areas/'
        ).replace('/services.xml', '')

        try:
            resp = self.session.get(
                f"{self.base_url}/folders",
                params={
                    'oslc.where': f'public_rm:parent={project_area_url}',
                    'oslc.select': '*',
                },
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return None

            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.content)
            for item in root.findall(f'.//{{{ns["nav"]}}}folder'):
                about = item.get(f'{{{ns["rdf"]}}}about')
                if about:
                    return about
            return None
        except Exception:
            return None

    def find_folder(self, project_url: str, folder_name: str) -> Optional[Dict]:
        """Find an existing folder by name in a project"""
        self._ensure_auth()
        ns = self._NS_OSLC
        project_area_url = project_url.replace(
            '/oslc_rm/', '/process/project-areas/'
        ).replace('/services.xml', '')

        try:
            resp = self.session.get(
                f"{self.base_url}/folders",
                params={
                    'oslc.where': f'public_rm:parent={project_area_url}',
                    'oslc.select': '*',
                },
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return None

            root = ET.fromstring(resp.content)

            # Check root level and children
            for item in root.findall(f'.//{{{ns["nav"]}}}folder'):
                title_el = item.find('dcterms:title', ns)
                about = item.get(f'{{{ns["rdf"]}}}about')
                if title_el is not None and title_el.text == folder_name:
                    return {'title': title_el.text, 'url': about}

                # Check children of root
                if about:
                    child_result = self._find_child_folder(about, folder_name)
                    if child_result:
                        return child_result

            return None
        except Exception:
            return None

    def _find_child_folder(self, parent_url: str, folder_name: str) -> Optional[Dict]:
        """Search for a folder by name in children of a parent folder"""
        ns = self._NS_OSLC
        try:
            resp = self.session.get(
                f"{self.base_url}/folders",
                params={
                    'oslc.where': f'nav:parent={parent_url}',
                    'oslc.select': '*',
                    'oslc.pageSize': '100',
                },
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return None

            root = ET.fromstring(resp.content)
            for item in root.findall(f'.//{{{ns["nav"]}}}folder'):
                title_el = item.find('dcterms:title', ns)
                about = item.get(f'{{{ns["rdf"]}}}about')
                if title_el is not None and title_el.text == folder_name:
                    return {'title': title_el.text, 'url': about}
            return None
        except Exception:
            return None

    # ── Write: Link Types ─────────────────────────────────────

    def get_link_types(self, project_url: str) -> List[Dict]:
        """Get all available link types for a project.

        Returns list of dicts with 'name' and 'uri' for each link type.
        """
        self._ensure_auth()
        project_area_id = self._extract_project_area_id(project_url)
        project_area_url = f"{self.base_url}/process/project-areas/{project_area_id}"

        import urllib.parse
        encoded_pa = urllib.parse.quote(project_area_url, safe='')

        try:
            resp = self.session.get(
                f"{self.base_url}/linkTypeQuery?projectURL={encoded_pa}",
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            ns_dng = 'http://jazz.net/ns/rm/dng/types#'
            ns_rdfs = 'http://www.w3.org/2000/01/rdf-schema#'

            link_type_uris = []
            for member in root.findall(f'.//{{{ns_rdfs}}}member'):
                lt = member.find(f'{{{ns_dng}}}LinkType')
                if lt is not None:
                    uri = lt.get(f'{{{self._NS_OSLC["rdf"]}}}about', '')
                    if uri:
                        link_type_uris.append(uri)

            # Resolve names for custom link types (project-specific URLs)
            link_types = []
            for uri in link_type_uris:
                name = self._resolve_link_type_name(uri)
                if name:
                    link_types.append({'name': name, 'uri': uri})

            return link_types
        except Exception:
            return []

    def _resolve_link_type_name(self, uri: str) -> str:
        """Resolve a link type URI to its display name"""
        # Standard OSLC RM link types
        standard_names = {
            'http://open-services.net/ns/rm#elaboratedBy': 'Elaborated By',
            'http://open-services.net/ns/rm#elaborates': 'Elaborates',
            'http://open-services.net/ns/rm#specifiedBy': 'Specified By',
            'http://open-services.net/ns/rm#specifies': 'Specifies',
            'http://open-services.net/ns/rm#validatedBy': 'Validated By',
            'http://open-services.net/ns/rm#implementedBy': 'Implemented By',
            'http://open-services.net/ns/rm#affectedBy': 'Affected By',
            'http://open-services.net/ns/rm#trackedBy': 'Tracked By',
            'http://jazz.net/ns/dm/linktypes#derives': 'Derives (Architecture)',
            'http://jazz.net/ns/dm/linktypes#satisfy': 'Satisfies (Architecture)',
            'http://jazz.net/ns/dm/linktypes#refine': 'Refines (Architecture)',
            'http://jazz.net/ns/dm/linktypes#trace': 'Trace (Architecture)',
            'http://www.ibm.com/xmlns/rdm/types/Decomposition': 'Decomposition',
            'http://www.ibm.com/xmlns/rdm/types/Extraction': 'Extraction',
            'http://www.ibm.com/xmlns/rdm/types/Embedding': 'Embedding',
            'http://www.ibm.com/xmlns/rdm/types/SynonymLink': 'Synonym',
            'http://www.ibm.com/xmlns/rdm/types/ArtifactTermReferenceLink': 'Term Reference',
            'http://www.ibm.com/xmlns/rdm/types/Link': 'Link',
            'http://purl.org/dc/terms/references': 'References',
        }

        if uri in standard_names:
            return standard_names[uri]

        # Custom project-specific link types — fetch the name
        if uri.startswith('http'):
            try:
                resp = self.session.get(
                    uri,
                    headers={
                        'Accept': 'application/rdf+xml',
                        'OSLC-Core-Version': '2.0',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    for elem in root.iter():
                        local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                        if local == 'title' and elem.text:
                            return elem.text
            except Exception:
                pass

        return ''

    # ── Write: Requirements ───────────────────────────────────

    def get_artifact_shapes(self, project_url: str) -> List[Dict]:
        """Get all available artifact type shapes for a project.

        Returns list of dicts with 'name' and 'url' for each shape.
        """
        self._ensure_auth()
        try:
            resp = self.session.get(
                project_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            ns = self._NS_OSLC

            shape_urls = []
            for rs in root.findall('.//oslc:resourceShape', ns):
                shape_url = rs.get(f'{{{ns["rdf"]}}}resource', '')
                if shape_url:
                    shape_urls.append(shape_url)

            # Resolve shape names
            shapes = []
            for shape_url in shape_urls:
                try:
                    resp2 = self.session.get(
                        shape_url,
                        headers={'Accept': 'application/rdf+xml'},
                        timeout=15,
                    )
                    if resp2.status_code == 200:
                        root2 = ET.fromstring(resp2.content)
                        for elem in root2.iter():
                            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                            if local == 'title' and elem.text:
                                shapes.append({'name': elem.text, 'url': shape_url})
                                break
                except Exception:
                    continue

            return shapes
        except Exception:
            return []

    def create_requirement(self, project_url: str, title: str, content: str,
                           shape_url: str, folder_url: Optional[str] = None,
                           link_uri: Optional[str] = None,
                           link_target_url: Optional[str] = None) -> Optional[Dict]:
        """Create a requirement in DNG.

        Args:
            project_url: The project's service provider URL
            title: Requirement title (will be prefixed with [AI Generated])
            content: Rich text content as plain text (converted to XHTML)
            shape_url: The artifact type shape URL (e.g., System Requirement)
            folder_url: Optional folder URL to place the artifact in
            link_uri: Optional link type URI (e.g., a Satisfies link type URL)
            link_target_url: Optional target requirement URL to link to

        Returns:
            Dict with 'title' and 'url' of created requirement, or None on failure.
        """
        self._ensure_auth()
        project_area_id = self._extract_project_area_id(project_url)
        project_area_url = f"{self.base_url}/process/project-areas/{project_area_id}"

        import urllib.parse
        encoded_pa = urllib.parse.quote(project_area_url, safe='')
        creation_url = f"{self.base_url}/requirementFactory?projectURL={encoded_pa}"

        # Prefix title with [AI Generated]
        prefixed_title = f"[AI Generated] {title}" if not title.startswith("[AI Generated]") else title

        # Convert plain text content to XHTML
        xhtml_content = self._text_to_xhtml(content)

        # Build folder reference if provided
        folder_ref = ''
        if folder_url:
            folder_ref = f'<nav:parent rdf:resource="{folder_url}"/>'

        # Build link reference if provided
        link_ref = ''
        extra_ns = ''
        if link_uri and link_target_url:
            # Determine if this is a standard OSLC link or a custom project link
            if link_uri.startswith('http://open-services.net/ns/rm#'):
                # Standard OSLC RM link — use as XML element directly
                link_local = link_uri.split('#')[-1]
                link_ref = f'<oslc_rm:{link_local} rdf:resource="{link_target_url}"/>'
            elif link_uri.startswith('http://jazz.net/ns/dm/linktypes#'):
                # Jazz DM link type
                link_local = link_uri.split('#')[-1]
                extra_ns = ' xmlns:dm="http://jazz.net/ns/dm/linktypes#"'
                link_ref = f'<dm:{link_local} rdf:resource="{link_target_url}"/>'
            else:
                # Custom project-specific link type — use the full URI as namespace + local
                # Extract the base URL and the LT_ identifier
                if '/types/LT_' in link_uri:
                    lt_id = link_uri.split('/')[-1]
                    lt_base = link_uri.rsplit('/', 1)[0] + '/'
                    extra_ns = f' xmlns:rm_link="{lt_base}"'
                    link_ref = f'<rm_link:{lt_id} rdf:resource="{link_target_url}"/>'

        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#"
         xmlns:oslc="http://open-services.net/ns/core#"
         xmlns:nav="http://jazz.net/ns/rm/navigation#"{extra_ns}>
  <oslc_rm:Requirement>
    <dcterms:title>{self._escape_xml(prefixed_title)}</dcterms:title>
    <dcterms:description rdf:parseType="Literal">{xhtml_content}</dcterms:description>
    <oslc:instanceShape rdf:resource="{shape_url}"/>
    {folder_ref}
    {link_ref}
  </oslc_rm:Requirement>
</rdf:RDF>'''

        try:
            resp = self.session.post(
                creation_url,
                data=rdf.encode('utf-8'),
                headers={
                    'Content-Type': 'application/rdf+xml',
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code == 201:
                return {
                    'title': prefixed_title,
                    'url': resp.headers.get('Location', ''),
                }
            error_msg = self._extract_oslc_error(resp.text)
            return {'error': f"HTTP {resp.status_code}: {error_msg}" if error_msg else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'error': str(e)}

    def update_requirement(self, requirement_url: str,
                            title: Optional[str] = None,
                            content: Optional[str] = None) -> Optional[Dict]:
        """Update an existing requirement in DNG.

        Uses OSLC optimistic locking: GET to fetch ETag, then PUT with If-Match.

        Args:
            requirement_url: The full URL of the requirement to update
            title: New title (optional — keeps existing if not provided)
            content: New content as plain text (optional — keeps existing if not provided)

        Returns:
            Dict with 'title' and 'url' on success, or {'error': '...'} on failure.
        """
        self._ensure_auth()

        if not title and not content:
            return {'error': 'Nothing to update — provide title and/or content'}

        # Step 1: GET the current requirement to obtain ETag and existing data
        try:
            get_resp = self.session.get(
                requirement_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if get_resp.status_code != 200:
                return {'error': f'Failed to fetch requirement: HTTP {get_resp.status_code}'}

            etag = get_resp.headers.get('ETag', '')
            if not etag:
                return {'error': 'Server did not return an ETag — cannot update safely'}

        except Exception as e:
            return {'error': f'Failed to fetch requirement: {e}'}

        # Step 2: Parse existing RDF to extract current values
        try:
            root = ET.fromstring(get_resp.content)
        except Exception as e:
            return {'error': f'Failed to parse requirement RDF: {e}'}

        # Extract current title and description from the RDF
        current_title = ''
        current_desc = ''
        ns = self._NS_OSLC
        # Try multiple element paths
        for elem in root.iter():
            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if local == 'title' and elem.text and not current_title:
                current_title = elem.text
            elif local == 'description' and not current_desc:
                # Description may contain XML children (XHTML)
                if elem.text:
                    current_desc = elem.text

        # Step 3: Build the updated title and content
        new_title = title if title else current_title
        if content:
            xhtml_content = self._text_to_xhtml(content)
        else:
            xhtml_content = None

        # Step 4: Modify the RDF — replace title and description in the raw XML
        rdf_str = get_resp.content.decode('utf-8')

        if title:
            # Replace dcterms:title content
            import re
            rdf_str = re.sub(
                r'(<dcterms:title[^>]*>)(.*?)(</dcterms:title>)',
                lambda m: f'{m.group(1)}{self._escape_xml(new_title)}{m.group(3)}',
                rdf_str,
                count=1,
                flags=re.DOTALL,
            )

        if xhtml_content:
            # Replace dcterms:description content
            import re
            rdf_str = re.sub(
                r'(<dcterms:description[^>]*>)(.*?)(</dcterms:description>)',
                lambda m: f'{m.group(1)}{xhtml_content}{m.group(3)}',
                rdf_str,
                count=1,
                flags=re.DOTALL,
            )

        # Step 5: PUT the updated RDF back with If-Match
        try:
            put_resp = self.session.put(
                requirement_url,
                data=rdf_str.encode('utf-8'),
                headers={
                    'Content-Type': 'application/rdf+xml',
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'If-Match': etag,
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if put_resp.status_code in [200, 204]:
                return {
                    'title': new_title,
                    'url': requirement_url,
                }
            error_msg = self._extract_oslc_error(put_resp.text)
            return {'error': f'HTTP {put_resp.status_code}: {error_msg}' if error_msg else f'HTTP {put_resp.status_code}'}
        except Exception as e:
            return {'error': f'PUT failed: {e}'}

    def _text_to_xhtml(self, text: str) -> str:
        """Convert plain text to XHTML content for DNG description field"""
        escaped = self._escape_xml(text)
        paragraphs = escaped.split('\n\n')
        xhtml_parts = []
        for para in paragraphs:
            para = para.strip()
            if para:
                # Check if it looks like a bullet list
                lines = para.split('\n')
                if all(line.strip().startswith('- ') or line.strip().startswith('* ') for line in lines if line.strip()):
                    items = ''.join(f'<li>{line.strip().lstrip("- ").lstrip("* ")}</li>' for line in lines if line.strip())
                    xhtml_parts.append(f'<ul>{items}</ul>')
                else:
                    xhtml_parts.append(f'<p>{para}</p>')

        body = ''.join(xhtml_parts)
        return f'<div xmlns="http://www.w3.org/1999/xhtml"><p><strong>[AI Generated by Bob]</strong></p>{body}</div>'

    def _escape_xml(self, text: str) -> str:
        """Escape special XML characters"""
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&apos;'))

    def _extract_oslc_error(self, response_text: str) -> str:
        """Extract error message from an OSLC error response"""
        try:
            root = ET.fromstring(response_text)
            for elem in root.iter():
                local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                if local == 'message' and elem.text:
                    return elem.text.strip()
        except Exception:
            pass
        return ''

    # ── Configuration Management (Baselines) ────────────────

    def _get_component_and_stream(self, project_url: str) -> Optional[Dict]:
        """Discover the component URL and default stream URL for a DNG project.

        Returns dict with 'component_url', 'stream_url', 'stream_title' or None.
        """
        self._ensure_auth()
        try:
            # Step 1: GET the service provider to find the component
            resp = self.session.get(
                project_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return None

            root = ET.fromstring(resp.content)
            ns_config = 'http://open-services.net/ns/config#'
            ns_rdf = self._NS_OSLC['rdf']

            component_url = None
            for elem in root.findall(f'.//{{{ns_config}}}component'):
                component_url = elem.get(f'{{{ns_rdf}}}resource', '')
                if component_url:
                    break

            if not component_url:
                return None

            # Step 2: GET the component's configurations to find the stream
            configs_url = f"{component_url}/configurations"
            resp2 = self.session.get(
                configs_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp2.status_code != 200:
                return None

            root2 = ET.fromstring(resp2.content)
            stream_url = None
            for elem in root2.iter():
                tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                if tag_local == 'member':
                    url = elem.get(f'{{{ns_rdf}}}resource', '')
                    if '/cm/stream/' in url:
                        stream_url = url
                        break

            if not stream_url:
                return None

            # Step 3: GET the stream to get its title
            resp3 = self.session.get(
                stream_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            stream_title = ''
            if resp3.status_code == 200:
                root3 = ET.fromstring(resp3.content)
                for elem in root3.iter():
                    local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                    if local == 'title' and elem.text:
                        stream_title = elem.text.strip()
                        break

            return {
                'component_url': component_url,
                'stream_url': stream_url,
                'stream_title': stream_title,
            }
        except Exception:
            return None

    def create_baseline(self, project_url: str, title: str,
                         description: str = '') -> Optional[Dict]:
        """Create a baseline from the project's current stream.

        Args:
            project_url: The project's service provider URL
            title: Baseline name (will be prefixed with [AI Generated])
            description: Optional baseline description

        Returns:
            Dict with 'title', 'url', 'task_url' on success, or {'error': '...'} on failure.
            Note: Baseline creation is async (202). The 'task_url' can be polled.
        """
        self._ensure_auth()

        config = self._get_component_and_stream(project_url)
        if not config:
            return {'error': 'Could not discover component/stream for this project. '
                    'Configuration management may not be enabled.'}

        prefixed_title = f"[AI Generated] {title}" if not title.startswith("[AI Generated]") else title

        desc_element = ''
        if description:
            desc_element = f'\n    <dcterms:description>{self._escape_xml(description)}</dcterms:description>'

        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_config="http://open-services.net/ns/config#">
  <oslc_config:Baseline rdf:about="">
    <dcterms:title>{self._escape_xml(prefixed_title)}</dcterms:title>{desc_element}
    <oslc_config:component rdf:resource="{config['component_url']}"/>
    <oslc_config:overrides rdf:resource="{config['stream_url']}"/>
  </oslc_config:Baseline>
</rdf:RDF>'''

        baselines_url = f"{config['stream_url']}/baselines"

        try:
            resp = self.session.post(
                baselines_url,
                data=rdf.encode('utf-8'),
                headers={
                    'Content-Type': 'application/rdf+xml',
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code in [200, 201, 202]:
                task_url = resp.headers.get('Location', '')
                return {
                    'title': prefixed_title,
                    'url': task_url,  # For 202, this is the task tracker URL
                    'task_url': task_url if resp.status_code == 202 else '',
                    'stream_title': config['stream_title'],
                }
            error_msg = self._extract_oslc_error(resp.text)
            return {'error': f'HTTP {resp.status_code}: {error_msg}' if error_msg else f'HTTP {resp.status_code}'}
        except Exception as e:
            return {'error': str(e)}

    def list_baselines(self, project_url: str) -> List[Dict]:
        """List all baselines for a project's component.

        Returns list of dicts with 'title', 'url', 'created', 'creator'.
        """
        self._ensure_auth()

        config = self._get_component_and_stream(project_url)
        if not config:
            return []

        baselines_url = f"{config['stream_url']}/baselines"

        try:
            resp = self.session.get(
                baselines_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            ns_config = 'http://open-services.net/ns/config#'
            ns_rdf = self._NS_OSLC['rdf']
            ns_dcterms = self._NS_OSLC['dcterms']

            baselines = []
            for bl in root.findall(f'.//{{{ns_config}}}Baseline'):
                about = bl.get(f'{{{ns_rdf}}}about', '')
                title_el = bl.find(f'{{{ns_dcterms}}}title')
                created_el = bl.find(f'{{{ns_dcterms}}}created')
                creator_el = bl.find(f'{{{ns_dcterms}}}creator')

                baselines.append({
                    'title': title_el.text.strip() if title_el is not None and title_el.text else '',
                    'url': about,
                    'created': created_el.text if created_el is not None else '',
                    'creator': creator_el.get(f'{{{ns_rdf}}}resource', '') if creator_el is not None else '',
                })

            return baselines
        except Exception:
            return []

    # ── EWM (Engineering Workflow Management) ────────────────

    def list_ewm_projects(self) -> List[Dict]:
        """List all EWM projects from the OSLC workitems catalog"""
        self._ensure_auth()
        try:
            resp = self.session.get(
                f"{self._ccm_url}/oslc/workitems/catalog",
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            ns = self._NS_OSLC
            projects = []

            for sp in root.findall('.//oslc:ServiceProvider', ns):
                title_el = sp.find('dcterms:title', ns)
                about = sp.get(f'{{{ns["rdf"]}}}about')
                if title_el is not None and about:
                    # Extract context ID from URL
                    # Pattern: /ccm/oslc/contexts/{context_id}/workitems/services.xml
                    context_id = ''
                    if '/contexts/' in about:
                        parts = about.split('/contexts/')
                        if len(parts) > 1:
                            context_id = parts[1].split('/')[0]
                    projects.append({
                        'title': title_el.text,
                        'url': about,
                        'id': context_id or (about.split('/')[-1] if '/' in about else about),
                        'context_id': context_id,
                    })

            return projects
        except Exception:
            return []

    def _get_ewm_creation_factories(self, service_provider_url: str) -> Dict[str, str]:
        """Get EWM creation factory URLs from a service provider.

        Returns dict mapping work item type to creation URL.
        e.g. {'Task': 'https://...', 'Defect': 'https://...', 'Story': 'https://...'}
        """
        try:
            resp = self.session.get(
                service_provider_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return {}

            root = ET.fromstring(resp.content)
            ns = self._NS_OSLC

            factories = {}
            for cf in root.findall('.//oslc:CreationFactory', ns):
                title_el = cf.find('dcterms:title', ns)
                creation_el = cf.find('oslc:creation', ns)
                if title_el is None or creation_el is None:
                    continue
                factory_title = (title_el.text or '').strip().lower()
                creation_url = creation_el.get(f'{{{ns["rdf"]}}}resource', '')
                if not creation_url:
                    continue

                # Match by title: "Location for creation of {Type} change requests"
                if ' task ' in factory_title:
                    factories['Task'] = creation_url
                elif ' defect ' in factory_title:
                    factories['Defect'] = creation_url
                elif 'story' in factory_title:
                    factories['Story'] = creation_url

            return factories
        except Exception:
            return {}

    def create_ewm_task(self, service_provider_url: str, title: str, description: str = '',
                         requirement_url: Optional[str] = None) -> Optional[Dict]:
        """Create a Task work item in EWM.

        Args:
            service_provider_url: EWM project's service provider URL
            title: Task title (will be prefixed with [AI Generated])
            description: Task description
            requirement_url: Optional DNG requirement URL for calm:implementsRequirement link
        """
        self._ensure_auth()

        factories = self._get_ewm_creation_factories(service_provider_url)
        creation_url = factories.get('Task')
        if not creation_url:
            return {'error': 'No Task creation factory found for this project'}

        prefixed_title = f"[AI Generated] {title}" if not title.startswith("[AI Generated]") else title
        desc_body = f"[AI Generated by Bob]\n\n{description}" if description else "[AI Generated by Bob]"

        # Build cross-tool link if requirement URL provided
        link_element = ''
        calm_ns = ''
        if requirement_url:
            calm_ns = '\n         xmlns:calm="http://jazz.net/xmlns/prod/jazz/calm/1.0/"'
            link_element = f'\n    <calm:implementsRequirement rdf:resource="{requirement_url}"/>'

        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"{calm_ns}>
  <rdf:Description>
    <dcterms:title>{self._escape_xml(prefixed_title)}</dcterms:title>
    <dcterms:description>{self._escape_xml(desc_body)}</dcterms:description>{link_element}
  </rdf:Description>
</rdf:RDF>'''

        try:
            resp = self.session.post(
                creation_url,
                data=rdf.encode('utf-8'),
                headers={
                    'Content-Type': 'application/rdf+xml',
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code in [200, 201]:
                return {
                    'title': prefixed_title,
                    'url': resp.headers.get('Location', ''),
                }
            error_msg = self._extract_oslc_error(resp.text)
            return {'error': f"HTTP {resp.status_code}: {error_msg}" if error_msg else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'error': str(e)}

    # ── ETM (Engineering Test Management) ─────────────────

    def list_etm_projects(self) -> List[Dict]:
        """List all ETM projects from the OSLC QM catalog"""
        self._ensure_auth()
        try:
            resp = self.session.get(
                f"{self._qm_url}/oslc_qm/catalog",
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            ns = self._NS_OSLC
            projects = []

            for sp in root.findall('.//oslc:ServiceProvider', ns):
                title_el = sp.find('dcterms:title', ns)
                about = sp.get(f'{{{ns["rdf"]}}}about')
                if title_el is not None and about:
                    projects.append({
                        'title': title_el.text,
                        'url': about,
                        'id': about.split('/')[-1] if '/' in about else about,
                    })

            return projects
        except Exception:
            return []

    def _get_etm_creation_factories(self, service_provider_url: str) -> Dict[str, str]:
        """Get ETM creation factory URLs from a service provider.

        Returns dict mapping resource type to creation URL.
        e.g. {'TestCase': 'https://...', 'TestResult': 'https://...'}
        """
        try:
            resp = self.session.get(
                service_provider_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return {}

            root = ET.fromstring(resp.content)
            ns = self._NS_OSLC

            factories = {}
            for cf in root.findall('.//oslc:CreationFactory', ns):
                creation_el = cf.find('oslc:creation', ns)
                if creation_el is None:
                    continue
                creation_url = creation_el.get(f'{{{ns["rdf"]}}}resource', '')
                if not creation_url:
                    continue

                for rt in cf.findall('oslc:resourceType', ns):
                    rt_uri = rt.get(f'{{{ns["rdf"]}}}resource', '')
                    if 'TestCase' in rt_uri:
                        factories['TestCase'] = creation_url
                    elif 'TestScript' in rt_uri:
                        factories['TestScript'] = creation_url
                    elif 'TestResult' in rt_uri:
                        factories['TestResult'] = creation_url
                    elif 'TestExecutionRecord' in rt_uri:
                        factories['TestExecutionRecord'] = creation_url
                    elif 'TestPlan' in rt_uri:
                        factories['TestPlan'] = creation_url

            return factories
        except Exception:
            return {}

    def create_test_case(self, service_provider_url: str, title: str,
                          description: str = '',
                          requirement_url: Optional[str] = None) -> Optional[Dict]:
        """Create a Test Case in ETM.

        Args:
            service_provider_url: ETM project's service provider URL
            title: Test case title (will be prefixed with [AI Generated])
            description: Test case description/steps
            requirement_url: Optional DNG requirement URL for oslc_qm:validatesRequirement link
        """
        self._ensure_auth()

        factories = self._get_etm_creation_factories(service_provider_url)
        creation_url = factories.get('TestCase')
        if not creation_url:
            return {'error': 'No TestCase creation factory found for this project'}

        prefixed_title = f"[AI Generated] {title}" if not title.startswith("[AI Generated]") else title
        desc_body = f"[AI Generated by Bob]\n\n{description}" if description else "[AI Generated by Bob]"

        link_element = ''
        if requirement_url:
            link_element = f'\n    <oslc_qm:validatesRequirement rdf:resource="{requirement_url}"/>'

        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_qm="http://open-services.net/ns/qm#">
  <oslc_qm:TestCase>
    <dcterms:title>{self._escape_xml(prefixed_title)}</dcterms:title>
    <dcterms:description>{self._escape_xml(desc_body)}</dcterms:description>{link_element}
  </oslc_qm:TestCase>
</rdf:RDF>'''

        try:
            resp = self.session.post(
                creation_url,
                data=rdf.encode('utf-8'),
                headers={
                    'Content-Type': 'application/rdf+xml',
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code in [200, 201]:
                return {
                    'title': prefixed_title,
                    'url': resp.headers.get('Location', ''),
                }
            error_msg = self._extract_oslc_error(resp.text)
            return {'error': f"HTTP {resp.status_code}: {error_msg}" if error_msg else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'error': str(e)}

    def create_test_result(self, service_provider_url: str, title: str,
                            test_case_url: str, status: str = 'passed') -> Optional[Dict]:
        """Create a Test Result in ETM.

        Args:
            service_provider_url: ETM project's service provider URL
            title: Test result title (will be prefixed with [AI Generated])
            test_case_url: URL of the Test Case this result reports on
            status: Result status — 'passed', 'failed', 'blocked', 'incomplete', or 'error'
        """
        self._ensure_auth()

        factories = self._get_etm_creation_factories(service_provider_url)
        creation_url = factories.get('TestResult')
        if not creation_url:
            return {'error': 'No TestResult creation factory found for this project'}

        prefixed_title = f"[AI Generated] {title}" if not title.startswith("[AI Generated]") else title

        # Map friendly status to OSLC QM status values
        status_map = {
            'passed': 'com.ibm.rqm.execution.common.state.passed',
            'failed': 'com.ibm.rqm.execution.common.state.failed',
            'blocked': 'com.ibm.rqm.execution.common.state.blocked',
            'incomplete': 'com.ibm.rqm.execution.common.state.incomplete',
            'error': 'com.ibm.rqm.execution.common.state.error',
        }
        oslc_status = status_map.get(status.lower(), status)

        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_qm="http://open-services.net/ns/qm#">
  <oslc_qm:TestResult>
    <dcterms:title>{self._escape_xml(prefixed_title)}</dcterms:title>
    <oslc_qm:reportsOnTestCase rdf:resource="{test_case_url}"/>
    <oslc_qm:status>{oslc_status}</oslc_qm:status>
  </oslc_qm:TestResult>
</rdf:RDF>'''

        try:
            resp = self.session.post(
                creation_url,
                data=rdf.encode('utf-8'),
                headers={
                    'Content-Type': 'application/rdf+xml',
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code in [200, 201]:
                return {
                    'title': prefixed_title,
                    'url': resp.headers.get('Location', ''),
                }
            error_msg = self._extract_oslc_error(resp.text)
            return {'error': f"HTTP {resp.status_code}: {error_msg}" if error_msg else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'error': str(e)}

    # ── Export ─────────────────────────────────────────────────

    def export_to_json(self, requirements: List[Dict], filepath: str):
        """Export requirements to JSON file"""
        with open(filepath, 'w') as f:
            json.dump(requirements, f, indent=2)

    def export_to_csv(self, requirements: List[Dict], filepath: str):
        """Export requirements to CSV file"""
        if not requirements:
            return
        fields = ['id', 'title', 'description', 'url', 'format', 'modified', 'created']
        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(requirements)

    def export_to_markdown(self, requirements: List[Dict], filepath: str):
        """Export requirements to Markdown file"""
        with open(filepath, 'w') as f:
            f.write("# Requirements\n\n")
            for req in requirements:
                f.write(f"## {req.get('id', 'N/A')}: {req.get('title', 'Untitled')}\n\n")
                if req.get('description'):
                    f.write(f"{req['description']}\n\n")
                if req.get('modified'):
                    f.write(f"*Last modified: {req['modified']}*\n\n")
                f.write("---\n\n")


# Built by Bob & Brett Scharmett
