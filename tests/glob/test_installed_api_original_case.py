"""
Test that /installed API preserves original case in cnr_id.

This test verifies that the `/v2/customnode/installed` API:
1. Returns cnr_id with original case (e.g., "ComfyUI_SigmoidOffsetScheduler")
2. Does NOT include an "original_name" field
3. Maintains frontend compatibility with PyPI baseline

This matches the PyPI 4.0.3b1 baseline behavior.
"""

import requests


def test_installed_api_preserves_original_case(server_url):
    """Test that /installed API returns cnr_id with original case."""
    response = requests.get(f"{server_url}/v2/customnode/installed")
    assert response.status_code == 200

    installed = response.json()
    assert len(installed) > 0, "Should have at least one installed package"

    # Check each installed package
    for package_key, package_info in installed.items():
        # Verify cnr_id field exists
        assert 'cnr_id' in package_info, f"Package {package_key} should have cnr_id field"

        cnr_id = package_info['cnr_id']

        # Verify cnr_id preserves original case (contains uppercase letters)
        # For ComfyUI_SigmoidOffsetScheduler, it should NOT be all lowercase
        if 'comfyui' in cnr_id.lower():
            # If it contains "comfyui", it should have uppercase letters
            assert cnr_id != cnr_id.lower(), \
                f"cnr_id '{cnr_id}' should preserve original case, not be normalized to lowercase"

        # Verify no original_name field in response (PyPI baseline)
        assert 'original_name' not in package_info, \
            f"Package {package_key} should NOT have original_name field for frontend compatibility"


def test_cnr_package_original_case(server_url):
    """Test specifically that CNR packages preserve original case."""
    response = requests.get(f"{server_url}/v2/customnode/installed")
    assert response.status_code == 200

    installed = response.json()

    # Find a CNR package (has version like "1.0.1")
    cnr_packages = {k: v for k, v in installed.items()
                   if v.get('ver', '').count('.') >= 2}

    assert len(cnr_packages) > 0, "Should have at least one CNR package for testing"

    for package_key, package_info in cnr_packages.items():
        cnr_id = package_info['cnr_id']

        # CNR packages should have original case preserved
        # Example: "ComfyUI_SigmoidOffsetScheduler" not "comfyui_sigmoidoffsetscheduler"
        assert any(c.isupper() for c in cnr_id), \
            f"CNR package cnr_id '{cnr_id}' should contain uppercase letters"


def test_nightly_package_original_case(server_url):
    """Test specifically that Nightly packages preserve original case."""
    response = requests.get(f"{server_url}/v2/customnode/installed")
    assert response.status_code == 200

    installed = response.json()

    # Find a Nightly package (key contains "@nightly")
    nightly_packages = {k: v for k, v in installed.items() if '@nightly' in k}

    if len(nightly_packages) == 0:
        # No nightly packages installed, skip test
        return

    for package_key, package_info in nightly_packages.items():
        cnr_id = package_info['cnr_id']

        # Nightly packages should also have original case preserved
        # Example: "ComfyUI_SigmoidOffsetScheduler" not "comfyui_sigmoidoffsetscheduler"
        assert any(c.isupper() for c in cnr_id), \
            f"Nightly package cnr_id '{cnr_id}' should contain uppercase letters"


def test_api_response_structure_matches_pypi(server_url):
    """Test that API response structure matches PyPI 4.0.3b1 baseline."""
    response = requests.get(f"{server_url}/v2/customnode/installed")
    assert response.status_code == 200

    installed = response.json()

    # Skip test if no packages installed (may happen in parallel environments)
    if len(installed) == 0:
        pytest.skip("No packages installed - skipping structure validation test")

    # Check first package structure
    first_package = next(iter(installed.values()))

    # Required fields from PyPI baseline
    required_fields = {'ver', 'cnr_id', 'aux_id', 'enabled'}
    actual_fields = set(first_package.keys())

    assert required_fields == actual_fields, \
        f"API response fields should match PyPI baseline: {required_fields}, got: {actual_fields}"
