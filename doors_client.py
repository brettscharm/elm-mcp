"""
DOORS Next Generation API Client
Built by Brett Scharmett
Connects to IBM DOORS Next via OSLC and Reportable REST APIs

NOT an official IBM product. Use at your own risk.
"""

import os
import re
import csv
import json
import sys
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
from dotenv import load_dotenv
import requests
import time as _time


class ELMSession(requests.Session):
    """`requests.Session` subclass that adds three robustness behaviors
    every existing call site benefits from automatically (no call-site
    changes anywhere in this client):

    1. **Auto-retry on transient errors.** Network failures (Connection,
       Timeout) and 408/423/503 responses get retried with backoff
       [2s, 5s, 10s, give-up]. Other 4xx/5xx pass through unchanged.

    2. **Header-driven re-auth.** Long-lived sessions can have their
       cookie expire mid-flight; Jazz then redirects to a login page
       which the original code parsed as XML, producing baffling
       errors. We now detect Jazz's auth-required headers
       (`X-com-ibm-team-repository-web-auth-msg: authrequired`,
       `X-jazz-web-oauth-url`, etc.) and re-authenticate transparently
       via the client's `authenticate()` method, then replay the
       original request. Recursion-guarded so the auth call itself
       doesn't re-trigger re-auth.

    3. **Configuration-Context translation.** When a caller sets the
       `Configuration-Context` header, we also set the matching query
       parameter — `vvc.configuration` for local-config URLs (paths
       containing `/cm/stream/`, `/cm/baseline/`, or `/cm/changeset/`)
       and `oslc_config.context` for the GCM case. This was a real
       latent bug: hard-coding the header alone errors on local-only-
       config projects in some DNG versions.

    Every behavior is opt-out via env var if it ever causes trouble:
      ELM_MCP_DISABLE_SESSION_RETRY=1
      ELM_MCP_DISABLE_SESSION_REAUTH=1
      ELM_MCP_DISABLE_CONFIG_CTX_XLATE=1
    """

    _RETRY_DELAYS = (2, 5, 10)  # seconds
    _RETRY_STATUSES = (408, 423, 503)
    _AUTH_HEADERS = (
        ("X-com-ibm-team-repository-web-auth-msg", "authrequired"),
        ("X-jazz-web-oauth-url", None),
        ("X-JSA-AUTHORIZATION-REDIRECT", None),
        ("X-JSA-APP-PASSWORD-REDIRECT", None),
    )

    def __init__(self, *args, client_ref=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._client_ref = client_ref
        self._reauth_in_progress = False
        self._retry_disabled = os.environ.get(
            "ELM_MCP_DISABLE_SESSION_RETRY", "0") == "1"
        self._reauth_disabled = os.environ.get(
            "ELM_MCP_DISABLE_SESSION_REAUTH", "0") == "1"
        self._cfg_xlate_disabled = os.environ.get(
            "ELM_MCP_DISABLE_CONFIG_CTX_XLATE", "0") == "1"

    def request(self, method, url, **kwargs):
        # 1. Configuration-Context header → query-param translation
        if not self._cfg_xlate_disabled:
            kwargs = self._translate_config_context(url, kwargs)

        # 2. Retry loop wrapping the actual call
        last_resp = None
        last_exc = None
        max_attempts = 1 if self._retry_disabled else (len(self._RETRY_DELAYS) + 1)
        for attempt in range(max_attempts):
            try:
                resp = super().request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < max_attempts - 1:
                    _time.sleep(self._RETRY_DELAYS[attempt])
                    continue
                raise
            last_resp = resp

            # 3. Auth-required header detection → re-auth and retry once
            if (not self._reauth_disabled
                    and not self._reauth_in_progress
                    and self._needs_reauth(resp)):
                if (self._client_ref
                        and hasattr(self._client_ref, "authenticate")):
                    self._reauth_in_progress = True
                    try:
                        self._client_ref.authenticate()
                    finally:
                        self._reauth_in_progress = False
                    # Retry the original request with the freshened session
                    try:
                        return super().request(method, url, **kwargs)
                    except (requests.ConnectionError, requests.Timeout):
                        return resp  # give up; caller deals

            # Retry on transient HTTP statuses
            if (resp.status_code in self._RETRY_STATUSES
                    and attempt < max_attempts - 1):
                _time.sleep(self._RETRY_DELAYS[attempt])
                continue

            return resp

        if last_exc:
            raise last_exc
        return last_resp

    def _needs_reauth(self, resp) -> bool:
        # 401 is the textbook signal
        if resp.status_code == 401:
            return True
        # Jazz uses headers to redirect to login while returning 200
        for header_name, expected_value in self._AUTH_HEADERS:
            val = resp.headers.get(header_name)
            if val is None:
                continue
            if expected_value is None:
                if val.strip():
                    return True
            elif val.strip().lower() == expected_value:
                return True
        return False

    def _translate_config_context(self, url: str, kwargs: dict) -> dict:
        """If the caller set Configuration-Context as a header, also add
        the matching query param. Don't override an existing param; don't
        mutate the caller's dicts."""
        headers = kwargs.get("headers") or {}
        cfg = headers.get("Configuration-Context", "") if headers else ""
        if not cfg:
            return kwargs

        if any(seg in url for seg in ("/cm/stream/", "/cm/baseline/", "/cm/changeset/")):
            param_name = "vvc.configuration"
        else:
            param_name = "oslc_config.context"

        params = kwargs.get("params") or {}
        if isinstance(params, dict):
            if param_name in params:
                return kwargs
            new_params = dict(params)
            new_params[param_name] = cfg
            new_kwargs = dict(kwargs)
            new_kwargs["params"] = new_params
            return new_kwargs
        # If params is something exotic (list of tuples, etc.), leave it alone
        return kwargs


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

    def __init__(self, base_url: str, username: str, password: str, verify_ssl: bool = True):
        # Normalize: strip trailing slash, extract server root.
        # Users sometimes paste a domain-specific URL (/rm, /ccm, /qm, /gc)
        # or the JTS admin URL (/jts, /jts/admin). Strip any of those so
        # we always derive the bare server root and re-attach each domain
        # path explicitly.
        base_url = base_url.rstrip('/')
        server_root = base_url
        for suffix in ['/jts/admin', '/jts', '/rm/admin', '/rm',
                       '/ccm/admin', '/ccm', '/qm/admin', '/qm',
                       '/gc/admin', '/gc']:
            if base_url.endswith(suffix):
                server_root = base_url[:-len(suffix)]
                break

        # One auth, four domain-specific endpoints.
        self.server_root = server_root
        self.base_url = f"{server_root}/rm"     # DNG (Requirements)
        self.ccm_url = f"{server_root}/ccm"     # EWM (Work items, SCM)
        self.qm_url = f"{server_root}/qm"       # ETM (Test management)
        self.gc_url = f"{server_root}/gc"       # GCM (Global config)

        self.username = username
        self.password = password
        # ELMSession adds retry / re-auth / config-context translation
        # transparently; existing self.session.get/post/put call sites
        # don't change. Pass `client_ref=self` so the session can call
        # authenticate() back on us when it detects auth-required.
        self.session = ELMSession(client_ref=self)
        self.session.verify = verify_ssl
        self._authenticated = False

    @classmethod
    def from_env(cls):
        """Create client from .env file.

        Reads ELM_URL/ELM_USERNAME/ELM_PASSWORD (preferred — the credentials
        cover all five ELM domains: DNG/EWM/ETM/GCM/SCM). Falls back to the
        legacy DOORS_URL/DOORS_USERNAME/DOORS_PASSWORD names so existing
        installations keep working.
        """
        load_dotenv()
        base_url = os.getenv('ELM_URL') or os.getenv('DOORS_URL')
        username = os.getenv('ELM_USERNAME') or os.getenv('DOORS_USERNAME')
        password = os.getenv('ELM_PASSWORD') or os.getenv('DOORS_PASSWORD')
        if not all([base_url, username, password]):
            raise ValueError(
                "Missing environment variables. "
                "Set ELM_URL, ELM_USERNAME, and ELM_PASSWORD in your .env file."
            )
        return cls(base_url, username, password)

    def authenticate(self) -> dict:
        """Authenticate with DOORS Next.

        Tries Basic Auth first, then falls back to Jazz Form-Based Auth
        (j_security_check) if the server uses form-based login.

        Returns:
            dict with 'success' (bool) and 'error' (str, empty on success).
        """
        self.session.headers.update({
            'X-Requested-With': 'XMLHttpRequest',  # Prevents OIDC redirect
        })

        # ── Attempt 1: Basic Auth ────────────────────────────
        try:
            self.session.auth = (self.username, self.password)
            resp = self.session.get(
                f"{self.base_url}/rootservices",
                timeout=self._TIMEOUT,
                allow_redirects=True,
            )
        except requests.exceptions.SSLError:
            if not self.session.verify:
                # Already retried without SSL — give up
                return {'success': False, 'error': f'SSL certificate error for {self.base_url}. The server certificate is not trusted.'}
            # SSL cert issue — common with IBM Cloud demo environments
            # Auto-retry without SSL verification
            self.session.verify = False
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            return self.authenticate()  # Retry with verify=False
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': f'Cannot reach server at {self.base_url}. Check the URL and network.'}
        except requests.exceptions.Timeout:
            return {'success': False, 'error': f'Server at {self.base_url} timed out after {self._TIMEOUT}s.'}
        except Exception as e:
            return {'success': False, 'error': f'Connection error: {e}'}

        # Check if we got valid XML back (real rootservices, not a login page)
        if resp.status_code == 200 and self._is_valid_rootservices(resp.text):
            # rootservices may be public — verify auth by hitting the catalog
            auth_check = self._verify_auth_with_catalog()
            if auth_check is True:
                self._authenticated = True
                return {'success': True, 'error': ''}
            elif auth_check is False:
                return {'success': False, 'error': 'Invalid username or password.'}
            # auth_check is None means catalog check was inconclusive — trust rootservices
            self._authenticated = True
            return {'success': True, 'error': ''}

        # ── Attempt 2: Jazz Form-Based Auth ──────────────────
        # IBM ELM often uses form-based auth via j_security_check
        if self._needs_form_auth(resp):
            return self._form_based_authenticate()

        # ── Auth failed ──────────────────────────────────────
        if resp.status_code == 401:
            return {'success': False, 'error': 'Invalid username or password (HTTP 401).'}
        elif resp.status_code == 403:
            return {'success': False, 'error': 'Access denied (HTTP 403). Check your account permissions.'}
        elif resp.status_code != 200:
            return {'success': False, 'error': f'Server returned HTTP {resp.status_code}. Check the URL.'}
        else:
            return {'success': False, 'error': 'Server returned a login page instead of rootservices. Authentication failed.'}

    def _verify_auth_with_catalog(self):
        """Verify authentication by requesting the OSLC catalog (requires auth).

        Returns:
            True  — auth confirmed working
            False — auth confirmed failing (401/403)
            None  — inconclusive (catalog unavailable, network error, etc.)
        """
        try:
            resp = self.session.get(
                f"{self.base_url}/oslc_rm/catalog",
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
                allow_redirects=True,
            )
            if resp.status_code == 200:
                return True
            if resp.status_code in [401, 403]:
                return False
            if 'j_security_check' in resp.text or 'authfailed' in resp.url.lower():
                return False
            return None  # Inconclusive
        except Exception:
            return None  # Network issue — don't block auth

    def _is_valid_rootservices(self, body: str) -> bool:
        """Check if the response body is valid rootservices XML (not a login page)."""
        # A real rootservices response contains OSLC catalog references
        return ('rootservices' in body.lower() or 'catalogUrl' in body or
                'oslc_rm' in body or 'ServiceProviderCatalog' in body) and \
               'j_security_check' not in body

    def _needs_form_auth(self, resp) -> bool:
        """Check if the server is asking for form-based authentication."""
        body = resp.text.lower()
        return ('j_security_check' in body or
                'authfailed' in resp.url.lower() or
                'form' in body and 'j_username' in body)

    def _form_based_authenticate(self) -> dict:
        """Authenticate using IBM Jazz Form-Based Auth (j_security_check)."""
        # Clear basic auth — form auth uses cookies
        self.session.auth = None

        auth_url = f"{self.server_root}/j_security_check"
        try:
            resp = self.session.post(
                auth_url,
                data={
                    'j_username': self.username,
                    'j_password': self.password,
                },
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                allow_redirects=True,
                timeout=self._TIMEOUT,
            )
        except Exception as e:
            return {'success': False, 'error': f'Form-based auth request failed: {e}'}

        # Check for auth failure indicators
        if 'authfailed' in resp.url.lower():
            return {'success': False, 'error': 'Invalid username or password (form-based auth failed).'}

        # Verify by checking the catalog (requires auth, unlike rootservices)
        auth_check = self._verify_auth_with_catalog()
        if auth_check is True:
            self._authenticated = True
            return {'success': True, 'error': ''}
        elif auth_check is False:
            return {'success': False, 'error': 'Form-based auth failed. Invalid username or password.'}

        # Fallback: check rootservices
        try:
            verify = self.session.get(
                f"{self.base_url}/rootservices",
                timeout=self._TIMEOUT,
            )
            if verify.status_code == 200 and self._is_valid_rootservices(verify.text):
                self._authenticated = True
                return {'success': True, 'error': ''}
        except Exception:
            pass

        return {'success': False, 'error': 'Form-based auth completed but server still not accessible. Check credentials.'}

    def _ensure_auth(self):
        """Ensure authenticated before making requests"""
        if not self._authenticated:
            result = self.authenticate()
            if not result['success']:
                raise ConnectionError(f"Failed to authenticate: {result['error']}")

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

    # ── Search ────────────────────────────────────────────────

    def resolve_requirement_id(self, project_url: str,
                                requirement_id: str) -> Optional[Dict]:
        """Look up a DNG requirement by its short identifier (e.g. '123'
        or 'REQ-123') and return the full URL plus title.

        Modelled after IBM ELM-Python-Client's
        `RM.resolve_reqid_to_core_uri`. Uses OSLC where on the project's
        query capability with `dcterms:identifier`. If a numeric prefix
        like 'REQ-' or 'NFR-' is given, strips it and tries the numeric
        portion (DNG stores identifier as the integer typically).

        Returns: {'id', 'title', 'url'} or None on failure / no match.
        """
        self._ensure_auth()
        if not requirement_id:
            return None
        # Normalize: strip optional prefix (REQ-, NFR-, etc.) → numeric part
        import re as _re
        m = _re.match(r'^[A-Za-z\-_]+(\d+)$', requirement_id.strip())
        numeric = m.group(1) if m else requirement_id.strip()
        candidates = []
        if numeric != requirement_id.strip():
            candidates.append(numeric)
        candidates.append(requirement_id.strip())

        # Discover the OSLC query capability for the project
        query_url = self._get_oslc_query_capability(project_url)
        if not query_url:
            return None

        ns = self._NS_OSLC
        for cand in candidates:
            try:
                params = {
                    # DNG's OSLC query requires every namespace prefix used
                    # in where/select to be DECLARED via oslc.prefix —
                    # otherwise the server 400s with "Undefined namespace
                    # prefix: dcterms". This declaration was missing, which
                    # (together with the wrong query capability) is why
                    # resolve_requirement_id always returned "not found".
                    # Fixed in v0.25.0. Identifier is an integer literal —
                    # no quotes.
                    'oslc.prefix': 'dcterms=<http://purl.org/dc/terms/>',
                    'oslc.where': f'dcterms:identifier={cand}',
                    'oslc.select': 'dcterms:identifier,dcterms:title',
                    'oslc.pageSize': '5',
                }
                resp = self.session.get(
                    query_url,
                    params=params,
                    headers={
                        'Accept': 'application/rdf+xml',
                        'OSLC-Core-Version': '2.0',
                    },
                    timeout=self._TIMEOUT,
                )
                if resp.status_code != 200:
                    continue
                root = ET.fromstring(resp.content)
                for req_el in root.findall('.//oslc_rm:Requirement', ns):
                    about = req_el.get(f'{{{ns["rdf"]}}}about', '')
                    title_el = req_el.find('dcterms:title', ns)
                    id_el = req_el.find('dcterms:identifier', ns)
                    if about:
                        return {
                            'id': (id_el.text if id_el is not None else cand),
                            'title': (title_el.text if title_el is not None else ''),
                            'url': about,
                        }
                # Some servers return Description elements rather than
                # typed Requirement — try that shape too
                for d in root.findall(f'.//{{{ns["rdf"]}}}Description'):
                    about = d.get(f'{{{ns["rdf"]}}}about', '')
                    if not about or '/resources/' not in about:
                        continue
                    title_el = d.find('dcterms:title', ns)
                    id_el = d.find('dcterms:identifier', ns)
                    if id_el is not None and id_el.text and id_el.text.strip() == cand:
                        return {
                            'id': cand,
                            'title': (title_el.text if title_el is not None else ''),
                            'url': about,
                        }
            except Exception:
                continue
        return None

    def _get_oslc_query_capability(self, project_url: str) -> str:
        """Helper: get the OSLC query capability URL for a DNG project's
        Requirement type. Cached internally on first lookup."""
        if not hasattr(self, '_query_cap_cache'):
            self._query_cap_cache = {}
        if project_url in self._query_cap_cache:
            return self._query_cap_cache[project_url]
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
                return ''
            root = ET.fromstring(resp.content)
            ns = self._NS_OSLC
            rm_req_type = 'http://open-services.net/ns/rm#Requirement'
            fallback = ''
            # Find the QueryCapability whose resourceType is the RM
            # Requirement type. The services doc lists MANY capabilities
            # (AttributeType, LinkType, Folder, View, …) and the
            # Requirement one is NOT first — picking the first (the old
            # bug) returned attributeTypeQuery, so resolve_requirement_id
            # and every OSLC attribute query 400'd. Fixed in v0.25.0.
            for qc in root.findall('.//oslc:QueryCapability', ns):
                base_el = qc.find('oslc:queryBase', ns)
                if base_el is None:
                    continue
                base_url = base_el.get(f'{{{ns["rdf"]}}}resource', '')
                if not base_url:
                    continue
                res_types = [
                    e.get(f'{{{ns["rdf"]}}}resource', '')
                    for e in qc.findall('oslc:resourceType', ns)
                ]
                if rm_req_type in res_types:
                    self._query_cap_cache[project_url] = base_url
                    return base_url
                if not fallback:
                    fallback = base_url
            # No Requirement-typed capability found — fall back to the
            # first (better than nothing for older DNG service docs).
            if fallback:
                self._query_cap_cache[project_url] = fallback
                return fallback
        except Exception:
            return ''
        return ''

    def resolve_user(self, identifier: str) -> Optional[Dict]:
        """Resolve a user identifier (URI, username, or display name) to
        a structured user record. Bidirectional: pass either form.

        Modelled after IBM ELM-Python-Client's `Project.user_nametouri_resolver`
        / `user_uritoname_resolver`. Queries the JTS user catalog.

        Returns: {'name', 'username', 'uri', 'email'} or None on no match.
        """
        self._ensure_auth()
        if not identifier:
            return None
        ident = identifier.strip()
        # Detect URI form
        if ident.startswith('http'):
            return self._fetch_user_by_uri(ident)
        # Otherwise treat as a name/username and query the user catalog
        try:
            users_url = f"{self.jts_url}/users"
            resp = self.session.get(
                users_url,
                params={
                    'oslc.where': f'foaf:name="{ident}"',
                    'oslc.select': 'foaf:name,foaf:nick,foaf:mbox',
                    'oslc.pageSize': '5',
                },
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                # Try by username (foaf:nick) instead of display name
                resp = self.session.get(
                    users_url,
                    params={
                        'oslc.where': f'foaf:nick="{ident}"',
                        'oslc.select': 'foaf:name,foaf:nick,foaf:mbox',
                        'oslc.pageSize': '5',
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
            foaf_ns = 'http://xmlns.com/foaf/0.1/'
            ns = self._NS_OSLC
            for d in root.findall(f'.//{{{ns["rdf"]}}}Description'):
                about = d.get(f'{{{ns["rdf"]}}}about', '')
                name_el = d.find(f'{{{foaf_ns}}}name')
                nick_el = d.find(f'{{{foaf_ns}}}nick')
                mbox_el = d.find(f'{{{foaf_ns}}}mbox')
                if about:
                    return {
                        'name': (name_el.text if name_el is not None else ''),
                        'username': (nick_el.text if nick_el is not None else ''),
                        'uri': about,
                        'email': (mbox_el.get(f'{{{ns["rdf"]}}}resource', '')
                                  if mbox_el is not None else ''),
                    }
        except Exception:
            return None
        return None

    def _fetch_user_by_uri(self, uri: str) -> Optional[Dict]:
        """Reverse: dereference a user URI to get name/email."""
        try:
            resp = self.session.get(
                uri,
                headers={'Accept': 'application/rdf+xml',
                         'OSLC-Core-Version': '2.0'},
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            root = ET.fromstring(resp.content)
            foaf_ns = 'http://xmlns.com/foaf/0.1/'
            ns = self._NS_OSLC
            for d in root.findall(f'.//{{{ns["rdf"]}}}Description'):
                name_el = d.find(f'{{{foaf_ns}}}name')
                nick_el = d.find(f'{{{foaf_ns}}}nick')
                mbox_el = d.find(f'{{{foaf_ns}}}mbox')
                return {
                    'name': (name_el.text if name_el is not None else ''),
                    'username': (nick_el.text if nick_el is not None else ''),
                    'uri': uri,
                    'email': (mbox_el.get(f'{{{ns["rdf"]}}}resource', '')
                              if mbox_el is not None else ''),
                }
        except Exception:
            return None
        return None

    def search_requirements(self, project_url: str, query: str,
                             max_results: int = 20) -> List[Dict]:
        """Full-text search across all artifacts in a DNG project.

        Uses the OSLC query capability with oslc.searchTerms (primary),
        then falls back to JFS full-text search if OSLC returns nothing.

        Args:
            project_url: The project's service provider URL
            query: Search terms (e.g., "security", "power backup")
            max_results: Maximum results to return (default 20)

        Returns:
            List of dicts with 'title', 'url', 'summary' for matching artifacts.
        """
        self._ensure_auth()

        # ── Primary: OSLC query with searchTerms ─────────────
        results = self._search_oslc_query(project_url, query, max_results)
        if results:
            return results

        # ── Fallback: JFS full-text search ───────────────────
        return self._search_jfs(project_url, query, max_results)

    def _search_oslc_query(self, project_url: str, query: str,
                            max_results: int = 20) -> List[Dict]:
        """Search using OSLC query capability (oslc.searchTerms).

        DNG returns compact results (URLs only), so we fetch each resource's
        title in a lightweight follow-up request.
        """
        try:
            # Get the RequirementCollection query base from the service provider
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

            query_base = None
            for qc in root.findall('.//oslc:QueryCapability', ns):
                rt_el = qc.find('oslc:resourceType', ns)
                if rt_el is not None and 'RequirementCollection' in rt_el.get(f'{{{ns["rdf"]}}}resource', ''):
                    qb_el = qc.find('oslc:queryBase', ns)
                    if qb_el is not None:
                        query_base = qb_el.get(f'{{{ns["rdf"]}}}resource', '').replace('&amp;', '&')
                    break

            if not query_base:
                return []

            # Execute the OSLC search
            resp2 = self.session.get(
                query_base,
                params={
                    'oslc.searchTerms': f'"{query}"',
                    'oslc.pageSize': str(max_results),
                },
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp2.status_code != 200:
                return []

            root2 = ET.fromstring(resp2.content)

            # Collect resource URLs from rdfs:member elements
            resource_urls = []
            for member in root2.iter():
                local = member.tag.split('}')[-1] if '}' in member.tag else member.tag
                if local in ('Requirement', 'RequirementCollection'):
                    about = member.get(f'{{{ns["rdf"]}}}about', '')
                    if about and '/resources/' in about:
                        resource_urls.append(about)
                        if len(resource_urls) >= max_results:
                            break

            if not resource_urls:
                return []

            # Fetch title for each resource (compact representation)
            results = []
            for url in resource_urls:
                try:
                    r = self.session.get(
                        url,
                        headers={
                            'Accept': 'application/rdf+xml',
                            'OSLC-Core-Version': '2.0',
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                        timeout=15,
                    )
                    if r.status_code != 200:
                        continue
                    rroot = ET.fromstring(r.content)
                    title = ''
                    desc = ''
                    for elem in rroot.iter():
                        el_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                        if el_local == 'title' and elem.text and not title:
                            title = elem.text
                        elif el_local == 'description' and elem.text and not desc:
                            desc = elem.text[:200]
                    if title:
                        results.append({
                            'title': title,
                            'url': url,
                            'summary': desc,
                        })
                except Exception:
                    continue

            return results
        except Exception:
            return []

    def _search_jfs(self, project_url: str, query: str,
                     max_results: int = 20) -> List[Dict]:
        """Fallback search using JFS full-text search endpoint."""
        project_area_id = self._extract_project_area_id(project_url)
        project_area_url = f"{self.base_url}/process/project-areas/{project_area_id}"

        try:
            resp = self.session.get(
                f"{self.base_url}/search",
                params={
                    'q': query,
                    'projectArea': project_area_url,
                },
                headers={
                    'Accept': 'application/xml',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            ns_atom = 'http://www.w3.org/2005/Atom'

            results = []
            for entry in root.findall(f'{{{ns_atom}}}entry'):
                title_el = entry.find(f'{{{ns_atom}}}title')
                link_el = entry.find(f'{{{ns_atom}}}link')
                summary_el = entry.find(f'{{{ns_atom}}}summary')
                content_el = entry.find(f'{{{ns_atom}}}content')

                href = link_el.get('href', '') if link_el is not None else ''
                title_text = title_el.text if title_el is not None else ''

                display_title = title_text
                if title_text.startswith('http'):
                    display_title = title_text.split('/')[-1]

                summary_text = ''
                if summary_el is not None and summary_el.text:
                    summary_text = summary_el.text.strip()
                elif content_el is not None and content_el.text:
                    summary_text = content_el.text.strip()[:200]

                results.append({
                    'title': display_title,
                    'url': href or title_text,
                    'summary': summary_text,
                })

                if len(results) >= max_results:
                    break

            return results
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

    def get_module_requirements(self, module_url: str, config_url: Optional[str] = None,
                                  filter: Optional[Dict] = None) -> List[Dict]:
        """Get requirements from a specific module by its URL.

        Uses the Reportable REST API (publish/resources?moduleURI=...).
        Falls back to OSLC parsing if Reportable namespaces don't match.

        Args:
            module_url: The module's URL
            config_url: Optional configuration context URL (baseline or stream).
                        If provided, reads requirements from that specific configuration.
            filter: Optional dict applied client-side to the returned list. Each
                    key/value pair filters the result. Supports:
                      - Exact match on top-level fields:
                          {"artifact_type": "System Requirement"}
                      - Exact match on custom attributes (project-specific):
                          {"Status": "Approved", "Priority": "High"}
                      - List-of-values (any-of match):
                          {"Status": ["Approved", "Reviewed"]}
                      - Substring match by appending "_contains":
                          {"title_contains": "security"}
                    Match is case-insensitive. Multiple keys are AND'd.
                    Pass None or {} to return all requirements (default).
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
                reqs = []
                for ns_variant in self._NS_VARIANTS:
                    parsed = self._parse_reqs_reportable(root, ns_variant)
                    if parsed:
                        reqs = parsed
                        break

                # Try namespace-agnostic parsing
                if not reqs:
                    reqs = self._parse_reqs_agnostic(root)

                # Try OSLC namespaces as final fallback
                if not reqs:
                    reqs = self._parse_reqs_oslc(root)

                if reqs:
                    return self._apply_filter(reqs, filter) if filter else reqs

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

    def get_requirement_details(self, req_url: str) -> Optional[Dict]:
        """Fetch a single requirement's metadata directly from its URL.

        Returns {'title', 'artifact_type', 'status', 'owner',
        'custom_attributes', 'id'} or None on failure.

        Added in v0.21.1 to support analyze_change_impact's seed
        resolution — without this, the impact tool fell back to using
        the URL as the title, which was ugly.

        Uses the OSLC RM resource endpoint (Accept: application/rdf+xml).
        """
        if not req_url:
            return None
        try:
            self._ensure_auth()
            resp = self.session.get(
                req_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            root = ET.fromstring(resp.content)
            ns = self._NS_OSLC
            # Find the main artifact (Requirement or Description)
            target = None
            for tag in ('.//oslc_rm:Requirement',
                         f'.//{{{ns["rdf"]}}}Description'):
                el = root.find(tag, ns) if 'oslc_rm:' in tag else root.find(tag)
                if el is not None:
                    target = el
                    break
            if target is None:
                return None
            title_el = target.find('dcterms:title', ns)
            ident_el = target.find('dcterms:identifier', ns)
            type_el = target.find('rdm_types:ArtifactFormat', ns) \
                if 'rdm_types' in ns else None
            return {
                'url': req_url,
                'title': (title_el.text or '').strip() if title_el is not None else '',
                'id': (ident_el.text or '').strip() if ident_el is not None else '',
                'artifact_type': '',
                'status': '',
                'owner': '',
                'custom_attributes': {},
            }
        except Exception:
            return None

    def get_requirement_links(self, req_url: str) -> List[Dict]:
        """Fetch outgoing OSLC links from a single requirement.

        Returns list of {'target_url', 'target_title', 'link_type',
        'target_type'} for each link found. Best-effort: parses common
        OSLC RM link predicates (validatedBy, satisfiedBy, elaborates,
        trackedBy, etc.).

        Added in v0.21.1 to enable analyze_change_impact's BFS graph
        traversal. Before this, the impact tool always returned just
        the seed because no client method exposed link discovery.
        """
        if not req_url:
            return []
        try:
            self._ensure_auth()
            resp = self.session.get(
                req_url,
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
            rdf_ns = ns['rdf']
            # Find the main artifact element
            target = None
            for tag_path in ('.//oslc_rm:Requirement',
                              f'.//{{{rdf_ns}}}Description'):
                if 'oslc_rm:' in tag_path:
                    el = root.find(tag_path, ns)
                else:
                    el = root.find(tag_path)
                if el is not None:
                    target = el
                    break
            if target is None:
                return []

            # Map of OSLC link predicates → friendly link type labels.
            # Each predicate's <rdf:resource> attribute gives the target URL.
            link_predicates = [
                ('oslc_rm:validatedBy', 'validatedBy'),
                ('oslc_rm:satisfiedBy', 'satisfiedBy'),
                ('oslc_rm:elaboratedBy', 'elaboratedBy'),
                ('oslc_rm:specifiedBy', 'specifiedBy'),
                ('oslc_rm:trackedBy', 'trackedBy'),
                ('oslc_rm:affectedBy', 'affectedBy'),
                ('jazz_rm:specifies', 'specifies'),
                ('jazz_rm:elaborates', 'elaborates'),
                ('jazz_rm:validates', 'validates'),
                ('jazz_rm:satisfies', 'satisfies'),
                ('jazz_rm:tracksRequirement', 'tracksRequirement'),
                ('dcterms:references', 'references'),
                ('jazz_dm:satisfy', 'satisfy'),
                ('jazz_dm:trace', 'trace'),
                ('jazz_dm:derives', 'derives'),
                ('rm_types:Decomposition', 'decomposition'),
            ]

            link_ns = {
                'oslc_rm': 'http://open-services.net/ns/rm#',
                'jazz_rm': 'http://jazz.net/ns/rm#',
                'jazz_dm': 'http://jazz.net/ns/dm/linktypes#',
                'dcterms': 'http://purl.org/dc/terms/',
                'rm_types': 'http://www.ibm.com/xmlns/rdm/types/',
                'rdf': rdf_ns,
            }

            links: List[Dict] = []
            for pred_qname, label in link_predicates:
                for link_el in target.findall(pred_qname, link_ns):
                    resource = link_el.get(f'{{{rdf_ns}}}resource')
                    if not resource:
                        continue
                    links.append({
                        'target_url': resource,
                        'target_title': '',
                        'link_type': label,
                        'target_type': '',
                    })
            return links
        except Exception:
            return []

    @staticmethod
    def _apply_filter(reqs: List[Dict], filter_dict: Dict) -> List[Dict]:
        """Apply a generic filter dict to a list of requirement dicts.

        See get_module_requirements docstring for supported filter shapes.
        Each requirement dict has top-level fields (title, artifact_type, id,
        description) and a nested 'custom_attributes' dict for project-specific
        attributes (Status, Priority, etc.). The filter walks both.
        """
        if not filter_dict:
            return reqs

        def match_one(req: Dict, key: str, want) -> bool:
            if key.endswith('_contains'):
                base = key[:-len('_contains')]
                actual = (req.get(base)
                          or req.get('custom_attributes', {}).get(base) or '')
                if isinstance(want, list):
                    return any(str(w).lower() in str(actual).lower() for w in want)
                return str(want).lower() in str(actual).lower()
            actual = req.get(key)
            if actual is None:
                actual = req.get('custom_attributes', {}).get(key, '')
            actual_norm = str(actual).strip().lower()

            # Enum-tolerant comparison. get_attribute_definitions reports
            # some enum labels with a 'State' prefix (StateDraft,
            # StateUnderReview) while the artifacts store the bare label
            # (Draft). Strip a leading 'state' so a filter copied from
            # either source matches. Fixed in v0.24.2.
            def _enum_norm(s: str) -> str:
                s = str(s).strip().lower()
                return s[5:] if s.startswith('state') and len(s) > 5 else s

            if isinstance(want, list):
                wants = {str(w).strip().lower() for w in want}
                if actual_norm in wants:
                    return True
                return _enum_norm(actual) in {_enum_norm(w) for w in want}
            if actual_norm == str(want).strip().lower():
                return True
            return _enum_norm(actual) == _enum_norm(want)

        return [r for r in reqs
                if all(match_one(r, k, v) for k, v in filter_dict.items())]

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
                        # For enumeration attributes (Status, Priority,
                        # Stability, …) the Reportable REST API returns BOTH a
                        # numeric code (value="4") and the human label
                        # (literalName="Approved"). Prefer the label: it's what
                        # the user sees in DNG and what they filter by. Without
                        # this the value displays as a raw code ("Status: 4")
                        # and {"Status": "Approved"} filters never match.
                        # Fixed in v0.24.2.
                        literal_name = custom_attr.get(
                            f'{{{ns_attr}}}literalName', '')
                        if literal_name:
                            attr_value = literal_name
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

    # ── Write: Modules ───────────────────────────────────────

    def create_module(self, project_url: str, title: str,
                       description: str = '') -> Optional[Dict]:
        """Create a module (RequirementCollection) in a DNG project.

        Args:
            project_url: The project's service provider URL
            title: Module title            description: Optional module description

        Returns:
            Dict with 'title' and 'url' of created module, or {'error': '...'} on failure.
        """
        self._ensure_auth()
        project_area_id = self._extract_project_area_id(project_url)
        project_area_url = f"{self.base_url}/process/project-areas/{project_area_id}"

        # Find the Module shape
        shapes = self.get_artifact_shapes(project_url)
        module_shape = None
        for s in shapes:
            if s['name'].lower() == 'module':
                module_shape = s['url']
                break
        if not module_shape:
            return {'error': 'No Module artifact type found in this project'}

        clean_title = title.strip()

        desc_xhtml = ''
        if description:
            desc_xhtml = f'<div xmlns="http://www.w3.org/1999/xhtml"><p>{self._escape_xml(description)}</p></div>'

        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#"
         xmlns:oslc="http://open-services.net/ns/core#">
  <oslc_rm:RequirementCollection>
    <dcterms:title>{self._escape_xml(clean_title)}</dcterms:title>
    <dcterms:description rdf:parseType="Literal">{desc_xhtml}</dcterms:description>
    <oslc:instanceShape rdf:resource="{module_shape}"/>
  </oslc_rm:RequirementCollection>
</rdf:RDF>'''

        import urllib.parse
        encoded_pa = urllib.parse.quote(project_area_url, safe='')

        try:
            resp = self.session.post(
                f"{self.base_url}/requirementFactory?projectURL={encoded_pa}",
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
                    'title': clean_title,
                    'url': resp.headers.get('Location', ''),
                }
            error_msg = self._extract_oslc_error(resp.text)
            return {'error': f"HTTP {resp.status_code}: {error_msg}" if error_msg else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'error': str(e)}

    def add_to_module(self, module_url: str, requirement_urls: List[str]) -> Dict:
        """Bind one or more existing requirements to a DNG module.

        TWO-PATH IMPLEMENTATION (v0.5.4+):
          - Primary: DNG Structure API (requires GCM/config-mgmt). Works
            on ELM-Hub-style projects where configuration management is
            on. Pattern: GET module → discover /structure → modify
            childBindings → PUT-with-If-Match → poll task tracker.
          - Fallback: legacy oslc_rm:uses PUT directly to the module
            artifact. This is what older DNG installs and non-config-
            managed projects support. Activated when the Structure API
            indicates "non-GCM project" (no oslc_config:component on
            the module).

        Args:
            module_url: The module artifact URL (.../resources/MD_*).
            requirement_urls: Existing requirement URLs to bind.

        Returns:
            {'added': int, 'module_url': str, 'method': str} on success
            {'error': str, 'module_url': str} on failure.
        """
        self._ensure_auth()
        if not requirement_urls:
            return {'error': 'requirement_urls is empty', 'module_url': module_url}

        # ── Discover the GCM stream we're working in ──────────────
        try:
            mod_resp = self.session.get(
                module_url,
                headers={'Accept': 'application/rdf+xml'},
                timeout=self._TIMEOUT,
            )
            if mod_resp.status_code != 200:
                return {'error': f'Failed to fetch module: HTTP {mod_resp.status_code}',
                        'module_url': module_url}
            comp_match = re.search(
                r'oslc_config:component\s+rdf:resource="([^"]+)"', mod_resp.text)
            component_url = comp_match.group(1) if comp_match else ''

            # OPT-OUT project handling (v0.5.6 fix): when the module RDF
            # doesn't have oslc_config:component directly (because the
            # project has CM disabled / "opt-out"), the IBM
            # ELM-Python-Client discovers the project's auto-created
            # default component + "Initial Stream" via a different
            # path — see the user-shared finding from their
            # ELM-Python-Client deep-dive. The Structure API still
            # works on opt-out projects, you just have to find the
            # synthetic stream a different way.
            if not component_url:
                project_url_for_lookup = self._derive_project_url_from_module(
                    mod_resp.text, module_url)
                synthetic = self._discover_default_component_and_stream(
                    project_url_for_lookup)
                if synthetic:
                    component_url, stream_url = synthetic
                    sys.stderr.write(
                        f"[elm-mcp] add_to_module: opt-out project "
                        f"detected; using default component+stream "
                        f"({component_url}, {stream_url})\n"
                    ) if False else None  # noqa — quiet by default
                else:
                    # Synthesize discovery failed too — try the legacy path
                    # before giving up.
                    fallback = self._add_to_module_legacy(
                        module_url, requirement_urls,
                        initial_rdf=mod_resp.text)
                    if fallback and 'error' not in fallback:
                        fallback['method'] = 'legacy_oslc_rm_uses'
                        return fallback
                    fb_err = (fallback.get('error', 'unknown')
                              if fallback else 'unknown')
                    return {
                        'error': (
                            f'This DNG project does not support '
                            f'programmatic module binding. Tried THREE '
                            f'paths: (1) Structure API with module-level '
                            f'oslc_config:component (no component on the '
                            f'module RDF — likely an opt-out project); '
                            f'(2) Structure API with project-derived '
                            f'default component (could not discover one); '
                            f'(3) legacy oslc_rm:uses PUT (also failed: '
                            f'{fb_err}). Either (a) ask your DNG admin to '
                            f'enable configuration management on the '
                            f'project, or (b) drag the artifacts into the '
                            f'module manually in the DNG UI.'),
                        'module_url': module_url,
                    }
            else:
                # Module RDF had a component reference — use that to find
                # the active stream the standard way.
                cfg_resp = self.session.get(
                    f"{component_url}/configurations",
                    headers={'Accept': 'application/rdf+xml'},
                    timeout=self._TIMEOUT,
                )
                # CRITICAL (v0.5.7): the configurations endpoint returns
                # multiple rdfs:members — typically a STREAM (writable)
                # plus zero-to-many BASELINES (read-only snapshots). Older
                # code grabbed the first match, which on some servers is a
                # baseline. PUTting against a baseline returns HTTP 410
                # Gone, which then makes the structure-URL discovery fail
                # silently. Always prefer the /cm/stream/ URL; fall back
                # to first member only if no stream is present (very rare).
                all_members = re.findall(
                    r'rdfs:member\s+rdf:resource="([^"]+)"', cfg_resp.text)
                stream_url = next(
                    (u for u in all_members if '/cm/stream/' in u), None)
                if not stream_url and all_members:
                    stream_url = all_members[0]
                if not stream_url:
                    return {'error': 'Could not discover active stream for this component',
                            'module_url': module_url}
        except Exception as e:
            return {'error': f'Component/stream discovery failed: {e}',
                    'module_url': module_url}

        struct_headers = {
            'Accept': 'application/rdf+xml',
            'DoorsRP-Request-Type': 'public 2.0',
            'vvc.configuration': stream_url,
        }

        # ── Step 1: GET module with the magic header → discover /structure ─
        try:
            r = self.session.get(module_url, headers=struct_headers,
                                 timeout=self._TIMEOUT)
            struct_match = re.search(
                r'(?:j\.\d+|module|jazz_rm):structure\s+rdf:resource="([^"]+)"',
                r.text,
            )
            if not struct_match:
                # Try a plain /structure URL match as fallback
                struct_match = re.search(
                    r'rdf:resource="(https?://[^"]+/structure)"', r.text)
            if not struct_match:
                return {'error': 'Could not discover module /structure URL '
                                  '(server may not support DoorsRP-Request-Type)',
                        'module_url': module_url}
            structure_url = struct_match.group(1)
        except Exception as e:
            return {'error': f'Module GET failed: {e}', 'module_url': module_url}

        # ── Step 2: GET the structure resource ────────────────────
        try:
            sr = self.session.get(structure_url, headers=struct_headers,
                                  timeout=self._TIMEOUT)
            if sr.status_code != 200:
                return {'error': f'Structure GET failed: HTTP {sr.status_code}',
                        'module_url': module_url}
            etag = sr.headers.get('ETag', '')
            if not etag:
                return {'error': 'Structure GET returned no ETag',
                        'module_url': module_url}
            structure_body = sr.text
        except Exception as e:
            return {'error': f'Structure GET error: {e}', 'module_url': module_url}

        # Idempotency: skip URLs that are already bound
        existing_bound = set(re.findall(
            r'j\.0:boundArtifact\s+rdf:resource="([^"]+)"', structure_body))
        to_add = [u for u in requirement_urls if u and u not in existing_bound]
        if not to_add:
            return {'added': 0, 'module_url': module_url,
                    'note': 'all requirements already bound'}

        # ── Step 3: Build new bindings + splice into structure body ───
        new_bindings = ''
        for i, req_url in enumerate(to_add, start=1):
            binding_id = f"{structure_url}#{i}"
            new_bindings += (
                f'    <j.0:Binding rdf:about="{binding_id}">\n'
                f'      <oslc_config:component rdf:resource="{component_url}"/>\n'
                f'      <j.0:boundArtifact rdf:resource="{req_url}"/>\n'
                f'      <j.0:module rdf:resource="{module_url}"/>\n'
                f'      <j.0:childBindings rdf:resource="http://www.w3.org/1999/02/22-rdf-syntax-ns#nil"/>\n'
                f'    </j.0:Binding>\n'
            )

        nil_pattern = re.compile(
            r'<j\.0:childBindings\s+rdf:resource="[^"]*#nil"\s*/>',
            re.DOTALL,
        )
        if nil_pattern.search(structure_body):
            # Empty module: replace nil with a populated Collection
            new_body = nil_pattern.sub(
                '<j.0:childBindings rdf:parseType="Collection">\n'
                + new_bindings
                + '  </j.0:childBindings>',
                structure_body,
                count=1,
            )
        elif '</j.0:childBindings>' in structure_body:
            # Populated module: insert into existing Collection
            new_body = structure_body.replace(
                '</j.0:childBindings>',
                new_bindings + '</j.0:childBindings>',
                1,
            )
        else:
            return {'error': 'Could not locate childBindings (neither nil nor Collection)',
                    'module_url': module_url}

        # ── Step 4: PUT the structure ─────────────────────────────
        put_headers = dict(struct_headers)
        put_headers['Content-Type'] = 'application/rdf+xml'
        put_headers['If-Match'] = etag
        try:
            pr = self.session.put(structure_url,
                                  data=new_body.encode('utf-8'),
                                  headers=put_headers,
                                  timeout=self._TIMEOUT,
                                  allow_redirects=False)
        except Exception as e:
            return {'error': f'Structure PUT failed: {e}', 'module_url': module_url}

        if pr.status_code != 202:
            err = self._extract_oslc_error(pr.text)
            return {'error': f'Structure PUT HTTP {pr.status_code}: '
                              f'{err or pr.text[:200]}',
                    'module_url': module_url}

        task_url = pr.headers.get('Location')
        if not task_url:
            return {'error': '202 returned but no Location task tracker',
                    'module_url': module_url}

        # ── Step 5: Poll the task tracker ─────────────────────────
        import time as _t
        deadline = _t.time() + 30
        delay = 0.5
        verdict = None
        while _t.time() < deadline:
            try:
                tr = self.session.get(
                    task_url,
                    headers={'Accept': 'application/rdf+xml'},
                    timeout=self._TIMEOUT,
                )
            except Exception as e:
                return {'error': f'Task tracker poll failed: {e}',
                        'module_url': module_url}
            state = re.search(r'oslc_auto:state\s+rdf:resource="([^"]+)"', tr.text)
            verdict_m = re.search(r'oslc_auto:verdict\s+rdf:resource="([^"]+)"', tr.text)
            state_uri = state.group(1) if state else ''
            verdict = verdict_m.group(1) if verdict_m else ''
            if 'inProgress' not in state_uri and 'queued' not in state_uri:
                if 'unavailable' not in verdict:
                    break
            _t.sleep(delay)
            delay = min(delay * 2, 3.0)

        if verdict and 'passed' in verdict:
            return {'added': len(to_add), 'module_url': module_url}

        # Pull the error detail if present
        err_msg = re.search(r'<oslc:message[^>]*>([^<]+)', tr.text)
        return {
            'error': (f'Module update finished with verdict={verdict}. '
                      f'{err_msg.group(1) if err_msg else ""}'.strip()),
            'module_url': module_url,
        }

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

    def _derive_project_url_from_module(self, module_rdf: str,
                                         module_url: str) -> str:
        """From a module's RDF, extract the URL of the DNG project that
        owns it. Tries process:projectArea first, then falls back to
        the URL pattern (modules live under .../resources/MD_*).
        Used by opt-out-project component discovery."""
        try:
            pa_match = re.search(
                r'process:projectArea\s+rdf:resource="([^"]+)"',
                module_rdf,
            )
            if pa_match:
                pa_url = pa_match.group(1)
                # process:projectArea usually points at /process/project-areas/<id>
                # We need the /rm services URL or /rm-projects/<id> for components
                # discovery. Convert /process/project-areas/<id> →
                # /rm/rm-projects/<id> (DNG's component-listing endpoint pattern).
                pa_id_match = re.search(r'/project-areas/([^/?#]+)', pa_url)
                if pa_id_match:
                    return f"{self.base_url}/rm-projects/{pa_id_match.group(1)}"
            # Fallback: try to find the rm-projects URL elsewhere in the RDF
            rm_proj_match = re.search(
                r'(https?://[^"]+/rm/rm-projects/[A-Za-z0-9_\-]+)',
                module_rdf,
            )
            if rm_proj_match:
                return rm_proj_match.group(1)
        except Exception:
            pass
        return ''

    def _discover_default_component_and_stream(
            self, project_url: str) -> Optional[tuple]:
        """For opt-out (CM-disabled) projects, DNG auto-creates a
        single default component with a single 'Initial Stream'
        configuration. The IBM ELM-Python-Client discovers these by
        listing the project's components and picking the first one's
        first configuration. Returns (component_url, stream_url) or
        None if discovery fails (genuinely no programmatic-binding
        path on this server)."""
        if not project_url:
            return None
        try:
            # Step 1: list the project's components.
            # /rm/rm-projects/<id> → returns project metadata including
            # an oslc_config:component link or a "components" feed.
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
            # The first component reference works for opt-out projects
            # (they have exactly one). Pattern matches both direct
            # component refs and component-collection refs.
            comp_match = re.search(
                r'oslc_config:component\s+rdf:resource="([^"]+)"',
                resp.text,
            )
            if not comp_match:
                # Try alternate patterns — older / newer DNG versions
                # use slightly different predicates
                comp_match = re.search(
                    r'(https?://[^"]+/cm/component/[A-Za-z0-9_\-]+)',
                    resp.text,
                )
                if not comp_match:
                    return None
            component_url = (comp_match.group(1)
                             if comp_match.lastindex
                             else comp_match.group(0))

            # Step 2: list the component's configurations and pick
            # the first stream (opt-out projects have one default).
            cfg_resp = self.session.get(
                f"{component_url}/configurations",
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if cfg_resp.status_code != 200:
                return None
            # Look for a Stream or Configuration member first; fall
            # back to any rdfs:member URL.
            stream_match = re.search(
                r'<oslc_config:Stream[^>]+rdf:about="([^"]+)"',
                cfg_resp.text,
            )
            if not stream_match:
                stream_match = re.search(
                    r'rdfs:member\s+rdf:resource="([^"]+)"',
                    cfg_resp.text,
                )
            if not stream_match:
                return None
            stream_url = stream_match.group(1)

            return (component_url, stream_url)
        except Exception:
            return None

    def _add_to_module_legacy(self, module_url: str,
                               requirement_urls: List[str],
                               initial_rdf: Optional[str] = None) -> Dict:
        """Legacy module-binding path — adds `oslc_rm:uses` triples
        directly to the module artifact via PUT-with-If-Match. Used as
        a fallback when the modern Structure API path is unavailable
        (non-GCM / non-config-managed projects).

        This was the original DNG binding mechanism before the Module
        Structure API. On config-managed projects it's been locked
        down; on non-config-managed projects it may still work. v0.5.4
        tries it as a fallback specifically because the user reported
        being stuck on a project where config-mgmt isn't enabled.

        Returns:
            {'added': int, 'module_url': str} on success.
            {'error': str, 'module_url': str} on failure.
        """
        try:
            # Re-fetch the module if we don't already have its body — we
            # need the ETag for the If-Match PUT.
            headers_get = {
                'Accept': 'application/rdf+xml',
                'OSLC-Core-Version': '2.0',
                'X-Requested-With': 'XMLHttpRequest',
            }
            if initial_rdf is None:
                resp = self.session.get(module_url, headers=headers_get,
                                        timeout=self._TIMEOUT)
            else:
                # Re-fetch for ETag (initial_rdf came from a different
                # GET that may have used different headers / no ETag).
                resp = self.session.get(module_url, headers=headers_get,
                                        timeout=self._TIMEOUT)
            if resp.status_code != 200:
                return {
                    'error': (f'Legacy fallback: failed to GET module: '
                              f'HTTP {resp.status_code}'),
                    'module_url': module_url,
                }
            etag = resp.headers.get('ETag', '')
            if not etag:
                return {
                    'error': 'Legacy fallback: module GET returned no ETag',
                    'module_url': module_url,
                }

            rdf_str = resp.content.decode('utf-8')

            # Find which existing requirement URLs are already in the
            # module via oslc_rm:uses triples — skip duplicates.
            existing = set(re.findall(
                r'oslc_rm:uses\s+rdf:resource="([^"]+)"', rdf_str))
            to_add = [u for u in requirement_urls if u not in existing]
            if not to_add:
                return {
                    'added': 0, 'module_url': module_url,
                    'note': 'all requirements already bound (legacy path)',
                }

            # Inject the triples. Find the closing tag of the module
            # description and put new uses triples just before it.
            new_triples = "".join(
                f'\n    <oslc_rm:uses rdf:resource="{u}"/>'
                for u in to_add
            )

            # The RDF might not declare oslc_rm namespace — inject it
            # if missing.
            if 'xmlns:oslc_rm=' not in rdf_str:
                rdf_str = re.sub(
                    r'<rdf:RDF\b',
                    '<rdf:RDF xmlns:oslc_rm="http://open-services.net/ns/rm#"',
                    rdf_str, count=1,
                )

            # Inject before the last </oslc_rm:Requirement> or </rdf:Description>
            # whichever describes this module
            inject_pat = re.compile(
                rf'(rdf:about="{re.escape(module_url)}".*?)(</[A-Za-z0-9_:]+>)',
                re.DOTALL,
            )
            m = inject_pat.search(rdf_str)
            if m:
                rdf_str = (rdf_str[:m.start()]
                           + m.group(1) + new_triples + '\n  '
                           + m.group(2)
                           + rdf_str[m.end():])
            else:
                # Fallback — put before </rdf:RDF>
                rdf_str = rdf_str.replace(
                    '</rdf:RDF>',
                    f'  <rdf:Description rdf:about="{module_url}">'
                    f'{new_triples}\n  </rdf:Description>\n</rdf:RDF>',
                    1,
                )

            put_resp = self.session.put(
                module_url,
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
            if put_resp.status_code in (200, 204):
                return {'added': len(to_add), 'module_url': module_url}
            err = self._extract_oslc_error(put_resp.text)
            return {
                'error': (f'Legacy PUT failed: HTTP {put_resp.status_code}'
                          + (f': {err}' if err else '')),
                'module_url': module_url,
            }
        except Exception as e:
            return {'error': f'Legacy fallback exception: {e}',
                    'module_url': module_url}

    def find_folder(self, project_url: str, folder_name: str) -> Optional[Dict]:
        """Find an existing folder by name anywhere in a project's folder
        tree. Walks recursively — finds folders at any depth.

        Pre-v0.1.15 only searched root + 1 level deep, missing folders
        created under sub-folders (and even folders created by
        create_folder() under the project root because that helper writes
        them under the *root folder*, not the project area).
        """
        self._ensure_auth()
        project_area_url = project_url.replace(
            '/oslc_rm/', '/process/project-areas/'
        ).replace('/services.xml', '')

        # BFS: queue starts with the project area; we expand each parent
        # to its direct children and check titles. visited keeps us out
        # of cycles (shouldn't happen in DNG but defensive).
        visited: set = set()
        queue: List[str] = [project_area_url]
        while queue:
            parent = queue.pop(0)
            if parent in visited:
                continue
            visited.add(parent)

            children = self._list_child_folders(parent)
            for child in children:
                if child.get('title') == folder_name:
                    return child
                child_url = child.get('url')
                if child_url and child_url not in visited:
                    queue.append(child_url)

            # Cap traversal at a sensible depth to avoid pathological
            # cases. 1000 folders visited is way more than any real
            # project.
            if len(visited) > 1000:
                break

        return None

    def _list_child_folders(self, parent_url: str) -> List[Dict]:
        """Return direct children of a parent folder URL (or project
        area URL for root-level folders). Tries both `public_rm:parent`
        (used for project-area-as-parent) and `nav:parent` (used for
        folder-as-parent) since DNG's predicate varies by parent type."""
        ns = self._NS_OSLC
        results: List[Dict] = []
        # Try both predicate names — DNG uses different ones depending
        # on whether the parent is a project area or a folder. We
        # collect from both queries and dedupe by URL.
        for predicate in ('public_rm:parent', 'nav:parent'):
            try:
                resp = self.session.get(
                    f"{self.base_url}/folders",
                    params={
                        'oslc.where': f'{predicate}={parent_url}',
                        'oslc.select': '*',
                        'oslc.pageSize': '200',
                    },
                    headers={
                        'Accept': 'application/rdf+xml',
                        'OSLC-Core-Version': '2.0',
                    },
                    timeout=self._TIMEOUT,
                )
                if resp.status_code != 200:
                    continue
                root = ET.fromstring(resp.content)
                for item in root.findall(f'.//{{{ns["nav"]}}}folder'):
                    title_el = item.find('dcterms:title', ns)
                    about = item.get(f'{{{ns["rdf"]}}}about')
                    if not about:
                        continue
                    title = (title_el.text or '').strip() if title_el is not None else ''
                    results.append({'title': title, 'url': about})
            except Exception:
                continue

        # Dedupe by URL
        seen = set()
        out = []
        for r in results:
            u = r.get('url', '')
            if u and u not in seen:
                seen.add(u)
                out.append(r)
        return out

    def _find_child_folder(self, parent_url: str, folder_name: str) -> Optional[Dict]:
        """Backward-compat shim — kept for any external callers that may
        still reference it. Internally we use _list_child_folders +
        find_folder's BFS now."""
        for child in self._list_child_folders(parent_url):
            if child.get('title') == folder_name:
                return child
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

    # Section headers that don't belong in a requirement body. Acceptance
    # criteria + verification steps live in ETM test cases, not in DNG
    # requirements. Business value + stakeholder needs are project-rationale
    # context, not part of the "shall" statement. We reject content that
    # contains these as section headers — the AI can re-emit the requirement
    # cleanly and put the rest of the content in the right place. Match
    # against headers only (label + colon at start of a line/paragraph), not
    # any mention of the words.
    _BAD_REQ_HEADERS = (
        "acceptance criteria", "success criteria", "business value",
        "stakeholder need", "stakeholder needs", "test steps",
        "pass/fail", "pass / fail", "pass/fail criteria",
        "verification method", "verification:", "how to verify",
        "test procedure", "expected result", "expected results",
    )

    @classmethod
    def _validate_requirement_content(cls, content: str) -> Optional[str]:
        """Return an error message if the requirement body contains
        section headers that belong in test cases / project rationale,
        not in the requirement itself. None if content is clean."""
        if not content:
            return None
        import re as _re
        for header in cls._BAD_REQ_HEADERS:
            # Match the header as a section label: at start of a line or
            # paragraph break, followed by a colon. Case-insensitive.
            pattern = r'(?:^|\n)\s*' + _re.escape(header) + r'\s*:'
            if _re.search(pattern, content, _re.IGNORECASE):
                return (
                    f"Requirement body contains a '{header}' section. That "
                    "doesn't belong in a DNG requirement body — it goes "
                    "elsewhere:\n"
                    "  - 'Acceptance Criteria', 'Test Steps', 'Pass/Fail', "
                    "'Verification', 'Expected Result' → these go in the "
                    "ETM Test Case for this requirement (call create_test_case "
                    "after the requirement is created).\n"
                    "  - 'Business Value', 'Stakeholder Need', 'Success "
                    "Criteria' → these go in a separate Stakeholder/Business "
                    "Requirement that the System Requirement traces to (use "
                    "Step 3g tiered decomposition).\n"
                    "Re-emit this requirement with just the 'shall' statement "
                    "(plus an optional 'Rationale:' line for compliance "
                    "references)."
                )
        return None

    def create_requirement(self, project_url: str, title: str, content: str,
                           shape_url: str, folder_url: Optional[str] = None,
                           link_uri: Optional[str] = None,
                           link_target_url: Optional[str] = None) -> Optional[Dict]:
        """Create a requirement in DNG.

        Args:
            project_url: The project's service provider URL
            title: Requirement title
            content: Rich text content (plain text or Markdown — converted
                to XHTML). Validated against _BAD_REQ_HEADERS — content
                with embedded acceptance-criteria / business-value /
                stakeholder-needs / verification sections is rejected so
                those concerns end up in the right artifact (test cases /
                stakeholder reqs / business reqs).
            shape_url: The artifact type shape URL (e.g., System Requirement)
            folder_url: Optional folder URL to place the artifact in
            link_uri: Optional link type URI (e.g., a Satisfies link type URL)
            link_target_url: Optional target requirement URL to link to

        Returns:
            Dict with 'title' and 'url' of created requirement, or
            {'error': ...} on failure (including content validation rejection).
        """
        # Reject mis-shaped requirements before they hit DNG.
        validation_error = self._validate_requirement_content(content)
        if validation_error:
            return {'error': validation_error, 'rejected_for_content_shape': True}

        self._ensure_auth()
        project_area_id = self._extract_project_area_id(project_url)
        project_area_url = f"{self.base_url}/process/project-areas/{project_area_id}"

        import urllib.parse
        encoded_pa = urllib.parse.quote(project_area_url, safe='')
        creation_url = f"{self.base_url}/requirementFactory?projectURL={encoded_pa}"

        clean_title = title.strip()

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

        # DNG stores the rich-text body in jazz_rm:primaryText (what users see
        # and edit in the DNG rich-text editor). dcterms:description is only a
        # short-summary field — putting the body there leaves Primary Text
        # blank, which is the bug the user hit.
        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_rm="http://open-services.net/ns/rm#"
         xmlns:oslc="http://open-services.net/ns/core#"
         xmlns:nav="http://jazz.net/ns/rm/navigation#"
         xmlns:jazz_rm="http://jazz.net/ns/rm#"{extra_ns}>
  <oslc_rm:Requirement>
    <dcterms:title>{self._escape_xml(clean_title)}</dcterms:title>
    <dcterms:description rdf:parseType="Literal"></dcterms:description>
    <jazz_rm:primaryText rdf:parseType="Literal">{xhtml_content}</jazz_rm:primaryText>
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
                    'title': clean_title,
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

        # Reject mis-shaped content same as create_requirement does.
        if content:
            validation_error = self._validate_requirement_content(content)
            if validation_error:
                return {'error': validation_error, 'rejected_for_content_shape': True}

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
        """Convert input text to XHTML for DNG's jazz_rm:primaryText field.

        Accepts three input shapes (LLM picks whichever is easiest):
          1. Raw XHTML — if the text starts with '<' and parses as XML, it's
             passed through verbatim, wrapped in an XHTML namespace div.
             Best for tables / images / complex layouts the LLM hand-builds.
          2. Markdown — if the `markdown` library is available, headings,
             tables, images, lists, links, bold/italic, and code blocks all
             work. Tables use the `tables` extension; raw HTML passes through.
          3. Plain text — paragraphs split on blank lines; lines starting
             with '- ' or '* ' become bulleted lists.

        DNG's jazz_rm:primaryText is parseType="Literal" — strict XML, not
        HTML. So we use only the 5 XML entities (&amp; &lt; &gt; &quot;
        &apos;) and literal Unicode for everything else (±, °, etc.).
        """
        if not text:
            text = ''
        stripped = text.strip()

        # Path 1: raw XHTML pass-through
        if stripped.startswith('<'):
            inner = stripped
            # If they wrapped it in <div xmlns="...xhtml">, take the inner.
            import re as _re
            m = _re.match(r'^<div\s+xmlns="http://www\.w3\.org/1999/xhtml"[^>]*>(.*)</div>\s*$', inner, _re.DOTALL)
            if m:
                inner = m.group(1)
            return (
                '<div xmlns="http://www.w3.org/1999/xhtml">'
                f'{inner}'
                '</div>'
            )

        # Path 2: Markdown via the `markdown` library if installed
        try:
            import markdown  # type: ignore
            html = markdown.markdown(
                text,
                extensions=['tables', 'fenced_code', 'sane_lists'],
                output_format='xhtml',
            )
            # markdown emits HTML entities for &, <, > already escaped in
            # text content. Tables/images/lists are real elements.
            return (
                '<div xmlns="http://www.w3.org/1999/xhtml">'
                f'{html}'
                '</div>'
            )
        except ImportError:
            pass

        # Path 3: plain text fallback (original behavior)
        escaped = self._escape_xml(text)
        paragraphs = escaped.split('\n\n')
        xhtml_parts = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            lines = para.split('\n')
            if all(
                line.strip().startswith('- ') or line.strip().startswith('* ')
                for line in lines if line.strip()
            ):
                items = ''.join(
                    f'<li>{line.strip().lstrip("- ").lstrip("* ")}</li>'
                    for line in lines if line.strip()
                )
                xhtml_parts.append(f'<ul>{items}</ul>')
            else:
                xhtml_parts.append(f'<p>{para}</p>')

        body = ''.join(xhtml_parts)
        return (
            '<div xmlns="http://www.w3.org/1999/xhtml">'
            f'{body}'
            '</div>'
        )

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
            title: Baseline name            description: Optional baseline description

        Returns:
            Dict with 'title', 'url', 'task_url' on success, or {'error': '...'} on failure.
            Note: Baseline creation is async (202). The 'task_url' can be polled.
        """
        self._ensure_auth()

        config = self._get_component_and_stream(project_url)
        if not config:
            return {'error': 'Could not discover component/stream for this project. '
                    'Configuration management may not be enabled.'}

        clean_title = title.strip()

        desc_element = ''
        if description:
            desc_element = f'\n    <dcterms:description>{self._escape_xml(description)}</dcterms:description>'

        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_config="http://open-services.net/ns/config#">
  <oslc_config:Baseline rdf:about="">
    <dcterms:title>{self._escape_xml(clean_title)}</dcterms:title>{desc_element}
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
                    'title': clean_title,
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
                f"{self.ccm_url}/oslc/workitems/catalog",
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

    def get_ewm_workitem_types(self, service_provider_url: str) -> List[Dict]:
        """Get ALL work item types available in an EWM project.

        Public method for discovering what types of work items can be
        created in a given EWM project — Epic, Capability, Story, Task,
        Defect, Bug, Issue, Engineering Task, etc. — whatever the
        project's process configuration exposes.

        Args:
            service_provider_url: EWM project's service provider URL
                (from list_ewm_projects → 'url' field)

        Returns:
            List of {'name': str, 'creation_url': str, 'shape_url': str}
            sorted by name. The 'name' is what the EWM project actually
            calls the type (e.g. 'Epic'), suitable to surface to the user
            as their list of options. The 'creation_url' is what
            create_ewm_task / create_defect-style POSTs need.
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
                return []

            root = ET.fromstring(resp.content)
            ns = self._NS_OSLC

            results = []
            seen_names = set()
            for cf in root.findall('.//oslc:CreationFactory', ns):
                title_el = cf.find('dcterms:title', ns)
                creation_el = cf.find('oslc:creation', ns)
                if title_el is None or creation_el is None:
                    continue

                raw_title = (title_el.text or '').strip()
                creation_url = creation_el.get(f'{{{ns["rdf"]}}}resource', '')
                if not creation_url or not raw_title:
                    continue

                # Extract the type name from the factory title.
                # Common patterns:
                #   "Location for creation of <Type> change requests"
                #   "<Type> creation factory"
                #   just "<Type>"
                # If neither pattern matches AND the title looks like a
                # generic factory (no specific type embedded), skip it —
                # those are catch-alls that confuse the user when we
                # surface them as type options.
                import re as _re
                name = None
                m = _re.match(
                    r'^Location for creation of\s+(.+?)\s+change\s+requests?$',
                    raw_title,
                    _re.IGNORECASE,
                )
                if m:
                    name = m.group(1).strip()
                else:
                    m = _re.match(
                        r'^(.+?)\s+creation\s+factory$',
                        raw_title,
                        _re.IGNORECASE,
                    )
                    if m:
                        name = m.group(1).strip()

                if name is None:
                    # No recognizable wrapper — accept the title as-is
                    # only if it looks like a real type (no "creation",
                    # no "factory", no "change requests"). Otherwise it's
                    # a generic catch-all factory; skip.
                    lowered = raw_title.lower()
                    if any(skip in lowered for skip in
                           ('creation', 'factory', 'change request')):
                        continue
                    name = raw_title

                # Title-case ONLY if the whole name is lower; preserve
                # mixed-case names like "PI Objective" untouched.
                if name and name == name.lower():
                    name = name.title()

                # Dedupe by name (some projects expose the same type via
                # multiple factories — e.g. one for default, one for a
                # specific category).
                if name in seen_names:
                    continue
                seen_names.add(name)

                shape_el = cf.find('oslc:resourceShape', ns)
                shape_url = (shape_el.get(f'{{{ns["rdf"]}}}resource', '')
                             if shape_el is not None else '')

                results.append({
                    'name': name,
                    'creation_url': creation_url,
                    'shape_url': shape_url,
                })

            results.sort(key=lambda x: x['name'].lower())
            return results
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
            title: Task title            description: Task description
            requirement_url: Optional DNG requirement URL for calm:implementsRequirement link
        """
        self._ensure_auth()

        factories = self._get_ewm_creation_factories(service_provider_url)
        creation_url = factories.get('Task')
        if not creation_url:
            return {'error': 'No Task creation factory found for this project'}

        clean_title = title.strip()
        desc_body = description or ""

        # Build cross-tool link if requirement URL provided.
        # Note on the predicate: calm:implementsRequirement
        # (http://open-services.net/xmlns/prod/jazz/calm/1.0/implementsRequirement)
        # is the one IBM publishes as the canonical CALM predicate, but EWM
        # silently DROPS it on POST — verified by probe/22_ewm_link_variants.
        # The predicate that actually persists is oslc_cm:implementsRequirement
        # (http://open-services.net/ns/cm#implementsRequirement). Confirmed
        # against the live server: stored as both a direct triple and a
        # reified statement.
        link_element = ''
        link_ns = ''
        if requirement_url:
            link_ns = '\n         xmlns:oslc_cm="http://open-services.net/ns/cm#"'
            link_element = f'\n    <oslc_cm:implementsRequirement rdf:resource="{requirement_url}"/>'

        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"{link_ns}>
  <rdf:Description>
    <dcterms:title>{self._escape_xml(clean_title)}</dcterms:title>
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
                task_url = resp.headers.get('Location', '')
                result = {
                    'title': clean_title,
                    'url': task_url,
                }
                # Bidirectional link write — DNG only renders inbound links
                # in its UI when the inverse triple is explicitly stored ON
                # the requirement. The forward link from EWM (oslc_cm:
                # implementsRequirement) makes the EWM work item show the
                # requirement, but doesn't make the requirement show the
                # task. Write oslc_rm:trackedBy back onto the requirement so
                # DNG's "Links" panel renders it.
                if requirement_url and task_url:
                    backlink_result = self.create_link(
                        source_url=requirement_url,
                        link_type_uri='http://open-services.net/ns/rm#trackedBy',
                        target_url=task_url,
                    )
                    if backlink_result and 'error' in backlink_result:
                        result['backlink_warning'] = (
                            f"Forward link (EWM→DNG) succeeded; back-link "
                            f"(DNG→EWM) failed: {backlink_result['error']}. "
                            f"The work item shows the requirement, but the "
                            f"requirement may not show the work item in "
                            f"DNG's Links panel."
                        )
                return result
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
                f"{self.qm_url}/oslc_qm/catalog",
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

    def _get_etm_query_capabilities(self, service_provider_url: str) -> Dict[str, str]:
        """Discover query capability URLs per ETM resource type.

        Returns dict like {'TestCase': '<url>', 'TestPlan': '<url>',
        'TestExecutionRecord': '<url>', 'TestResult': '<url>'}.
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
            caps: Dict[str, str] = {}
            for qc in root.findall('.//oslc:QueryCapability', ns):
                base_el = qc.find('oslc:queryBase', ns)
                if base_el is None:
                    continue
                base_url = base_el.get(f'{{{ns["rdf"]}}}resource', '')
                if not base_url:
                    continue
                for rt in qc.findall('oslc:resourceType', ns):
                    rt_uri = rt.get(f'{{{ns["rdf"]}}}resource', '')
                    if 'TestCase' in rt_uri:
                        caps['TestCase'] = base_url
                    elif 'TestPlan' in rt_uri:
                        caps['TestPlan'] = base_url
                    elif 'TestExecutionRecord' in rt_uri:
                        caps['TestExecutionRecord'] = base_url
                    elif 'TestResult' in rt_uri:
                        caps['TestResult'] = base_url
                    elif 'TestScript' in rt_uri:
                        caps['TestScript'] = base_url
            return caps
        except Exception:
            return {}

    def list_test_cases(self, service_provider_url: str,
                         where: Optional[str] = None,
                         max_results: int = 50) -> List[Dict]:
        """List test cases in an ETM project. Optional `where` is an
        OSLC where clause (e.g. `dcterms:title="Login flow"`).

        Returns list of {'url', 'title', 'identifier', 'state'}.
        """
        return self._etm_query('TestCase', service_provider_url,
                                where, max_results)

    def list_test_plans(self, service_provider_url: str,
                         where: Optional[str] = None,
                         max_results: int = 50) -> List[Dict]:
        """List test plans in an ETM project."""
        return self._etm_query('TestPlan', service_provider_url,
                                where, max_results)

    def list_test_execution_records(self, service_provider_url: str,
                                     where: Optional[str] = None,
                                     max_results: int = 50) -> List[Dict]:
        """List test execution records (TERs) in an ETM project."""
        return self._etm_query('TestExecutionRecord', service_provider_url,
                                where, max_results)

    def _etm_query(self, kind: str, service_provider_url: str,
                    where: Optional[str], max_results: int) -> List[Dict]:
        """Generic ETM OSLC query helper. kind is TestCase / TestPlan /
        TestExecutionRecord / TestResult / TestScript."""
        self._ensure_auth()
        caps = self._get_etm_query_capabilities(service_provider_url)
        query_url = caps.get(kind, '')
        if not query_url:
            return []
        params = {
            'oslc.select': 'dcterms:title,dcterms:identifier,oslc:status',
            'oslc.pageSize': str(max(1, min(max_results, 200))),
        }
        if where:
            params['oslc.where'] = where
        try:
            resp = self.session.get(
                query_url,
                params=params,
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
            qm_ns = 'http://open-services.net/ns/qm#'
            results: List[Dict] = []
            # Look for typed elements first (TestCase, TestPlan, etc.)
            typed_qname = f'{{{qm_ns}}}{kind}'
            elements = list(root.iter(typed_qname))
            if not elements:
                # Fallback: any rdf:Description with the right URI shape
                elements = [d for d in root.findall(f'.//{{{ns["rdf"]}}}Description')
                            if kind.lower() in (d.get(f'{{{ns["rdf"]}}}about', '') or '').lower()]
            for el in elements[:max_results]:
                about = el.get(f'{{{ns["rdf"]}}}about', '')
                # Filter out the OSLC query capability / catalog URL
                # itself — it carries query params or ends right at the
                # `Versioned*` capability path. Real test artifacts have a
                # specific resource id after that path.
                # Fixed in v0.21.1 — was returning empty-title catalog
                # entries as if they were test artifacts.
                if not about or '?' in about:
                    continue
                if about.rstrip('/').endswith(
                    f'com.ibm.rqm.planning.Versioned{kind}'
                ):
                    continue
                title_el = el.find('dcterms:title', ns)
                id_el = el.find('dcterms:identifier', ns)
                status_el = el.find('oslc:status', ns)
                title_val = ''
                if title_el is not None and title_el.text:
                    title_val = title_el.text.strip()
                results.append({
                    'url': about,
                    'title': title_val,
                    'identifier': (id_el.text or '').strip() if id_el is not None else '',
                    'state': (status_el.text or '').strip() if status_el is not None else '',
                })
            return results
        except Exception:
            return []

    def create_test_plan(self, service_provider_url: str, title: str,
                          description: str = '') -> Optional[Dict]:
        """Create a Test Plan in ETM. Test plans hold strategy, scope,
        and reference one or more test cases. Use for organizing test
        execution at the release / sprint / feature level."""
        self._ensure_auth()
        factories = self._get_etm_creation_factories(service_provider_url)
        creation_url = factories.get('TestPlan')
        if not creation_url:
            return {'error': 'No TestPlan creation factory found for this project'}
        clean_title = title.strip()
        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_qm="http://open-services.net/ns/qm#">
  <oslc_qm:TestPlan>
    <dcterms:title>{self._escape_xml(clean_title)}</dcterms:title>
    <dcterms:description>{self._escape_xml(description or "")}</dcterms:description>
  </oslc_qm:TestPlan>
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
                    'title': clean_title,
                    'url': resp.headers.get('Location', ''),
                }
            err = self._extract_oslc_error(resp.text)
            return {'error': f"HTTP {resp.status_code}: {err}" if err else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'error': str(e)}

    def create_test_execution_record(self, service_provider_url: str,
                                      title: str,
                                      test_case_url: str,
                                      description: str = '') -> Optional[Dict]:
        """Create a Test Execution Record (TER) in ETM. A TER is an
        instance of running a particular test case — typically created
        per release/iteration. Test results then attach to the TER."""
        self._ensure_auth()
        factories = self._get_etm_creation_factories(service_provider_url)
        creation_url = factories.get('TestExecutionRecord')
        if not creation_url:
            return {'error': 'No TestExecutionRecord creation factory found'}
        clean_title = title.strip()
        tc_link = ""
        if test_case_url:
            tc_link = (
                f'\n    <oslc_qm:runsTestCase '
                f'rdf:resource="{test_case_url}"/>'
            )
        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_qm="http://open-services.net/ns/qm#">
  <oslc_qm:TestExecutionRecord>
    <dcterms:title>{self._escape_xml(clean_title)}</dcterms:title>
    <dcterms:description>{self._escape_xml(description or "")}</dcterms:description>{tc_link}
  </oslc_qm:TestExecutionRecord>
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
                    'title': clean_title,
                    'url': resp.headers.get('Location', ''),
                    'test_case': test_case_url,
                }
            err = self._extract_oslc_error(resp.text)
            return {'error': f"HTTP {resp.status_code}: {err}" if err else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'error': str(e)}

    def create_test_case(self, service_provider_url: str, title: str,
                          description: str = '',
                          requirement_url: Optional[str] = None) -> Optional[Dict]:
        """Create a Test Case in ETM.

        Args:
            service_provider_url: ETM project's service provider URL
            title: Test case title            description: Test case description/steps
            requirement_url: Optional DNG requirement URL for oslc_qm:validatesRequirement link
        """
        self._ensure_auth()

        factories = self._get_etm_creation_factories(service_provider_url)
        creation_url = factories.get('TestCase')
        if not creation_url:
            return {'error': 'No TestCase creation factory found for this project'}

        clean_title = title.strip()
        desc_body = description or ""

        link_element = ''
        if requirement_url:
            link_element = f'\n    <oslc_qm:validatesRequirement rdf:resource="{requirement_url}"/>'

        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_qm="http://open-services.net/ns/qm#">
  <oslc_qm:TestCase>
    <dcterms:title>{self._escape_xml(clean_title)}</dcterms:title>
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
                test_case_url = resp.headers.get('Location', '')
                result = {
                    'title': clean_title,
                    'url': test_case_url,
                }
                # Bidirectional link write — DNG only renders inbound links
                # in its UI when the inverse triple is explicitly stored ON
                # the requirement. Write oslc_rm:validatedBy back onto the
                # requirement so DNG's "Links" panel renders the test case.
                if requirement_url and test_case_url:
                    backlink_result = self.create_link(
                        source_url=requirement_url,
                        link_type_uri='http://open-services.net/ns/rm#validatedBy',
                        target_url=test_case_url,
                    )
                    if backlink_result and 'error' in backlink_result:
                        result['backlink_warning'] = (
                            f"Forward link (ETM→DNG) succeeded; back-link "
                            f"(DNG→ETM) failed: {backlink_result['error']}. "
                            f"The test case shows the requirement, but the "
                            f"requirement may not show the test case in "
                            f"DNG's Links panel."
                        )
                return result
            error_msg = self._extract_oslc_error(resp.text)
            return {'error': f"HTTP {resp.status_code}: {error_msg}" if error_msg else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'error': str(e)}

    def create_test_script(self, service_provider_url: str, title: str,
                            steps: str = '',
                            test_case_url: Optional[str] = None) -> Optional[Dict]:
        """Create a Test Script in ETM.

        A Test Script is the actual test procedure (the steps the tester
        runs). Test Cases are typically the *what* (one verifiable behavior);
        Test Scripts are the *how* (the procedure). One Test Case can
        execute multiple Test Scripts; one Test Script can be referenced
        by multiple Test Cases.

        Args:
            service_provider_url: ETM project's service provider URL
            title: Test script title
            steps: Test procedure body (steps, expected results, pass/fail
                conditions). Stored in dcterms:description as plain text;
                ETM also accepts XHTML for richer formatting.
            test_case_url: Optional Test Case URL to link this script to via
                oslc_qm:executionInstructions (so the test case knows which
                script to run).
        """
        self._ensure_auth()

        factories = self._get_etm_creation_factories(service_provider_url)
        creation_url = factories.get('TestScript')
        if not creation_url:
            return {'error': 'No TestScript creation factory found for this project'}

        clean_title = title.strip()
        desc_body = steps or ""

        link_element = ''
        if test_case_url:
            link_element = f'\n    <oslc_qm:executesTestScript rdf:resource="{test_case_url}"/>'

        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_qm="http://open-services.net/ns/qm#">
  <oslc_qm:TestScript>
    <dcterms:title>{self._escape_xml(clean_title)}</dcterms:title>
    <dcterms:description>{self._escape_xml(desc_body)}</dcterms:description>{link_element}
  </oslc_qm:TestScript>
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
                return {'title': clean_title, 'url': resp.headers.get('Location', '')}
            error_msg = self._extract_oslc_error(resp.text)
            return {'error': f"HTTP {resp.status_code}: {error_msg}" if error_msg else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'error': str(e)}

    def create_test_result(self, service_provider_url: str, title: str,
                            test_case_url: str, status: str = 'passed') -> Optional[Dict]:
        """Create a Test Result in ETM.

        Args:
            service_provider_url: ETM project's service provider URL
            title: Test result title            test_case_url: URL of the Test Case this result reports on
            status: Result status — 'passed', 'failed', 'blocked', 'incomplete', or 'error'
        """
        self._ensure_auth()

        factories = self._get_etm_creation_factories(service_provider_url)
        creation_url = factories.get('TestResult')
        if not creation_url:
            return {'error': 'No TestResult creation factory found for this project'}

        clean_title = title.strip()

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
    <dcterms:title>{self._escape_xml(clean_title)}</dcterms:title>
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
                    'title': clean_title,
                    'url': resp.headers.get('Location', ''),
                }
            error_msg = self._extract_oslc_error(resp.text)
            return {'error': f"HTTP {resp.status_code}: {error_msg}" if error_msg else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'error': str(e)}

    # ── GCM (Global Configuration Management) ─────────────

    def list_global_configurations(self) -> List[Dict]:
        """List all global configurations (streams and baselines) from GCM.

        Returns a list of dicts with 'title', 'url', 'id' for each configuration.
        These span all ELM apps (DNG, EWM, ETM).
        """
        self._ensure_auth()
        try:
            resp = self.session.get(
                f"{self.gc_url}/configuration",
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
            ns_rdf = self._NS_OSLC['rdf']
            ns_dc = self._NS_OSLC['dcterms']

            configs = []
            for desc in root.findall(f'{{{ns_rdf}}}Description'):
                about = desc.get(f'{{{ns_rdf}}}about', '')
                if '/gc/configuration/' not in about:
                    continue
                title_el = desc.find(f'{{{ns_dc}}}title')
                title = title_el.text.strip() if title_el is not None and title_el.text else ''
                config_id = about.split('/')[-1]
                configs.append({
                    'title': title,
                    'url': about,
                    'id': config_id,
                })

            return configs
        except Exception:
            return []

    def list_global_components(self) -> List[Dict]:
        """List all components from GCM across DNG, EWM, and ETM.

        Returns a list of dicts with 'title', 'url', 'id', 'configurations_url',
        'project_area', 'created', 'modified'.
        """
        self._ensure_auth()
        try:
            resp = self.session.get(
                f"{self.gc_url}/oslc-query/components",
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
            ns_rdf = self._NS_OSLC['rdf']
            ns_dc = self._NS_OSLC['dcterms']
            ns_config = 'http://open-services.net/ns/config#'
            ns_process = 'http://jazz.net/ns/process#'

            components = []
            for desc in root.findall(f'{{{ns_rdf}}}Description'):
                about = desc.get(f'{{{ns_rdf}}}about', '')
                if '/gc/component/' not in about:
                    continue

                # Check it's actually a Component type
                is_component = False
                for type_el in desc.findall(f'{{{ns_rdf}}}type'):
                    type_uri = type_el.get(f'{{{ns_rdf}}}resource', '')
                    if 'Component' in type_uri:
                        is_component = True
                        break
                if not is_component:
                    continue

                title_el = desc.find(f'{{{ns_dc}}}title')
                title = title_el.text.strip() if title_el is not None and title_el.text else ''
                id_el = desc.find(f'{{{ns_dc}}}identifier')
                configs_el = desc.find(f'{{{ns_config}}}configurations')
                pa_el = desc.find(f'{{{ns_process}}}projectArea')
                created_el = desc.find(f'{{{ns_dc}}}created')
                modified_el = desc.find(f'{{{ns_dc}}}modified')

                components.append({
                    'title': title,
                    'url': about,
                    'id': id_el.text if id_el is not None else about.split('/')[-1],
                    'configurations_url': configs_el.get(f'{{{ns_rdf}}}resource', '') if configs_el is not None else '',
                    'project_area': pa_el.get(f'{{{ns_rdf}}}resource', '') if pa_el is not None else '',
                    'created': created_el.text if created_el is not None else '',
                    'modified': modified_el.text if modified_el is not None else '',
                })

            return components
        except Exception:
            return []

    def get_global_config_details(self, config_url: str) -> Optional[Dict]:
        """Get details for a specific global configuration.

        Returns dict with 'title', 'url', 'type' (stream/baseline),
        'contributions' (list of component configs that participate).
        """
        self._ensure_auth()
        try:
            resp = self.session.get(
                config_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return None

            root = ET.fromstring(resp.content)
            ns_rdf = self._NS_OSLC['rdf']
            ns_dc = self._NS_OSLC['dcterms']
            ns_config = 'http://open-services.net/ns/config#'

            title = ''
            config_type = 'configuration'
            contributions = []
            component_url = ''

            for desc in root.findall(f'{{{ns_rdf}}}Description') + [root]:
                about = desc.get(f'{{{ns_rdf}}}about', '')

                title_el = desc.find(f'{{{ns_dc}}}title')
                if title_el is not None and title_el.text:
                    title = title_el.text.strip()

                # Determine type (stream vs baseline)
                for type_el in desc.findall(f'{{{ns_rdf}}}type'):
                    type_uri = type_el.get(f'{{{ns_rdf}}}resource', '')
                    if 'Stream' in type_uri:
                        config_type = 'stream'
                    elif 'Baseline' in type_uri:
                        config_type = 'baseline'

                # Get component
                comp_el = desc.find(f'{{{ns_config}}}component')
                if comp_el is not None:
                    component_url = comp_el.get(f'{{{ns_rdf}}}resource', '')

                # Get contributions (local configs from DNG/EWM/ETM)
                for contrib in desc.findall(f'{{{ns_config}}}contribution'):
                    contrib_url = contrib.get(f'{{{ns_rdf}}}resource', '')
                    if contrib_url:
                        # Determine which app this contribution is from
                        app = 'unknown'
                        if '/rm/' in contrib_url:
                            app = 'DNG'
                        elif '/ccm/' in contrib_url:
                            app = 'EWM'
                        elif '/qm/' in contrib_url:
                            app = 'ETM'
                        contributions.append({'url': contrib_url, 'app': app})

            return {
                'title': title,
                'url': config_url,
                'type': config_type,
                'component': component_url,
                'contributions': contributions,
            }
        except Exception:
            return None

    # ── DNG: arbitrary attribute updates ───────────────────────

    def get_attribute_definitions(self, project_url: str) -> List[Dict]:
        """Get all attribute property definitions from a DNG project's
        artifact shapes.

        Walks `oslc:resourceShape` URIs from the project's services.xml,
        fetches each shape, then for each `oslc:Property` collects:
          - name (`oslc:name` or `dcterms:title`)
          - title (display label)
          - predicate_uri (`oslc:propertyDefinition`)
          - value_type (`oslc:valueType`)
          - allowed_values: list of {label, uri} when an `oslc:AllowedValues`
            block is present (enum-valued attrs).

        Returns a deduped list (one entry per predicate URI).
        Used by `update_requirement_attributes` to translate a friendly
        attribute name → predicate URI.
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
        except Exception:
            return []

        ns_oslc = 'http://open-services.net/ns/core#'
        ns_dct = 'http://purl.org/dc/terms/'
        ns_rdf = self._NS_OSLC['rdf']

        seen = set()
        defs: List[Dict] = []

        for shape_url in shape_urls:
            try:
                resp2 = self.session.get(
                    shape_url,
                    headers={'Accept': 'application/rdf+xml',
                             'OSLC-Core-Version': '2.0'},
                    timeout=15,
                )
                if resp2.status_code != 200:
                    continue
                shape_root = ET.fromstring(resp2.content)
            except Exception:
                continue

            # Walk every oslc:Property element
            for prop in shape_root.iter(f'{{{ns_oslc}}}Property'):
                pred_el = prop.find(f'{{{ns_oslc}}}propertyDefinition')
                if pred_el is None:
                    continue
                predicate_uri = pred_el.get(f'{{{ns_rdf}}}resource', '')
                if not predicate_uri or predicate_uri in seen:
                    continue
                seen.add(predicate_uri)

                # Title / display name
                title_el = prop.find(f'{{{ns_dct}}}title')
                title = title_el.text.strip() if title_el is not None and title_el.text else ''
                name_el = prop.find(f'{{{ns_oslc}}}name')
                name_text = (name_el.text.strip() if name_el is not None and name_el.text else '')
                if name_text:
                    name = name_text
                elif title:
                    name = title
                else:
                    name = predicate_uri.split('#')[-1].split('/')[-1]

                # Value type
                vt_el = prop.find(f'{{{ns_oslc}}}valueType')
                value_type = vt_el.get(f'{{{ns_rdf}}}resource', '') if vt_el is not None else ''

                # Allowed values (inline form)
                allowed: List[Dict] = []
                av_block = prop.find(f'{{{ns_oslc}}}allowedValues')
                if av_block is not None:
                    for av in av_block.iter(f'{{{ns_oslc}}}allowedValue'):
                        uri = av.get(f'{{{ns_rdf}}}resource', '')
                        if uri:
                            allowed.append({'label': uri.split('#')[-1].split('/')[-1], 'uri': uri})

                defs.append({
                    'name': name,
                    'title': title or name,
                    'predicate_uri': predicate_uri,
                    'value_type': value_type,
                    'allowed_values': allowed,
                })

        return defs

    def update_requirement_attributes(self, requirement_url: str,
                                      attributes: Dict[str, object]) -> Dict:
        """Update arbitrary DNG attributes on a requirement.

        `attributes` is a dict mapping either:
          - a human-readable attribute name ("Priority", "Stability"), OR
          - the full predicate URI (e.g. "http://jazz.net/ns/sse#stability"),
        to the new value.

        Values may be:
          - a string literal (sets a literal triple),
          - an http(s) URI (treated as a resource reference),
          - for enum-valued attributes, the human-readable label of an
            allowed value (e.g. "High") — resolved via the project's
            attribute definitions.

        Mirrors `update_requirement`: GET-with-ETag → modify RDF →
        PUT-with-If-Match.

        Returns {'title', 'url', 'updated': [list of keys applied]} on
        success, or {'error': ...}.
        """
        self._ensure_auth()
        if not attributes:
            return {'error': 'No attributes supplied.'}

        # ── Step 1: GET with ETag ───────────────────────────────
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
                return {'error': 'Server returned no ETag — refusing to PUT.'}
        except Exception as e:
            return {'error': f'Failed to fetch requirement: {e}'}

        rdf_str = get_resp.content.decode('utf-8')

        # ── Step 2: Resolve project_url & attribute definitions ──
        # Extract serviceProvider from the artifact's RDF
        project_url = None
        try:
            arrt = ET.fromstring(get_resp.content)
            for elem in arrt.iter():
                local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                if local == 'serviceProvider':
                    project_url = elem.get(f'{{{self._NS_OSLC["rdf"]}}}resource', '')
                    if project_url:
                        break
        except Exception:
            pass

        attr_defs: List[Dict] = []
        if project_url:
            attr_defs = self.get_attribute_definitions(project_url)

        def _find_def(key: str) -> Optional[Dict]:
            if not attr_defs:
                return None
            # Direct predicate URI match
            for d in attr_defs:
                if d['predicate_uri'] == key:
                    return d
            # Case-insensitive name / title match
            kl = key.lower()
            for d in attr_defs:
                if d['name'].lower() == kl or d['title'].lower() == kl:
                    return d
            # Local-name match
            for d in attr_defs:
                local = d['predicate_uri'].split('#')[-1].split('/')[-1]
                if local.lower() == kl:
                    return d
            return None

        # ── Step 3: Apply each attribute ───────────────────────
        import re
        applied: List[str] = []
        # We will inject new triples just before the closing
        # </rdf:Description> of the artifact's main description.
        # First find the closing tag for the rdf:Description that contains
        # rdf:about == requirement_url.
        for key, raw_value in attributes.items():
            d = _find_def(key) if not key.startswith('http') else _find_def(key)
            predicate_uri = d['predicate_uri'] if d else (key if key.startswith('http') else None)
            if not predicate_uri:
                # Fall back: use as predicate if it looks URI-ish, else skip.
                continue

            # Resolve enum value if necessary
            value = raw_value
            if d and d.get('allowed_values'):
                if isinstance(value, str) and not value.startswith('http'):
                    for av in d['allowed_values']:
                        if av['label'].lower() == value.lower() or av['uri'].endswith('#' + value):
                            value = av['uri']
                            break

            # Decide literal vs resource
            is_resource = isinstance(value, str) and value.startswith('http')

            # Build a qname: pred:local. Use a generated namespace per predicate.
            if '#' in predicate_uri:
                base_ns, local = predicate_uri.rsplit('#', 1)
                base_ns += '#'
            else:
                base_ns, local = predicate_uri.rsplit('/', 1)
                base_ns += '/'
            # Sanitize local name for XML
            qname_local = re.sub(r'[^A-Za-z0-9_]', '_', local)
            ns_prefix = f'attr_{abs(hash(base_ns)) % 10000}'

            # If predicate already exists, replace the triple's value
            #   pattern matches:  <(prefix:|ns:)local ...>...</...>  OR self-closing
            # We'll just match any prefix:local with that local — DNG returns
            # known prefixes in the artifact RDF.
            existing_pat = re.compile(
                rf'<([A-Za-z][A-Za-z0-9_]*):{re.escape(local)}\b[^>]*?(/>|>.*?</\1:{re.escape(local)}>)',
                re.DOTALL,
            )
            existing = existing_pat.search(rdf_str)
            if existing:
                # Replace its content
                if is_resource:
                    new_triple = f'<{existing.group(1)}:{local} rdf:resource="{value}"/>'
                else:
                    safe = self._escape_xml(str(value))
                    new_triple = f'<{existing.group(1)}:{local}>{safe}</{existing.group(1)}:{local}>'
                rdf_str = rdf_str[:existing.start()] + new_triple + rdf_str[existing.end():]
                applied.append(key)
                continue

            # Otherwise inject a new triple. We need the namespace declared.
            # If a prefix isn't declared, declare one on the rdf:RDF tag.
            ns_declared = (f'xmlns:{ns_prefix}="{base_ns}"' in rdf_str
                           or f'="{base_ns}"' in rdf_str)
            if not ns_declared:
                rdf_str = re.sub(
                    r'(<rdf:RDF\b[^>]*)',
                    rf'\1 xmlns:{ns_prefix}="{base_ns}"',
                    rdf_str,
                    count=1,
                )
                prefix_to_use = ns_prefix
            else:
                # Find the existing prefix that points at base_ns
                m = re.search(rf'xmlns:([A-Za-z][A-Za-z0-9_]*)="{re.escape(base_ns)}"', rdf_str)
                prefix_to_use = m.group(1) if m else ns_prefix

            if is_resource:
                triple = f'\n    <{prefix_to_use}:{local} rdf:resource="{value}"/>'
            else:
                safe = self._escape_xml(str(value))
                triple = f'\n    <{prefix_to_use}:{local}>{safe}</{prefix_to_use}:{local}>'

            # Inject before </rdf:Description> of the requirement (the one
            # whose rdf:about matches requirement_url).
            inject_pat = re.compile(
                rf'(<rdf:Description\b[^>]*rdf:about="{re.escape(requirement_url)}"[^>]*>)(.*?)(</rdf:Description>)',
                re.DOTALL,
            )
            inj = inject_pat.search(rdf_str)
            if inj:
                rdf_str = rdf_str[:inj.start()] + inj.group(1) + inj.group(2) + triple + '\n  ' + inj.group(3) + rdf_str[inj.end():]
            else:
                # Fallback: inject before any closing rdf:Description
                rdf_str = rdf_str.replace('</rdf:Description>', triple + '\n  </rdf:Description>', 1)
            applied.append(key)

        # ── Step 4: PUT with If-Match ───────────────────────────
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
                    'url': requirement_url,
                    'updated': applied,
                }
            error_msg = self._extract_oslc_error(put_resp.text)
            return {'error': f'HTTP {put_resp.status_code}: {error_msg}' if error_msg
                    else f'HTTP {put_resp.status_code}'}
        except Exception as e:
            return {'error': f'PUT failed: {e}'}

    # ── EWM: arbitrary work-item updates ───────────────────────

    def update_work_item(self, workitem_url: str,
                         fields: Dict[str, object]) -> Dict:
        """Update an EWM/CCM work item with the given fields.

        `fields` keys may be:
          - friendly names ("title", "description", "state"),
          - or full predicate URIs (e.g. "http://purl.org/dc/terms/title").

        Friendly aliases map to:
          title       -> dcterms:title
          description -> dcterms:description
          state       -> rtc_cm:state (must be a state URI)
          owner       -> dcterms:contributor
          severity    -> oslc_cmx:severity (must be a severity URI)
          priority    -> oslc_cmx:priority (must be a priority URI)
          subject     -> dcterms:subject

        Uses GET-with-ETag → PUT-with-If-Match.
        """
        self._ensure_auth()
        if not fields:
            return {'error': 'No fields supplied.'}

        ALIASES = {
            'title': 'http://purl.org/dc/terms/title',
            'description': 'http://purl.org/dc/terms/description',
            'state': 'http://jazz.net/xmlns/prod/jazz/rtc/cm/1.0/state',
            'owner': 'http://purl.org/dc/terms/contributor',
            'severity': 'http://open-services.net/ns/cm-x#severity',
            'priority': 'http://open-services.net/ns/cm-x#priority',
            'subject': 'http://purl.org/dc/terms/subject',
            'filedAgainst': 'http://jazz.net/xmlns/prod/jazz/rtc/cm/1.0/filedAgainst',
        }

        try:
            get_resp = self.session.get(
                workitem_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if get_resp.status_code != 200:
                return {'error': f'Failed to fetch work item: HTTP {get_resp.status_code}'}
            etag = get_resp.headers.get('ETag', '')
            if not etag:
                return {'error': 'Server returned no ETag — refusing to PUT.'}
        except Exception as e:
            return {'error': f'Failed to fetch work item: {e}'}

        rdf_str = get_resp.content.decode('utf-8')

        import re
        applied: List[str] = []

        for key, raw_value in fields.items():
            predicate_uri = ALIASES.get(key.lower(), key if key.startswith('http') else None)
            if not predicate_uri:
                continue
            value = raw_value
            is_resource = isinstance(value, str) and value.startswith('http')

            if '#' in predicate_uri:
                base_ns, local = predicate_uri.rsplit('#', 1)
                base_ns += '#'
            else:
                base_ns, local = predicate_uri.rsplit('/', 1)
                base_ns += '/'

            existing_pat = re.compile(
                rf'<([A-Za-z][A-Za-z0-9_]*):{re.escape(local)}\b[^>]*?(/>|>.*?</\1:{re.escape(local)}>)',
                re.DOTALL,
            )
            existing = existing_pat.search(rdf_str)
            if existing:
                if is_resource:
                    new_triple = f'<{existing.group(1)}:{local} rdf:resource="{value}"/>'
                else:
                    safe = self._escape_xml(str(value))
                    new_triple = f'<{existing.group(1)}:{local}>{safe}</{existing.group(1)}:{local}>'
                rdf_str = rdf_str[:existing.start()] + new_triple + rdf_str[existing.end():]
                applied.append(key)
                continue

            # Inject new triple
            m = re.search(rf'xmlns:([A-Za-z][A-Za-z0-9_]*)="{re.escape(base_ns)}"', rdf_str)
            if m:
                prefix = m.group(1)
            else:
                prefix = f'attr_{abs(hash(base_ns)) % 10000}'
                rdf_str = re.sub(
                    r'(<rdf:RDF\b[^>]*)',
                    rf'\1 xmlns:{prefix}="{base_ns}"',
                    rdf_str,
                    count=1,
                )

            if is_resource:
                triple = f'\n    <{prefix}:{local} rdf:resource="{value}"/>'
            else:
                safe = self._escape_xml(str(value))
                triple = f'\n    <{prefix}:{local}>{safe}</{prefix}:{local}>'

            rdf_str = rdf_str.replace('</rdf:Description>', triple + '\n  </rdf:Description>', 1)
            applied.append(key)

        try:
            put_resp = self.session.put(
                workitem_url,
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
                return {'url': workitem_url, 'updated': applied}
            error_msg = self._extract_oslc_error(put_resp.text)
            return {'error': f'HTTP {put_resp.status_code}: {error_msg}' if error_msg
                    else f'HTTP {put_resp.status_code}'}
        except Exception as e:
            return {'error': f'PUT failed: {e}'}

    def get_workflow_states(self, workitem_url: str) -> Dict:
        """List the workflow states available for a given EWM work item.

        Returns the work item's CURRENT state plus the full list of
        states defined in its workflow (Task, Defect, Story, etc. each
        have their own workflow). Useful for `transition_work_item`
        callers — pick a target state from this list rather than
        guessing 'Resolved' vs 'Done' vs 'Closed' (varies per project).

        Returns:
            {'current_state': {'name', 'uri'}, 'available_states': [{'name', 'uri'}, ...]}
            or {'error': '...'} on failure.
        """
        self._ensure_auth()
        try:
            get_resp = self.session.get(
                workitem_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if get_resp.status_code != 200:
                return {'error': f'Failed to fetch work item: HTTP {get_resp.status_code}'}
        except Exception as e:
            return {'error': f'Failed to fetch work item: {e}'}

        import re as _re
        rdf_str = get_resp.content.decode('utf-8')
        sm = _re.search(
            r'<[A-Za-z0-9_]+:state\s+rdf:resource="([^"]+/workflows/[^"]+)"\s*/>',
            rdf_str,
        )
        if not sm:
            return {'error': 'Could not find rtc_cm:state on the work item.'}
        current_state_uri = sm.group(1)

        base_match = _re.match(r'(.+/workflows/[^/]+)/states/([^/]+)/[^/]+$',
                               current_state_uri)
        if not base_match:
            return {'error': f'Could not parse workflow base from: {current_state_uri}'}
        wf_base = base_match.group(1)
        wf_id = base_match.group(2)
        states_list_url = f"{wf_base}/states/{wf_id}"

        try:
            states_resp = self.session.get(
                states_list_url,
                headers={'Accept': 'application/rdf+xml', 'OSLC-Core-Version': '2.0'},
                timeout=self._TIMEOUT,
            )
            if states_resp.status_code != 200:
                return {'error': f'Failed to fetch workflow states: HTTP {states_resp.status_code}'}
            sroot = ET.fromstring(states_resp.content)
        except Exception as e:
            return {'error': f'Failed to fetch workflow states: {e}'}

        ns = self._NS_OSLC
        available: List[Dict] = []
        current_name = ""
        rdfs_label_qname = '{http://www.w3.org/2000/01/rdf-schema#}label'
        # Collect every state in the workflow
        for s in sroot.iter(f'{{{ns["rdf"]}}}Description'):
            about = s.get(f'{{{ns["rdf"]}}}about', '')
            title_el = s.find('dcterms:title', ns)
            label_el = s.find(rdfs_label_qname)
            name = ""
            if title_el is not None and title_el.text:
                name = title_el.text.strip()
            elif label_el is not None and label_el.text:
                name = label_el.text.strip()
            if about and name:
                available.append({'name': name, 'uri': about})
                if about == current_state_uri:
                    current_name = name

        # Dedupe (some servers return states twice via different rdf:type entries)
        seen_uris = set()
        deduped = []
        for st in available:
            if st['uri'] not in seen_uris:
                seen_uris.add(st['uri'])
                deduped.append(st)

        return {
            'workflow_id': wf_id,
            'current_state': {'name': current_name, 'uri': current_state_uri},
            'available_states': sorted(deduped, key=lambda s: s['name'].lower()),
        }

    def transition_work_item(self, workitem_url: str, target_state: str) -> Dict:
        """Transition an EWM work item to the named state.

        EWM enforces workflow gates: a plain PUT that swaps `rtc_cm:state`
        is silently ignored. The supported path is to PUT with the
        `?_action=<actionId>` query parameter, where actionId is one of the
        workflow's named actions (e.g. `...action.startWorking`).

        Strategy:
          1. GET the WI; record current state URI and ETag.
          2. GET the action collection (`/ccm/oslc/workflows/<paId>/actions/<wfId>`)
             and the state collection (`/ccm/oslc/workflows/<paId>/states/<wfId>`).
          3. Match `target_state` against state titles/identifiers; record
             the target state URI.
          4. Pick the best-matching action — by checking which action's
             local-name aligns with the target state's local name (e.g.
             `state.inDevelopment` ↔ `action.startWorking`). Failing that,
             try each action in order until one succeeds.
          5. PUT the modified RDF (with new `rtc_cm:state`) to
             `<workitem_url>?_action=<actionId>` with `If-Match`.

        Returns {'url', 'state', 'action'} on success.
        """
        self._ensure_auth()
        try:
            get_resp = self.session.get(
                workitem_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if get_resp.status_code != 200:
                return {'error': f'Failed to fetch work item: HTTP {get_resp.status_code}'}
            etag = get_resp.headers.get('ETag', '')
        except Exception as e:
            return {'error': f'Failed to fetch work item: {e}'}

        import re
        rdf_str = get_resp.content.decode('utf-8')
        sm = re.search(
            r'<[A-Za-z0-9_]+:state\s+rdf:resource="([^"]+/workflows/[^"]+)"\s*/>',
            rdf_str,
        )
        if not sm:
            return {'error': 'Could not find rtc_cm:state on the work item.'}
        current_state_uri = sm.group(1)

        base_match = re.match(r'(.+/workflows/[^/]+)/states/([^/]+)/[^/]+$', current_state_uri)
        if not base_match:
            return {'error': f'Could not parse workflow base from: {current_state_uri}'}
        wf_base = base_match.group(1)        # .../workflows/<paId>
        wf_id = base_match.group(2)          # e.g. com.ibm.team.workitem.taskWorkflow
        states_list_url = f"{wf_base}/states/{wf_id}"
        actions_list_url = f"{wf_base}/actions/{wf_id}"

        try:
            states_resp = self.session.get(
                states_list_url,
                headers={'Accept': 'application/rdf+xml', 'OSLC-Core-Version': '2.0'},
                timeout=self._TIMEOUT,
            )
            if states_resp.status_code != 200:
                return {'error': f'Failed to fetch states: HTTP {states_resp.status_code}'}
            sroot = ET.fromstring(states_resp.content)

            actions_resp = self.session.get(
                actions_list_url,
                headers={'Accept': 'application/rdf+xml', 'OSLC-Core-Version': '2.0'},
                timeout=self._TIMEOUT,
            )
            aroot = ET.fromstring(actions_resp.content) if actions_resp.status_code == 200 else None
        except Exception as e:
            return {'error': f'Failed to fetch workflow metadata: {e}'}

        ns_dct = 'http://purl.org/dc/terms/'
        ns_rdf = self._NS_OSLC['rdf']
        ns_rdfs = 'http://www.w3.org/2000/01/rdf-schema#'

        # Find target state URI
        target_lower = target_state.lower()
        target_state_uri = None
        target_state_local = ''
        for desc in sroot.findall(f'{{{ns_rdf}}}Description'):
            about = desc.get(f'{{{ns_rdf}}}about', '')
            if '/states/' not in about or about == states_list_url:
                continue
            title_el = desc.find(f'{{{ns_dct}}}title')
            ident_el = desc.find(f'{{{ns_dct}}}identifier')
            t = (title_el.text or '').strip() if title_el is not None else ''
            i = (ident_el.text or '').strip() if ident_el is not None else ''
            if (t.lower() == target_lower
                or i.lower() == target_lower
                or i.lower().endswith('.' + target_lower.replace(' ', ''))
                or target_lower in t.lower()):
                target_state_uri = about
                target_state_local = (i or about.rsplit('/', 1)[-1]).rsplit('.', 1)[-1].lower()
                break

        if not target_state_uri:
            return {'error': f"State '{target_state}' not found in this workflow."}

        # Build candidate action list (URIs)
        action_uris: List[str] = []
        if aroot is not None:
            for member in aroot.iter(f'{{{ns_rdfs}}}member'):
                u = member.get(f'{{{ns_rdf}}}resource', '')
                if u:
                    action_uris.append(u)

        # Heuristic ranking: prefer action whose local-suffix is "similar"
        # to the target state's local name (e.g. inDevelopment <-> startWorking
        # both contain "work"; complete <-> done; reopen <-> new). This is
        # imperfect; we'll fall back to trying everything.
        STATE_HINTS = {
            'indevelopment': ['startworking', 'startwork', 'inprogress', 'begin'],
            'done': ['complete', 'finish', 'close', 'resolve'],
            'new': ['reopen', 'new', 'open'],
            'invalid': ['invalidate', 'reject'],
        }
        wanted = STATE_HINTS.get(target_state_local, [target_state_local])
        action_local = lambda u: u.rsplit('/', 1)[-1].rsplit('.', 1)[-1].lower()
        action_uris.sort(
            key=lambda u: (
                0 if any(h in action_local(u) for h in wanted) else
                1 if target_state_local in action_local(u) else 2
            )
        )

        new_rdf = re.sub(
            r'<([A-Za-z0-9_]+):state\s+rdf:resource="[^"]+"\s*/>',
            rf'<\1:state rdf:resource="{target_state_uri}"/>',
            rdf_str,
            count=1,
        )

        # Try each action in ranked order.
        last_error = ''
        for au in action_uris:
            action_id = au.rsplit('/', 1)[-1]
            put_url = workitem_url + ('&' if '?' in workitem_url else '?') + 'oslc_cm.properties=&' + 'rtc_cm.action=' + action_id  # build below differently
            put_url = workitem_url + ('&' if '?' in workitem_url else '?') + '_action=' + action_id
            try:
                put_resp = self.session.put(
                    put_url,
                    data=new_rdf.encode('utf-8'),
                    headers={
                        'Content-Type': 'application/rdf+xml',
                        'Accept': 'application/rdf+xml',
                        'OSLC-Core-Version': '2.0',
                        'If-Match': etag,
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    timeout=self._TIMEOUT,
                )
            except Exception as e:
                last_error = str(e)
                continue

            if put_resp.status_code in (200, 204):
                # Verify the state actually changed by re-GETing.
                try:
                    verify = self.session.get(
                        workitem_url,
                        headers={'Accept': 'application/rdf+xml',
                                 'OSLC-Core-Version': '2.0'},
                        timeout=self._TIMEOUT,
                    )
                    vm = re.search(
                        r'<[A-Za-z0-9_]+:state\s+rdf:resource="([^"]+)"',
                        verify.text,
                    )
                    if vm and vm.group(1) == target_state_uri:
                        return {
                            'url': workitem_url,
                            'state': target_state_uri,
                            'action': action_id,
                        }
                    # else: action was accepted but transitioned to a
                    # different state — keep trying.
                    if vm:
                        last_error = f"Action {action_id} moved state to {vm.group(1).rsplit('.', 1)[-1]}, not target."
                    # Re-fetch ETag for next attempt
                    etag = verify.headers.get('ETag', etag)
                except Exception:
                    pass
            else:
                em = self._extract_oslc_error(put_resp.text)
                last_error = f'HTTP {put_resp.status_code}: {em}' if em else f'HTTP {put_resp.status_code}'

        return {'error': f"No workflow action transitioned to '{target_state}'. "
                          f"Last attempt: {last_error}"}

    def query_work_items(self, ewm_project_url: str, where: str = '',
                         select: str = '*', page_size: int = 25) -> List[Dict]:
        """Query EWM work items via OSLC CM.

        Endpoint:
            /ccm/oslc/contexts/<paId>/workitems?oslc.where=...&oslc.select=...

        Returns list of dicts: id, title, state, type, owner, modified, url.
        Empty list on error.
        """
        self._ensure_auth()
        # Resolve query base from the project's services.xml
        try:
            sp_resp = self.session.get(
                ewm_project_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if sp_resp.status_code != 200:
                return []
            sproot = ET.fromstring(sp_resp.content)
            ns = self._NS_OSLC
            query_base = ''
            for qc in sproot.findall('.//oslc:QueryCapability', ns):
                qb = qc.find('oslc:queryBase', ns)
                if qb is not None:
                    query_base = qb.get(f'{{{ns["rdf"]}}}resource', '')
                    if query_base:
                        break
            if not query_base:
                return []
        except Exception:
            return []

        import urllib.parse
        params = []
        if where:
            params.append(('oslc.where', where))
        if select:
            params.append(('oslc.select', select))
        params.append(('oslc.pageSize', str(page_size)))
        url = query_base + ('&' if '?' in query_base else '?') + urllib.parse.urlencode(params)

        try:
            resp = self.session.get(
                url,
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
        except Exception:
            return []

        ns_rdf = self._NS_OSLC['rdf']
        ns_dct = 'http://purl.org/dc/terms/'
        ns_rtc = 'http://jazz.net/xmlns/prod/jazz/rtc/cm/1.0/'

        out: List[Dict] = []
        for desc in root.findall(f'{{{ns_rdf}}}Description'):
            about = desc.get(f'{{{ns_rdf}}}about', '')
            # Only real work items: /resource/itemName/.../WorkItem/<id> or
            # /oslc/contexts/<paId>/workitems/<id>. Skip shape descriptors.
            if not (
                '/com.ibm.team.workitem.WorkItem/' in about
                or '/contexts/' in about and '/workitems/' in about and not about.endswith('/services.xml')
            ):
                continue
            if '/shapes/' in about or '/shape/' in about:
                continue
            title_el = desc.find(f'{{{ns_dct}}}title')
            ident_el = desc.find(f'{{{ns_dct}}}identifier')
            mod_el = desc.find(f'{{{ns_dct}}}modified')
            type_el = desc.find(f'{{{ns_rtc}}}type')
            state_el = desc.find(f'{{{ns_rtc}}}state')
            contrib_el = desc.find(f'{{{ns_dct}}}contributor')
            out.append({
                'url': about,
                'id': (ident_el.text.strip() if ident_el is not None and ident_el.text else
                       (about.rstrip('/').split('/')[-1])),
                'title': title_el.text.strip() if title_el is not None and title_el.text else '',
                'modified': mod_el.text.strip() if mod_el is not None and mod_el.text else '',
                'type': type_el.get(f'{{{ns_rdf}}}resource', '') if type_el is not None else '',
                'state': state_el.get(f'{{{ns_rdf}}}resource', '') if state_el is not None else '',
                'owner': contrib_el.get(f'{{{ns_rdf}}}resource', '') if contrib_el is not None else '',
            })
        return out

    # ── Cross-domain link creation ─────────────────────────────

    def link_workitem_to_external_url(self, workitem_url: str,
                                       external_url: str,
                                       label: str = "External link",
                                       comment: str = "") -> Dict:
        """Attach an external URL (GitHub PR, GitLab MR, Bitbucket commit,
        Confluence page, anything outside ELM) to an EWM work item as an
        OSLC reference. After this call, opening the work item in EWM
        shows a clickable link to the external resource.

        This is the lightweight cross-tool integration — no need for
        the external system to speak OSLC; we just store the URL on the
        EWM side. Pairs naturally with create_task / create_defect /
        create_test_case (which write internal links) for teams that
        host code in GitHub instead of Jazz SCM.

        Uses oslc_cm:relatedURL — a generic "this work item references
        this URL" relation. EWM displays it under "Links → References"
        in the work-item UI.

        Returns {'workitem': str, 'external_url': str, 'label': str}
        on success or {'error': '...'} on failure.
        """
        self._ensure_auth()
        # Reuse the create_link plumbing — it does GET-with-ETag, modifies
        # the RDF, and PUTs with If-Match. We just pick a generic
        # oslc_cm:relatedURL predicate that EWM understands for arbitrary
        # external references.
        result = self.create_link(
            source_url=workitem_url,
            link_type_uri='http://open-services.net/ns/cm#relatedURL',
            target_url=external_url,
        )
        if result and 'error' not in result:
            return {
                'workitem': workitem_url,
                'external_url': external_url,
                'label': label,
                'comment': comment,
            }
        return result

    def create_link(self, source_url: str, link_type_uri: str,
                    target_url: str) -> Dict:
        """Create an OSLC link between two existing artifacts.

        Auto-detects source domain from URL and uses GET-with-ETag →
        PUT-with-If-Match (DNG, EWM, ETM all support this on their
        artifact resource URLs).

        Returns {'source', 'target', 'link_type'} on success, else
        {'error': ...}.
        """
        self._ensure_auth()
        try:
            get_resp = self.session.get(
                source_url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if get_resp.status_code != 200:
                return {'error': f'Failed to fetch source: HTTP {get_resp.status_code}'}
            etag = get_resp.headers.get('ETag', '')
            if not etag:
                return {'error': 'Source returned no ETag — refusing to PUT.'}
        except Exception as e:
            return {'error': f'Failed to fetch source: {e}'}

        rdf_str = get_resp.content.decode('utf-8')
        import re

        if '#' in link_type_uri:
            base_ns, local = link_type_uri.rsplit('#', 1)
            base_ns += '#'
        else:
            base_ns, local = link_type_uri.rsplit('/', 1)
            base_ns += '/'

        m = re.search(rf'xmlns:([A-Za-z][A-Za-z0-9_]*)="{re.escape(base_ns)}"', rdf_str)
        if m:
            prefix = m.group(1)
        else:
            prefix = f'lt_{abs(hash(base_ns)) % 10000}'
            rdf_str = re.sub(
                r'(<rdf:RDF\b[^>]*)',
                rf'\1 xmlns:{prefix}="{base_ns}"',
                rdf_str,
                count=1,
            )

        triple = f'\n    <{prefix}:{local} rdf:resource="{target_url}"/>'

        # Inject inside the rdf:Description for source_url, if present
        inj_pat = re.compile(
            rf'(<rdf:Description\b[^>]*rdf:about="{re.escape(source_url)}"[^>]*>)(.*?)(</rdf:Description>)',
            re.DOTALL,
        )
        inj = inj_pat.search(rdf_str)
        if inj:
            rdf_str = (rdf_str[:inj.start()] + inj.group(1) + inj.group(2)
                       + triple + '\n  ' + inj.group(3) + rdf_str[inj.end():])
        else:
            rdf_str = rdf_str.replace('</rdf:Description>', triple + '\n  </rdf:Description>', 1)

        try:
            put_resp = self.session.put(
                source_url,
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
                return {'source': source_url, 'target': target_url, 'link_type': link_type_uri}
            error_msg = self._extract_oslc_error(put_resp.text)
            return {'error': f'HTTP {put_resp.status_code}: {error_msg}' if error_msg
                    else f'HTTP {put_resp.status_code}'}
        except Exception as e:
            return {'error': f'PUT failed: {e}'}

    # ── EWM: defect creation ──────────────────────────────────

    def create_defect(self, service_provider_url: str, title: str,
                      description: str = '', severity: Optional[str] = None,
                      requirement_url: Optional[str] = None,
                      test_case_url: Optional[str] = None) -> Dict:
        """Create a Defect work item in EWM.

        Resolves:
          - the Defect creation factory from services.xml,
          - the `filedAgainst` category default from the defect resource shape,
          - severity URI from the project's severity enumeration (if name given).

        Optionally cross-links to a DNG requirement (oslc_cm:affectedByDefect /
        calm:tracksRequirement) or to an ETM test case (oslc_cm:relatedTestCase).
        """
        self._ensure_auth()

        # Find Defect creation factory and shape URL
        try:
            sp_resp = self.session.get(
                service_provider_url,
                headers={'Accept': 'application/rdf+xml', 'OSLC-Core-Version': '2.0'},
                timeout=self._TIMEOUT,
            )
            if sp_resp.status_code != 200:
                return {'error': f'Could not load service provider: HTTP {sp_resp.status_code}'}
            sproot = ET.fromstring(sp_resp.content)
        except Exception as e:
            return {'error': f'Service provider fetch failed: {e}'}

        ns = self._NS_OSLC
        creation_url = ''
        shape_url = ''
        for cf in sproot.findall('.//oslc:CreationFactory', ns):
            title_el = cf.find('dcterms:title', ns)
            t = (title_el.text or '').lower() if title_el is not None else ''
            if 'defect' not in t:
                continue
            cr = cf.find('oslc:creation', ns)
            sh = cf.find('oslc:resourceShape', ns)
            if cr is not None:
                creation_url = cr.get(f'{{{ns["rdf"]}}}resource', '')
            if sh is not None:
                shape_url = sh.get(f'{{{ns["rdf"]}}}resource', '')
            if creation_url:
                break

        if not creation_url:
            return {'error': 'Defect creation factory not found.'}

        # Read filedAgainst from the defect shape.
        # Strategy: collect both the default value (often "Unassigned" — many
        # process configs reject Unassigned for defects) and the full
        # AllowedValues list. Prefer the first non-Unassigned, non-default
        # category; only fall back to default if that's all there is.
        filed_against_url = ''
        shape_resp = None
        sroot = None
        if shape_url:
            try:
                shape_resp = self.session.get(
                    shape_url,
                    headers={'Accept': 'application/rdf+xml', 'OSLC-Core-Version': '2.0'},
                    timeout=self._TIMEOUT,
                )
                if shape_resp.status_code == 200:
                    sroot = ET.fromstring(shape_resp.content)
                    candidates = list(sroot.iter(f'{{{ns["oslc"]}}}Property')) + \
                                 list(sroot.findall(f'{{{ns["rdf"]}}}Description'))
                    default_val = ''
                    allowed_values_url = ''
                    for prop in candidates:
                        pdef = prop.find(f'{{{ns["oslc"]}}}propertyDefinition')
                        if pdef is None:
                            continue
                        pu = pdef.get(f'{{{ns["rdf"]}}}resource', '')
                        if pu.endswith('filedAgainst'):
                            dv = prop.find(f'{{{ns["oslc"]}}}defaultValue')
                            if dv is not None:
                                default_val = dv.get(f'{{{ns["rdf"]}}}resource', '')
                            av = prop.find(f'{{{ns["oslc"]}}}allowedValues')
                            if av is not None:
                                allowed_values_url = av.get(f'{{{ns["rdf"]}}}resource', '')
                            break
                    # Fetch allowed-values, pick first non-default category
                    chosen = ''
                    if allowed_values_url:
                        try:
                            av_resp = self.session.get(
                                allowed_values_url,
                                headers={'Accept': 'application/rdf+xml',
                                         'OSLC-Core-Version': '2.0'},
                                timeout=self._TIMEOUT,
                            )
                            if av_resp.status_code == 200:
                                av_root = ET.fromstring(av_resp.content)
                                for av_el in av_root.iter(f'{{{ns["oslc"]}}}allowedValue'):
                                    cat_url = av_el.get(f'{{{ns["rdf"]}}}resource', '')
                                    if cat_url and cat_url != default_val:
                                        chosen = cat_url
                                        break
                        except Exception:
                            pass
                    filed_against_url = chosen or default_val
            except Exception:
                pass

        # Resolve severity URI if friendly name given
        severity_uri = ''
        if severity:
            sev_lower = severity.strip().lower()
            if sev_lower.startswith('http'):
                severity_uri = severity
            elif shape_url and sroot is not None:
                # Locate severity property → range URI for enumeration
                enum_url = ''
                candidates2 = list(sroot.iter(f'{{{ns["oslc"]}}}Property')) + \
                              list(sroot.findall(f'{{{ns["rdf"]}}}Description'))
                for prop in candidates2:
                    pdef = prop.find(f'{{{ns["oslc"]}}}propertyDefinition')
                    if pdef is None:
                        continue
                    if pdef.get(f'{{{ns["rdf"]}}}resource', '').endswith('severity'):
                        rng = prop.find(f'{{{ns["oslc"]}}}range')
                        if rng is not None:
                            enum_url = rng.get(f'{{{ns["rdf"]}}}resource', '')
                            if enum_url:
                                break
                if enum_url:
                    try:
                        enum_resp = self.session.get(
                            enum_url,
                            headers={'Accept': 'application/rdf+xml',
                                     'OSLC-Core-Version': '2.0'},
                            timeout=self._TIMEOUT,
                        )
                        if enum_resp.status_code == 200:
                            eroot = ET.fromstring(enum_resp.content)
                            ns_dct = 'http://purl.org/dc/terms/'
                            for desc in eroot.findall(f'{{{ns["rdf"]}}}Description'):
                                t_el = desc.find(f'{{{ns_dct}}}title')
                                if t_el is None or not t_el.text:
                                    continue
                                if t_el.text.strip().lower() == sev_lower:
                                    severity_uri = desc.get(f'{{{ns["rdf"]}}}about', '')
                                    break
                    except Exception:
                        pass

        clean_title = title.strip()
        desc_body = description or ""

        # Build extra triples
        extras = []
        if filed_against_url:
            extras.append(f'<rtc_cm:filedAgainst rdf:resource="{filed_against_url}"/>')
        if severity_uri:
            extras.append(f'<oslc_cmx:severity rdf:resource="{severity_uri}"/>')
        if requirement_url:
            # Same lesson as create_ewm_task: calm: predicates get silently
            # dropped by EWM. Use the oslc_cm: namespace (which actually
            # persists) and the standard "affectsRequirement" semantic.
            extras.append(f'<oslc_cm:affectsRequirement rdf:resource="{requirement_url}"/>')
        if test_case_url:
            extras.append(f'<oslc_cm:relatedTestCase rdf:resource="{test_case_url}"/>')

        rdf = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:oslc_cm="http://open-services.net/ns/cm#"
         xmlns:oslc_cmx="http://open-services.net/ns/cm-x#"
         xmlns:rtc_cm="http://jazz.net/xmlns/prod/jazz/rtc/cm/1.0/">
  <rdf:Description>
    <dcterms:title>{self._escape_xml(clean_title)}</dcterms:title>
    <dcterms:description>{self._escape_xml(desc_body)}</dcterms:description>
    {''.join('    ' + e + chr(10) for e in extras)}
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
                defect_url = resp.headers.get('Location', '')
                result = {'title': clean_title, 'url': defect_url}
                # Bidirectional link write — same DNG render-quirk as
                # create_ewm_task / create_test_case. The forward link
                # (oslc_cm:affectsRequirement on the defect) makes the
                # defect show the requirement; we need the inverse triple
                # on the requirement so DNG renders the defect in its
                # Links panel. oslc_rm:affectedBy is the inverse.
                if requirement_url and defect_url:
                    backlink_result = self.create_link(
                        source_url=requirement_url,
                        link_type_uri='http://open-services.net/ns/rm#affectedBy',
                        target_url=defect_url,
                    )
                    if backlink_result and 'error' in backlink_result:
                        result['backlink_warning'] = (
                            f"Forward link (EWM→DNG) succeeded; back-link "
                            f"(DNG→EWM) failed: {backlink_result['error']}. "
                            f"The defect shows the requirement, but the "
                            f"requirement may not show the defect in DNG."
                        )
                return result
            error_msg = self._extract_oslc_error(resp.text)
            return {'error': f"HTTP {resp.status_code}: {error_msg}" if error_msg
                    else f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'error': str(e)}

    # ── SCM (Jazz SCM, read-only) ──────────────────────────────

    def scm_list_projects(self) -> List[Dict]:
        """List SCM service-providers from /ccm/oslc-scm/catalog (note hyphen).

        Returns: list of {name, projectAreaId, providerUrl}.
        """
        self._ensure_auth()
        try:
            resp = self.session.get(
                f"{self.ccm_url}/oslc-scm/catalog",
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.content)
        except Exception:
            return []

        ns = self._NS_OSLC
        out: List[Dict] = []
        for sp in root.findall('.//oslc:ServiceProvider', ns):
            about = sp.get(f'{{{ns["rdf"]}}}about', '')
            title_el = sp.find('dcterms:title', ns)
            name = title_el.text.strip() if title_el is not None and title_el.text else ''
            pa_id = ''
            if '/project-area/' in about:
                pa_id = about.rstrip('/').split('/project-area/')[-1]
            out.append({
                'name': name,
                'projectAreaId': pa_id,
                'providerUrl': about,
            })
        return out

    def _scm_paged_changeset_uris(self, limit: int = 25) -> List[str]:
        """Walk TRS pages until we have at least `limit` change-set URIs."""
        uris: List[str] = []
        page_url = f"{self.ccm_url}/rtcoslc/scm/reportable/trs/cs"
        ns_trs = 'http://open-services.net/ns/core/trs#'
        ns_rdf = self._NS_OSLC['rdf']
        seen = 0
        while page_url and seen < 25 and len(uris) < limit:
            try:
                resp = self.session.get(
                    page_url,
                    headers={
                        'Accept': 'application/rdf+xml',
                        'OSLC-Core-Version': '2.0',
                    },
                    timeout=self._TIMEOUT,
                )
                if resp.status_code != 200:
                    break
                root = ET.fromstring(resp.content)
            except Exception:
                break
            for changed in root.iter(f'{{{ns_trs}}}changed'):
                u = changed.get(f'{{{ns_rdf}}}resource', '')
                if u and u not in uris:
                    uris.append(u)
                    if len(uris) >= limit:
                        return uris
            # find <trs:previous>
            prev_el = root.find(f'.//{{{ns_trs}}}previous')
            page_url = prev_el.get(f'{{{ns_rdf}}}resource', '') if prev_el is not None else ''
            seen += 1
        return uris

    def _scm_workitems_for_changeset(self, cs_oid_url: str) -> List[Dict]:
        """Walk the cslink TRS for a given change-set's canonical OID URL,
        return [{workItemId, url}] for any that link to it.

        This is best-effort and only checks the first page of cslink TRS
        unless we discover the change-set OID quickly.
        """
        out: List[Dict] = []
        page_url = f"{self.ccm_url}/rtcoslc/scm/cslink/trs"
        ns_trs = 'http://open-services.net/ns/core/trs#'
        ns_rdf = self._NS_OSLC['rdf']
        ns_cm = 'http://open-services.net/ns/cm#'

        link_resources: List[str] = []
        try:
            resp = self.session.get(
                page_url,
                headers={'Accept': 'application/rdf+xml', 'OSLC-Core-Version': '2.0'},
                timeout=self._TIMEOUT,
            )
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for changed in root.iter(f'{{{ns_trs}}}changed'):
                    link_resources.append(changed.get(f'{{{ns_rdf}}}resource', ''))
        except Exception:
            return out

        # For each cslink resource, GET it and see if it points to our CS.
        for lr in link_resources[:25]:  # cap to avoid runaway
            if not lr:
                continue
            try:
                lr_resp = self.session.get(
                    lr,
                    headers={'Accept': 'application/rdf+xml', 'OSLC-Core-Version': '2.0'},
                    timeout=15,
                )
                if lr_resp.status_code != 200:
                    continue
                lroot = ET.fromstring(lr_resp.content)
            except Exception:
                continue
            for desc in lroot.findall(f'{{{ns_rdf}}}Description'):
                wi = desc.get(f'{{{ns_rdf}}}about', '')
                tracks = desc.find(f'{{{ns_cm}}}tracksChangeSet')
                if tracks is None:
                    continue
                if tracks.get(f'{{{ns_rdf}}}resource', '') == cs_oid_url:
                    wi_id = ''
                    if '/WorkItem/' in wi:
                        wi_id = wi.rstrip('/').split('/')[-1]
                    out.append({'workItemId': wi_id, 'url': wi})
        return out

    def scm_list_changesets(self, project_name: Optional[str] = None,
                            limit: int = 25) -> List[Dict]:
        """List recent change-sets via the SCM TRS feed.

        Walks `/ccm/rtcoslc/scm/reportable/trs/cs` (paginated by
        <trs:previous>), GETs each change-set RDF for metadata, and (if
        a project name is given) filters by `process:projectArea` title
        match.

        TRS feeds only ship the most recent ~5 changes per page; this
        method walks at most ~25 pages.

        Returns [{itemId, title, component, author, modified, totalChanges,
                  workItems[], url}].
        """
        self._ensure_auth()

        # Map project name → projectArea URL (so we can filter)
        target_pa_url = ''
        if project_name:
            projects = self.scm_list_projects()
            for p in projects:
                if project_name.lower() in p['name'].lower():
                    # Build process:projectArea URL: /ccm/process/project-areas/<paId>
                    target_pa_url = f"{self.ccm_url}/process/project-areas/{p['projectAreaId']}"
                    break

        cs_uris = self._scm_paged_changeset_uris(limit=limit * 4 if project_name else limit)

        ns_dct = 'http://purl.org/dc/terms/'
        ns_rdf = self._NS_OSLC['rdf']
        ns_scm = 'http://jazz.net/ns/scm#'
        ns_proc = 'http://jazz.net/ns/process#'

        out: List[Dict] = []
        for uri in cs_uris:
            if len(out) >= limit:
                break
            try:
                resp = self.session.get(
                    uri,
                    headers={'Accept': 'application/rdf+xml', 'OSLC-Core-Version': '2.0'},
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue
                root = ET.fromstring(resp.content)
            except Exception:
                continue

            cs_el = root.find(f'{{{ns_scm}}}ChangeSet')
            if cs_el is None:
                continue
            cs_about = cs_el.get(f'{{{ns_rdf}}}about', '')

            pa_el = cs_el.find(f'{{{ns_proc}}}projectArea')
            pa_url = pa_el.get(f'{{{ns_rdf}}}resource', '') if pa_el is not None else ''
            if target_pa_url and pa_url != target_pa_url:
                continue

            ident = cs_el.find(f'{{{ns_dct}}}identifier')
            title = cs_el.find(f'{{{ns_dct}}}title')
            comp = cs_el.find(f'{{{ns_scm}}}component')
            contrib = cs_el.find(f'{{{ns_dct}}}contributor')
            modified = cs_el.find(f'{{{ns_dct}}}modified')
            total = cs_el.find(f'{{{ns_scm}}}totalChanges')

            cs_id = (ident.text.strip() if ident is not None and ident.text else
                     uri.rstrip('/').split('/')[-1])
            cs_oid_url = f"{self.ccm_url}/resource/itemOid/com.ibm.team.scm.ChangeSet/{cs_id}"

            out.append({
                'itemId': cs_id,
                'title': title.text.strip() if title is not None and title.text else '',
                'component': comp.text.strip() if comp is not None and comp.text else '',
                'author': contrib.get(f'{{{ns_rdf}}}resource', '') if contrib is not None else '',
                'modified': modified.text.strip() if modified is not None and modified.text else '',
                'totalChanges': int(total.text) if total is not None and total.text and total.text.isdigit() else 0,
                'workItems': self._scm_workitems_for_changeset(cs_oid_url),
                'url': cs_about,
                'projectArea': pa_url,
            })
        return out

    def scm_get_changeset(self, changeset_id: str) -> Dict:
        """Fetch a single change-set by its `_xxx` itemId.

        GET both:
          - /ccm/rtcoslc/scm/reportable/cs/<id>  (reportable RDF)
          - /ccm/resource/itemOid/com.ibm.team.scm.ChangeSet/<id> (canonical)

        Returns {itemId, title, component, author, modified, totalChanges,
                 workItems[], reportable_url, canonical_url, rawRDF}.
        """
        self._ensure_auth()
        cs_id = changeset_id.strip()
        if not cs_id.startswith('_'):
            cs_id = '_' + cs_id

        rep_url = f"{self.ccm_url}/rtcoslc/scm/reportable/cs/{cs_id}"
        canon_url = f"{self.ccm_url}/resource/itemOid/com.ibm.team.scm.ChangeSet/{cs_id}"
        try:
            resp = self.session.get(
                rep_url,
                headers={'Accept': 'application/rdf+xml', 'OSLC-Core-Version': '2.0'},
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return {'error': f'HTTP {resp.status_code} on reportable URL'}
            root = ET.fromstring(resp.content)
        except Exception as e:
            return {'error': str(e)}

        ns_dct = 'http://purl.org/dc/terms/'
        ns_rdf = self._NS_OSLC['rdf']
        ns_scm = 'http://jazz.net/ns/scm#'
        ns_proc = 'http://jazz.net/ns/process#'

        cs_el = root.find(f'{{{ns_scm}}}ChangeSet')
        if cs_el is None:
            return {'error': 'No scm:ChangeSet element found in response.'}

        ident = cs_el.find(f'{{{ns_dct}}}identifier')
        title = cs_el.find(f'{{{ns_dct}}}title')
        comp = cs_el.find(f'{{{ns_scm}}}component')
        contrib = cs_el.find(f'{{{ns_dct}}}contributor')
        modified = cs_el.find(f'{{{ns_dct}}}modified')
        total = cs_el.find(f'{{{ns_scm}}}totalChanges')
        pa_el = cs_el.find(f'{{{ns_proc}}}projectArea')

        return {
            'itemId': ident.text.strip() if ident is not None and ident.text else cs_id,
            'title': title.text.strip() if title is not None and title.text else '',
            'component': comp.text.strip() if comp is not None and comp.text else '',
            'author': contrib.get(f'{{{ns_rdf}}}resource', '') if contrib is not None else '',
            'modified': modified.text.strip() if modified is not None and modified.text else '',
            'totalChanges': int(total.text) if total is not None and total.text and total.text.isdigit() else 0,
            'projectArea': pa_el.get(f'{{{ns_rdf}}}resource', '') if pa_el is not None else '',
            'reportable_url': rep_url,
            'canonical_url': canon_url,
            'workItems': self._scm_workitems_for_changeset(canon_url),
            'rawRDF': resp.content.decode('utf-8'),
        }

    def scm_get_workitem_changesets(self, workitem_id: str) -> List[Dict]:
        """List change-sets attached to a work item.

        GETs `/ccm/resource/itemName/com.ibm.team.workitem.WorkItem/<id>`
        and parses the `rtc_cm:com.ibm.team.filesystem.workitems.change_set.com.ibm.team.scm.ChangeSet`
        triples (full RDF predicate).

        Returns [{changeSetId, title, url}].  Empty list if the WI has
        no SCM links (which is fine — every WI has the shape).
        """
        self._ensure_auth()
        wi_id = workitem_id.strip()
        url = f"{self.ccm_url}/resource/itemName/com.ibm.team.workitem.WorkItem/{wi_id}"
        try:
            resp = self.session.get(
                url,
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
        except Exception:
            return []

        ns_dct = 'http://purl.org/dc/terms/'
        ns_rdf = self._NS_OSLC['rdf']
        cs_pred = '{http://jazz.net/xmlns/prod/jazz/rtc/cm/1.0/}com.ibm.team.filesystem.workitems.change_set.com.ibm.team.scm.ChangeSet'

        # Build map of CS-URL → reified-statement title (from rdf:Statement nodeIDs)
        title_map: Dict[str, str] = {}
        for desc in root.findall(f'{{{ns_rdf}}}Description'):
            obj_el = desc.find(f'{{{ns_rdf}}}object')
            pred_el = desc.find(f'{{{ns_rdf}}}predicate')
            t_el = desc.find(f'{{{ns_dct}}}title')
            if obj_el is None or pred_el is None or t_el is None:
                continue
            pu = pred_el.get(f'{{{ns_rdf}}}resource', '')
            ou = obj_el.get(f'{{{ns_rdf}}}resource', '')
            if 'change_set.com.ibm.team.scm.ChangeSet' in pu and ou and t_el.text:
                title_map[ou] = t_el.text.strip()

        out: List[Dict] = []
        seen = set()
        for desc in root.findall(f'{{{ns_rdf}}}Description'):
            for cs_link in desc.findall(cs_pred):
                cs_url = cs_link.get(f'{{{ns_rdf}}}resource', '')
                if not cs_url or cs_url in seen:
                    continue
                seen.add(cs_url)
                cs_id = cs_url.rstrip('/').split('/')[-1]
                out.append({
                    'changeSetId': cs_id,
                    'title': title_map.get(cs_url, ''),
                    'url': cs_url,
                })
        return out

    # ── EWM Reviews / Approvals ───────────────────────────────

    def review_get(self, workitem_id: str) -> Dict:
        """Fetch review-relevant fields from a work item.

        Returns:
          {title, state, type, approved, reviewed,
           approvals: [{approver, descriptor, stateName, stateIdentifier}],
           changeSets: [{changeSetId, title, url}],
           comments_url}

        Approvals are read from the work-item's `rtc_cm:approvals` (when
        embedded in the RDF). On servers where approvals are out-of-line,
        we fall back to the workitems/approvals collection.
        """
        self._ensure_auth()
        wi_id = workitem_id.strip()
        url = f"{self.ccm_url}/resource/itemName/com.ibm.team.workitem.WorkItem/{wi_id}"
        try:
            resp = self.session.get(
                url,
                headers={
                    'Accept': 'application/rdf+xml',
                    'OSLC-Core-Version': '2.0',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return {'error': f'HTTP {resp.status_code}'}
            root = ET.fromstring(resp.content)
        except Exception as e:
            return {'error': str(e)}

        ns_dct = 'http://purl.org/dc/terms/'
        ns_rdf = self._NS_OSLC['rdf']
        ns_oslc_cm = 'http://open-services.net/ns/cm#'
        ns_rtc = 'http://jazz.net/xmlns/prod/jazz/rtc/cm/1.0/'
        ns_oslc = 'http://open-services.net/ns/core#'

        title = ''
        state = ''
        wi_type = ''
        approved = None
        reviewed = None
        comments_url = ''
        for desc in root.findall(f'{{{ns_rdf}}}Description'):
            about = desc.get(f'{{{ns_rdf}}}about', '')
            if about != url:
                continue
            t_el = desc.find(f'{{{ns_dct}}}title')
            if t_el is not None and t_el.text:
                title = t_el.text.strip()
            state_el = desc.find(f'{{{ns_rtc}}}state')
            if state_el is not None:
                state = state_el.get(f'{{{ns_rdf}}}resource', '')
            type_el = desc.find(f'{{{ns_rtc}}}type')
            if type_el is not None:
                wi_type = type_el.get(f'{{{ns_rdf}}}resource', '')
            ap_el = desc.find(f'{{{ns_oslc_cm}}}approved')
            if ap_el is not None and ap_el.text:
                approved = ap_el.text.strip().lower() == 'true'
            rv_el = desc.find(f'{{{ns_oslc_cm}}}reviewed')
            if rv_el is not None and rv_el.text:
                reviewed = rv_el.text.strip().lower() == 'true'
            disc_el = desc.find(f'{{{ns_oslc}}}discussedBy')
            if disc_el is not None:
                comments_url = disc_el.get(f'{{{ns_rdf}}}resource', '')

        # Walk for change-sets via the same logic as scm_get_workitem_changesets
        cs_pred = f'{{{ns_rtc}}}com.ibm.team.filesystem.workitems.change_set.com.ibm.team.scm.ChangeSet'
        change_sets: List[Dict] = []
        seen = set()
        for desc in root.findall(f'{{{ns_rdf}}}Description'):
            for cs_link in desc.findall(cs_pred):
                cs_url = cs_link.get(f'{{{ns_rdf}}}resource', '')
                if not cs_url or cs_url in seen:
                    continue
                seen.add(cs_url)
                change_sets.append({
                    'changeSetId': cs_url.rstrip('/').split('/')[-1],
                    'title': '',
                    'url': cs_url,
                })

        # Approvals: try inline <rtc_cm:approvals> first
        approvals: List[Dict] = []
        approvals_pred = f'{{{ns_rtc}}}approvals'
        for desc in root.findall(f'{{{ns_rdf}}}Description'):
            for ap_block in desc.findall(approvals_pred):
                # Inline blank node or referenced
                for ap_node in ap_block:
                    rec = self._parse_approval_node(ap_node, ns_rdf, ns_dct, ns_rtc)
                    if rec:
                        approvals.append(rec)

        return {
            'workItemId': wi_id,
            'workItemUrl': url,
            'title': title,
            'state': state,
            'type': wi_type,
            'approved': approved,
            'reviewed': reviewed,
            'approvals': approvals,
            'changeSets': change_sets,
            'comments_url': comments_url,
        }

    def _parse_approval_node(self, ap_node, ns_rdf, ns_dct, ns_rtc) -> Optional[Dict]:
        """Helper: parse a single approval node (per scm_05_wi_schema.xml shape).

        Looks for: dcterms:title (descriptor), rtc_cm:approver/contributor,
        rtc_cm:stateName / state identifier.
        """
        try:
            descriptor = ''
            t_el = ap_node.find(f'{{{ns_dct}}}title')
            if t_el is not None and t_el.text:
                descriptor = t_el.text.strip()
            approver = ''
            for a_tag in ('approver', 'contributor', 'creator'):
                a_el = ap_node.find(f'{{{ns_rtc}}}{a_tag}') or ap_node.find(f'{{{ns_dct}}}{a_tag}')
                if a_el is not None:
                    approver = a_el.get(f'{{{ns_rdf}}}resource', '')
                    if approver:
                        break
            state_name = ''
            state_id = ''
            sn_el = ap_node.find(f'{{{ns_rtc}}}stateName')
            if sn_el is not None and sn_el.text:
                state_name = sn_el.text.strip()
            si_el = ap_node.find(f'{{{ns_rtc}}}stateIdentifier')
            if si_el is not None and si_el.text:
                state_id = si_el.text.strip()
            if not (descriptor or approver or state_name):
                return None
            return {
                'approver': approver,
                'descriptor': descriptor,
                'stateName': state_name,
                'stateIdentifier': state_id,
            }
        except Exception:
            return None

    def review_list_open(self, ewm_project_url: str) -> List[Dict]:
        """List open review work items for an EWM project.

        Runs the OSLC CM query:
            oslc.where=rtc_cm:type="com.ibm.team.review.workItemType.review"
                       and oslc_cm:closed=false
        against the project's workitems query base.

        Returns [{workItemId, title, type, state, url}]. Empty list if
        the project has no review-typed WIs (which is the case on this
        sandbox — that's expected).
        """
        # Reuse query_work_items but with the review type filter.
        where = ('rtc_cm:type="com.ibm.team.review.workItemType.review"'
                 ' and oslc_cm:closed=false')
        items = self.query_work_items(
            ewm_project_url=ewm_project_url,
            where=where,
            select='dcterms:title,dcterms:identifier,rtc_cm:type,rtc_cm:state,oslc_cm:closed',
            page_size=100,
        )
        return items

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


# Built by Brett Scharmett — not an official IBM product
