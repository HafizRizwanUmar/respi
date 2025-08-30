#!/usr/bin/env python3
"""
API Testing Script for Ad Filter System
Tests all endpoints to ensure proper functionality
"""

import requests
import json
import time
import sys
from typing import Dict, List

class AdFilterAPITester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.auth_token = None
        
    def test_health_check(self) -> bool:
        """Test the health check endpoint."""
        print("🔍 Testing health check endpoint...")
        try:
            response = self.session.get(f"{self.base_url}/api/health")
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Health check passed: {data}")
                return True
            else:
                print(f"❌ Health check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Health check error: {e}")
            return False
    
    def test_login(self, username: str = "admin", password: str = "admin123") -> bool:
        """Test user login."""
        print("🔐 Testing login endpoint...")
        try:
            response = self.session.post(
                f"{self.base_url}/api/login",
                json={"username": username, "password": password}
            )
            if response.status_code == 200:
                data = response.json()
                self.auth_token = data.get("access_token")
                print(f"✅ Login successful: {data['user']}")
                return True
            else:
                print(f"❌ Login failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Login error: {e}")
            return False
    
    def test_predict_endpoint(self) -> bool:
        """Test the ML prediction endpoint."""
        print("🧠 Testing ML prediction endpoint...")
        test_domains = [
            "ads.google.com",
            "doubleclick.net", 
            "github.com",
            "stackoverflow.com",
            "malicious-ads.example.com"
        ]
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/predict",
                json={"domains": test_domains}
            )
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Prediction successful:")
                print(f"   Blocked domains: {data['block_domains']}")
                print(f"   Analysis scores: {data['analysis']}")
                return True
            else:
                print(f"❌ Prediction failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Prediction error: {e}")
            return False
    
    def test_stats_endpoint(self) -> bool:
        """Test the statistics endpoint."""
        print("📊 Testing statistics endpoint...")
        try:
            response = self.session.get(f"{self.base_url}/api/stats")
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Stats retrieved:")
                print(f"   ML stats: {data.get('ml_stats', {})}")
                if 'pihole' in data:
                    print(f"   Pi-hole stats: {data['pihole']}")
                return True
            else:
                print(f"❌ Stats failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Stats error: {e}")
            return False
    
    def test_recent_queries(self) -> bool:
        """Test the recent queries endpoint."""
        print("📝 Testing recent queries endpoint...")
        try:
            response = self.session.get(f"{self.base_url}/api/recent-queries?limit=10")
            if response.status_code == 200:
                data = response.json()
                queries = data.get('queries', [])
                print(f"✅ Recent queries retrieved: {len(queries)} queries")
                if queries:
                    print(f"   Latest query: {queries[0]}")
                return True
            else:
                print(f"❌ Recent queries failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Recent queries error: {e}")
            return False
    
    def test_blocklist_management(self) -> bool:
        """Test blocklist add/remove functionality."""
        print("🚫 Testing blocklist management...")
        test_domain = "test-block.example.com"
        
        try:
            # Test adding domain
            response = self.session.post(
                f"{self.base_url}/api/blocklist",
                json={"domain": test_domain, "action": "add"}
            )
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Domain added to blocklist: {data['message']}")
                
                # Test removing domain
                response = self.session.post(
                    f"{self.base_url}/api/blocklist",
                    json={"domain": test_domain, "action": "remove"}
                )
                if response.status_code == 200:
                    data = response.json()
                    print(f"✅ Domain removed from blocklist: {data['message']}")
                    return True
                else:
                    print(f"❌ Domain removal failed: {response.status_code}")
                    return False
            else:
                print(f"❌ Domain addition failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Blocklist management error: {e}")
            return False
    
    def test_dashboard_access(self) -> bool:
        """Test dashboard page access."""
        print("🌐 Testing dashboard access...")
        try:
            response = self.session.get(f"{self.base_url}/")
            if response.status_code == 200:
                if "Ad Filter Dashboard" in response.text:
                    print("✅ Dashboard accessible")
                    return True
                else:
                    print("❌ Dashboard content not found")
                    return False
            else:
                print(f"❌ Dashboard access failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Dashboard access error: {e}")
            return False
    
    def run_all_tests(self) -> Dict[str, bool]:
        """Run all tests and return results."""
        print("🚀 Starting Ad Filter API Tests...\n")
        
        results = {}
        
        # Test basic connectivity
        results['health_check'] = self.test_health_check()
        print()
        
        # Test dashboard
        results['dashboard'] = self.test_dashboard_access()
        print()
        
        # Test authentication
        results['login'] = self.test_login()
        print()
        
        # Test ML prediction
        results['prediction'] = self.test_predict_endpoint()
        print()
        
        # Test statistics
        results['stats'] = self.test_stats_endpoint()
        print()
        
        # Test recent queries
        results['recent_queries'] = self.test_recent_queries()
        print()
        
        # Test blocklist management
        results['blocklist'] = self.test_blocklist_management()
        print()
        
        # Print summary
        print("📋 Test Summary:")
        print("=" * 50)
        passed = 0
        total = len(results)
        
        for test_name, passed_test in results.items():
            status = "✅ PASS" if passed_test else "❌ FAIL"
            print(f"{test_name.replace('_', ' ').title()}: {status}")
            if passed_test:
                passed += 1
        
        print("=" * 50)
        print(f"Tests passed: {passed}/{total}")
        
        if passed == total:
            print("🎉 All tests passed! Your API is working correctly.")
        else:
            print("⚠️  Some tests failed. Check the logs above for details.")
        
        return results

def main():
    """Main function to run tests."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Ad Filter API")
    parser.add_argument(
        "--url", 
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--username",
        default="admin",
        help="Username for login test (default: admin)"
    )
    parser.add_argument(
        "--password",
        default="admin123",
        help="Password for login test (default: admin123)"
    )
    
    args = parser.parse_args()
    
    # Test with provided URL
    tester = AdFilterAPITester(args.url)
    results = tester.run_all_tests()
    
    # Exit with error code if any tests failed
    if not all(results.values()):
        sys.exit(1)

if __name__ == "__main__":
    main()

