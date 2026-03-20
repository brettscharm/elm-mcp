"""
DOORS Next Client for IBM Bob Integration
Connects to IBM DOORS Next and pulls requirements
"""

import os
import requests
import json
from typing import List, Dict, Optional
from dotenv import load_dotenv
import xml.etree.ElementTree as ET


class DOORSNextClient:
    """Client for interacting with IBM DOORS Next (DNG) API"""
    
    def __init__(self, base_url: str, username: str, password: str, project: str):
        """
        Initialize DOORS Next client
        
        Args:
            base_url: DOORS Next server URL (e.g., https://goblue.clm.ibmcloud.com/rm)
            username: Your DOORS Next username
            password: Your DOORS Next password
            project: Project area name
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.project = project
        self.session = requests.Session()
        self._authenticated = False
        
    @classmethod
    def from_env(cls):
        """Create client from environment variables"""
        load_dotenv()
        
        base_url = os.getenv('DOORS_URL')
        username = os.getenv('DOORS_USERNAME')
        password = os.getenv('DOORS_PASSWORD')
        project = os.getenv('DOORS_PROJECT')
        
        if not all([base_url, username, password, project]):
            raise ValueError(
                "Missing required environment variables. "
                "Please set DOORS_URL, DOORS_USERNAME, DOORS_PASSWORD, and DOORS_PROJECT in .env file"
            )
        
        return cls(base_url, username, password, project)
    
    def authenticate(self) -> bool:
        """
        Authenticate with DOORS Next using form-based authentication
        
        Returns:
            True if authentication successful, False otherwise
        """
        try:
            # Step 1: Get the login form
            auth_url = f"{self.base_url.replace('/rm', '')}/jts/j_security_check"
            
            # Step 2: Submit credentials
            auth_data = {
                'j_username': self.username,
                'j_password': self.password
            }
            
            response = self.session.post(auth_url, data=auth_data, allow_redirects=True)
            
            # Step 3: Verify authentication
            if response.status_code == 200 and 'authfailed' not in response.url.lower():
                self._authenticated = True
                print("✅ Successfully authenticated with DOORS Next")
                return True
            else:
                print("❌ Authentication failed")
                return False
                
        except Exception as e:
            print(f"❌ Authentication error: {str(e)}")
            return False
    
    def _ensure_authenticated(self):
        """Ensure we're authenticated before making requests"""
        if not self._authenticated:
            if not self.authenticate():
                raise Exception("Failed to authenticate with DOORS Next")
    
    def get_project_info(self) -> Dict:
        """
        Get information about the project
        
        Returns:
            Dictionary with project information
        """
        self._ensure_authenticated()
        
        try:
            # Get project areas
            url = f"{self.base_url}/process/project-areas"
            response = self.session.get(url)
            
            if response.status_code == 200:
                return {
                    'status': 'success',
                    'message': 'Connected to DOORS Next',
                    'project': self.project
                }
            else:
                return {
                    'status': 'error',
                    'message': f'Failed to get project info: {response.status_code}'
                }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error: {str(e)}'
            }
    
    def get_requirements(self, 
                        status: Optional[str] = None,
                        req_type: Optional[str] = None,
                        limit: int = 100) -> List[Dict]:
        """
        Get requirements from DOORS Next
        
        Args:
            status: Filter by status (e.g., 'Approved', 'In Progress')
            req_type: Filter by type (e.g., 'Functional', 'Non-Functional')
            limit: Maximum number of requirements to return
            
        Returns:
            List of requirement dictionaries
        """
        self._ensure_authenticated()
        
        try:
            # Build OSLC query
            url = f"{self.base_url}/oslc_rm/query"
            
            # Basic query parameters
            params = {
                'oslc.select': '*',
                'oslc.pageSize': limit
            }
            
            # Add filters if specified
            where_clauses = []
            if status:
                where_clauses.append(f'dcterms:status="{status}"')
            if req_type:
                where_clauses.append(f'dcterms:type="{req_type}"')
            
            if where_clauses:
                params['oslc.where'] = ' and '.join(where_clauses)
            
            response = self.session.get(url, params=params)
            
            if response.status_code == 200:
                # Parse response (could be JSON or XML depending on Accept header)
                requirements = self._parse_requirements_response(response.text)
                print(f"✅ Retrieved {len(requirements)} requirements")
                return requirements
            else:
                print(f"❌ Failed to get requirements: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"❌ Error getting requirements: {str(e)}")
            return []
    
    def get_requirement_by_id(self, req_id: str) -> Optional[Dict]:
        """
        Get a specific requirement by ID
        
        Args:
            req_id: Requirement ID (e.g., 'REQ-1234')
            
        Returns:
            Requirement dictionary or None if not found
        """
        self._ensure_authenticated()
        
        try:
            url = f"{self.base_url}/resources/{req_id}"
            response = self.session.get(url)
            
            if response.status_code == 200:
                requirement = self._parse_requirement(response.text)
                print(f"✅ Retrieved requirement {req_id}")
                return requirement
            else:
                print(f"❌ Requirement {req_id} not found")
                return None
                
        except Exception as e:
            print(f"❌ Error getting requirement: {str(e)}")
            return None
    
    def update_requirement_status(self, req_id: str, status: str, comment: str = "") -> bool:
        """
        Update the status of a requirement
        
        Args:
            req_id: Requirement ID
            status: New status (e.g., 'In Progress', 'Implemented')
            comment: Optional comment about the change
            
        Returns:
            True if successful, False otherwise
        """
        self._ensure_authenticated()
        
        try:
            url = f"{self.base_url}/resources/{req_id}"
            
            data = {
                'status': status,
                'comment': comment
            }
            
            response = self.session.put(url, json=data)
            
            if response.status_code in [200, 204]:
                print(f"✅ Updated {req_id} status to '{status}'")
                return True
            else:
                print(f"❌ Failed to update status: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Error updating status: {str(e)}")
            return False
    
    def _parse_requirements_response(self, response_text: str) -> List[Dict]:
        """Parse requirements from API response"""
        # This is a simplified parser - actual implementation depends on response format
        requirements = []
        
        try:
            # Try parsing as JSON first
            data = json.loads(response_text)
            if isinstance(data, list):
                requirements = data
            elif isinstance(data, dict) and 'results' in data:
                requirements = data['results']
        except json.JSONDecodeError:
            # If not JSON, might be XML - parse accordingly
            try:
                root = ET.fromstring(response_text)
                # Parse XML structure (simplified)
                for item in root.findall('.//{http://www.w3.org/2005/Atom}entry'):
                    req = self._parse_xml_requirement(item)
                    if req:
                        requirements.append(req)
            except ET.ParseError:
                print("⚠️ Could not parse response format")
        
        return requirements
    
    def _parse_requirement(self, response_text: str) -> Optional[Dict]:
        """Parse a single requirement from API response"""
        try:
            # Try JSON first
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try XML
            try:
                root = ET.fromstring(response_text)
                return self._parse_xml_requirement(root)
            except ET.ParseError:
                return None
    
    def _parse_xml_requirement(self, element: ET.Element) -> Dict:
        """Parse requirement from XML element"""
        # Simplified XML parsing - adjust based on actual DOORS Next XML structure
        req = {
            'id': element.findtext('.//{http://purl.org/dc/terms/}identifier', ''),
            'title': element.findtext('.//{http://purl.org/dc/terms/}title', ''),
            'description': element.findtext('.//{http://purl.org/dc/terms/}description', ''),
            'status': element.findtext('.//{http://purl.org/dc/terms/}status', ''),
            'type': element.findtext('.//{http://purl.org/dc/terms/}type', ''),
        }
        return req
    
    def export_to_json(self, requirements: List[Dict], filename: str = "requirements.json"):
        """Export requirements to JSON file"""
        with open(filename, 'w') as f:
            json.dump(requirements, f, indent=2)
        print(f"✅ Exported {len(requirements)} requirements to {filename}")
    
    def export_to_markdown(self, requirements: List[Dict], filename: str = "requirements.md"):
        """Export requirements to Markdown file"""
        with open(filename, 'w') as f:
            f.write("# Requirements from DOORS Next\n\n")
            for req in requirements:
                f.write(f"## {req.get('id', 'N/A')}: {req.get('title', 'Untitled')}\n\n")
                f.write(f"**Status:** {req.get('status', 'N/A')}\n\n")
                f.write(f"**Type:** {req.get('type', 'N/A')}\n\n")
                f.write(f"**Description:**\n{req.get('description', 'No description')}\n\n")
                
                if 'acceptance_criteria' in req:
                    f.write("**Acceptance Criteria:**\n")
                    for criterion in req['acceptance_criteria']:
                        f.write(f"- {criterion}\n")
                    f.write("\n")
                
                f.write("---\n\n")
        
        print(f"✅ Exported {len(requirements)} requirements to {filename}")


if __name__ == "__main__":
    # Example usage
    print("DOORS Next Client - Example Usage\n")
    
    try:
        # Create client from environment variables
        client = DOORSNextClient.from_env()
        
        # Test connection
        print("Testing connection...")
        info = client.get_project_info()
        print(f"Status: {info['status']}")
        print(f"Message: {info['message']}\n")
        
        # Get requirements
        print("Fetching requirements...")
        requirements = client.get_requirements(status="Approved", limit=10)
        
        if requirements:
            print(f"\nFound {len(requirements)} requirements:")
            for req in requirements[:5]:  # Show first 5
                print(f"  - {req.get('id', 'N/A')}: {req.get('title', 'Untitled')}")
            
            # Export to files
            client.export_to_json(requirements)
            client.export_to_markdown(requirements)
        else:
            print("No requirements found or unable to retrieve them")
            print("\nThis might be because:")
            print("1. The API endpoints need adjustment for your DOORS Next version")
            print("2. You need different authentication")
            print("3. The project name is incorrect")
            print("\nPlease check with your DOORS Next administrator")
        
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("\nPlease create a .env file with:")
        print("DOORS_URL=https://goblue.clm.ibmcloud.com/rm")
        print("DOORS_USERNAME=your_username")
        print("DOORS_PASSWORD=your_password")
        print("DOORS_PROJECT=YourProject")
    except Exception as e:
        print(f"❌ Error: {e}")

# Made with Bob
