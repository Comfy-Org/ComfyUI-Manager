"""
Pytest configuration for glob API tests.
"""

import os
import sys
import time
from pathlib import Path

import pytest
import requests

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line(
        "markers", "requires_server: marks tests that require a running ComfyUI server"
    )
    config.addinivalue_line(
        "markers", "priority_high: marks tests as high priority for comprehensive test suites"
    )
    config.addinivalue_line(
        "markers", "priority_medium: marks tests as medium priority"
    )
    config.addinivalue_line(
        "markers", "priority_low: marks tests as low priority"
    )
    config.addinivalue_line(
        "markers", "complex_scenario: marks tests for complex multi-version scenarios"
    )


@pytest.fixture(scope="session")
def server_url():
    """Get server URL from environment or use default."""
    # Support both TEST_SERVER_PORT (for parallel tests) and COMFYUI_TEST_URL (for custom URLs)
    port = os.environ.get("TEST_SERVER_PORT", "8188")
    return os.environ.get("COMFYUI_TEST_URL", f"http://127.0.0.1:{port}")


@pytest.fixture(scope="session")
def custom_nodes_path():
    """Get custom nodes path from environment or use default."""
    default_path = project_root / "tests" / "env" / "ComfyUI" / "custom_nodes"
    return Path(os.environ.get("COMFYUI_CUSTOM_NODES_PATH", str(default_path)))


@pytest.fixture(scope="session", autouse=True)
def check_server_running(server_url):
    """Check if ComfyUI server is running before running tests."""
    try:
        response = requests.get(f"{server_url}/system_stats", timeout=5)
        if response.status_code != 200:
            pytest.exit(f"ComfyUI server not responding at {server_url}", returncode=1)
    except requests.exceptions.RequestException as e:
        pytest.exit(
            f"ComfyUI server not running at {server_url}. Start server with: cd tests/env && ./run.sh",
            returncode=1,
        )


@pytest.fixture(scope="session", autouse=True)
def install_test_package(server_url, custom_nodes_path):
    """
    Install a test package for API tests that require pre-installed packages.

    This fixture runs once per test session and installs ComfyUI_SigmoidOffsetScheduler
    so that tests like test_installed_api_* have at least one package to work with.
    """
    # Wait for check_server_running to complete
    time.sleep(1)

    # Check if package already installed
    try:
        response = requests.get(f"{server_url}/v2/customnode/installed", timeout=5)
        if response.status_code == 200:
            installed = response.json()
            # If we already have packages, skip installation
            if len(installed) > 0:
                print(f"\n✓ Test packages already installed: {len(installed)} packages found")
                return
    except Exception as e:
        print(f"\n⚠ Could not check installed packages: {e}")

    # Install test package
    print(f"\n⚙ Installing test package for session: ComfyUI_SigmoidOffsetScheduler")

    try:
        # Queue installation task
        response = requests.post(
            f"{server_url}/v2/manager/queue/task",
            json={
                "kind": "install",
                "ui_id": "session_test_package",
                "client_id": "test_session",
                "params": {
                    "id": "ComfyUI_SigmoidOffsetScheduler",
                    "version": "1.0.1",
                    "selected_version": "latest",
                },
            },
            timeout=10,
        )

        if response.status_code == 200:
            # Start queue
            requests.get(f"{server_url}/v2/manager/queue/start", timeout=10)

            # Wait for installation to complete (poll for completion)
            max_wait = 30
            start_time = time.time()
            installed_package_path = custom_nodes_path / "ComfyUI_SigmoidOffsetScheduler"

            while time.time() - start_time < max_wait:
                if installed_package_path.exists() and (installed_package_path / ".tracking").exists():
                    print(f"✓ Test package installed successfully")
                    break
                time.sleep(2)
            else:
                print(f"⚠ Test package installation may not have completed")

    except Exception as e:
        print(f"⚠ Could not install test package: {e}")
        print(f"  Some tests may fail due to missing packages")


@pytest.fixture(autouse=True)
def ensure_test_package_exists(server_url, custom_nodes_path, request):
    """
    Function-scoped fixture that ensures test package exists before each test.

    This handles the case where other test fixtures may have cleaned up the
    session test package. Only runs for tests that don't manipulate the
    test package themselves.
    """
    # Skip for tests that manipulate test packages themselves
    skip_tests = [
        # Phase 1: Complex scenarios
        "test_enable_cnr_when_both_disabled",
        "test_enable_nightly_when_both_disabled",
        # Phase 3: Disable complex scenarios
        "test_disable_cnr_when_nightly_disabled",
        # Phase 4: Update complex scenarios
        "test_update_cnr_with_nightly_disabled",
        "test_update_nightly_with_cnr_disabled",
        "test_update_enabled_with_multiple_disabled",
        # Phase 5: Install complex scenarios
        "test_install_new_version_when_both_disabled",
        "test_install_cnr_when_nightly_enabled",
        "test_install_nightly_when_cnr_enabled",
        # Phase 6: Uninstall complex scenarios
        "test_uninstall_removes_all_versions",
        # Phase 7: Complex version switch chains
        "test_cnr_version_upgrade_with_history",
        "test_sequential_version_switch_chain",
        # Queue API tests that use cleanup_package fixture
        "test_install_package_via_queue",
        "test_uninstall_package_via_queue",
        "test_install_uninstall_cycle",
        "test_case_insensitive_operations",
        "test_version_switch_cnr_to_nightly",
        "test_version_switch_between_cnr_versions",
        # Tests that manage their own package setup/cleanup
        "test_installed_api_shows_only_enabled_when_both_exist",
        "test_installed_api_cnr_priority_when_both_disabled",
        "test_installed_api_shows_disabled_when_no_enabled_exists",
    ]

    if request.node.name in skip_tests:
        yield
        return

    # Check if package exists
    test_package_path = custom_nodes_path / "ComfyUI_SigmoidOffsetScheduler"

    # If package doesn't exist, reinstall it
    if not test_package_path.exists():
        print(f"\n🔄 [RESTORE] Test package was removed, reinstalling...")

        try:
            # Queue installation task
            response = requests.post(
                f"{server_url}/v2/manager/queue/task",
                json={
                    "kind": "install",
                    "ui_id": "restore_test_package",
                    "client_id": "test_restore",
                    "params": {
                        "id": "ComfyUI_SigmoidOffsetScheduler",
                        "version": "1.0.1",
                        "selected_version": "latest",
                    },
                },
                timeout=10,
            )

            if response.status_code == 200:
                # Start queue
                requests.get(f"{server_url}/v2/manager/queue/start", timeout=10)

                # Wait for installation to complete
                max_wait = 30
                start_time = time.time()

                while time.time() - start_time < max_wait:
                    if test_package_path.exists() and (test_package_path / ".tracking").exists():
                        print(f"✓ Test package restored successfully")
                        break
                    time.sleep(2)
                else:
                    print(f"⚠ Test package restoration may not have completed")

        except Exception as e:
            print(f"⚠ Could not restore test package: {e}")

    yield


@pytest.fixture
def api_client(server_url):
    """Create API client with base URL."""

    class APIClient:
        def __init__(self, base_url: str):
            self.base_url = base_url
            self.session = requests.Session()

        def post(self, path: str, **kwargs) -> requests.Response:
            """Make POST request to API endpoint."""
            url = f"{self.base_url}{path}"
            return self.session.post(url, **kwargs)

        def get(self, path: str, **kwargs) -> requests.Response:
            """Make GET request to API endpoint."""
            url = f"{self.base_url}{path}"
            return self.session.get(url, **kwargs)

        def queue_task(self, kind: str, ui_id: str, params: dict) -> requests.Response:
            """Queue a task to the manager queue."""
            url = f"{self.base_url}/v2/manager/queue/task"
            payload = {"kind": kind, "ui_id": ui_id, "client_id": "test", "params": params}
            return self.session.post(url, json=payload)

        def start_queue(self) -> requests.Response:
            """Start processing the queue."""
            url = f"{self.base_url}/v2/manager/queue/start"
            return self.session.get(url)

        def get_pending_queue(self) -> requests.Response:
            """Get pending tasks in queue."""
            url = f"{self.base_url}/v2/manager/queue/pending"
            return self.session.get(url)

        def get_queue_history(self) -> requests.Response:
            """Get queue task history."""
            url = f"{self.base_url}/v2/manager/queue/history"
            return self.session.get(url)

        def get_installed_packages(self) -> requests.Response:
            """Get list of installed packages."""
            url = f"{self.base_url}/v2/customnode/installed"
            return self.session.get(url)

    return APIClient(server_url)


@pytest.fixture
def wait_for_queue():
    """Helper to wait for queue processing to complete."""

    def _wait(seconds=3):
        time.sleep(seconds)

    return _wait


@pytest.fixture
def clean_queue(api_client):
    """Clean up pending queue before and after test."""
    # Clear queue before test
    try:
        api_client.start_queue()
        time.sleep(2)
    except Exception:
        pass

    yield

    # Clear queue after test
    try:
        api_client.start_queue()
        time.sleep(2)
    except Exception:
        pass


# ========================================
# Complex Scenario Fixtures
# ========================================

# Test package configuration
TEST_PACKAGE_ID = "ComfyUI_SigmoidOffsetScheduler"
TEST_PACKAGE_CNR_ID = "comfyui_sigmoidoffsetscheduler"

# Dynamic versions (set by session-level setup)
TEST_PACKAGE_OLDEST_VERSION = None  # Third newest version (for Phase 7 history tests)
TEST_PACKAGE_OLD_VERSION = None     # Second newest version
TEST_PACKAGE_NEW_VERSION = None     # Latest version

# Derived version variables (set by initialize_test_versions fixture)
CNR_VERSION = None              # Alias for TEST_PACKAGE_NEW_VERSION
CNR_VERSION_OLD = None          # Alias for TEST_PACKAGE_OLD_VERSION
TEST_PACKAGE_VERSION = None     # Alias for TEST_PACKAGE_NEW_VERSION

# Wait times for operations
WAIT_TIME_SHORT = 3  # seconds for enable/disable
WAIT_TIME_MEDIUM = 8  # seconds for install
WAIT_TIME_LONG = 10  # seconds for update/complex operations


@pytest.fixture(scope="session", autouse=True)
def initialize_test_versions(server_url):
    """
    Session-level fixture to initialize test package versions dynamically.
    This runs once per test session and sets global version variables.
    """
    global TEST_PACKAGE_OLDEST_VERSION, TEST_PACKAGE_OLD_VERSION, TEST_PACKAGE_NEW_VERSION
    global CNR_VERSION, CNR_VERSION_OLD, TEST_PACKAGE_VERSION

    versions = get_available_cnr_versions(server_url, TEST_PACKAGE_ID)

    if not versions:
        pytest.skip(f"Could not fetch versions for {TEST_PACKAGE_ID}")

    # Assign versions based on availability
    TEST_PACKAGE_NEW_VERSION = versions[0] if len(versions) >= 1 else None
    TEST_PACKAGE_OLD_VERSION = versions[1] if len(versions) >= 2 else versions[0]
    TEST_PACKAGE_OLDEST_VERSION = versions[2] if len(versions) >= 3 else versions[-1]

    # Set derived version variables (aliases for backward compatibility)
    CNR_VERSION = TEST_PACKAGE_NEW_VERSION
    CNR_VERSION_OLD = TEST_PACKAGE_OLD_VERSION
    TEST_PACKAGE_VERSION = TEST_PACKAGE_NEW_VERSION

    if len(versions) < 2:
        pytest.skip(f"Need at least 2 versions for testing, found {len(versions)}")

    print(f"\n📦 Test versions initialized:")
    print(f"   - NEW (latest): {TEST_PACKAGE_NEW_VERSION}")
    print(f"   - OLD (2nd): {TEST_PACKAGE_OLD_VERSION}")
    print(f"   - OLDEST (3rd): {TEST_PACKAGE_OLDEST_VERSION}")


@pytest.fixture
def setup_multi_disabled_cnr_and_nightly(api_client, custom_nodes_path):
    """
    Install both CNR and Nightly in disabled state.

    Creates:
        .disabled/ComfyUI_SigmoidOffsetScheduler_1.0.2/ (CNR with .tracking)
        .disabled/ComfyUI_SigmoidOffsetScheduler/ (Nightly with .git)

    Use case: Test 1.1, 1.2 (Multiple Disabled → Enable)
    """
    import shutil

    disabled_path = custom_nodes_path / ".disabled"
    disabled_path.mkdir(exist_ok=True)

    # Cleanup any existing sigmoid packages before starting
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID
    if enabled_package.exists():
        shutil.rmtree(enabled_package)
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)

    # Step 1: Install CNR v1.0.2
    print(f"\n=== Step 1: Installing CNR v{TEST_PACKAGE_NEW_VERSION} ===")
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_multi_cnr",
        params={
            "id": TEST_PACKAGE_ID,
            "version": TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Debug: Check state after CNR install
    print(f"Enabled packages: {list(custom_nodes_path.glob('*Sigmoid*'))}")
    print(f"Disabled packages: {[p.name for p in disabled_path.iterdir() if 'sigmoid' in p.name.lower()]}")

    # Step 2: Disable CNR (move to .disabled/)
    print(f"\n=== Step 2: Disabling CNR ===")
    response = api_client.queue_task(
        kind="disable",
        ui_id="setup_multi_disable_cnr",
        params={"node_name": TEST_PACKAGE_ID},
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)  # Use MEDIUM for disable to ensure completion

    # Debug: Check state after CNR disable
    print(f"Enabled packages: {list(custom_nodes_path.glob('*Sigmoid*'))}")
    print(f"Disabled packages: {[p.name for p in disabled_path.iterdir() if 'sigmoid' in p.name.lower()]}")

    # Step 3: Install Nightly
    print(f"\n=== Step 3: Installing Nightly ===")
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_multi_nightly",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Debug: Check state after Nightly install
    print(f"Enabled packages: {list(custom_nodes_path.glob('*Sigmoid*'))}")
    print(f"Disabled packages: {[p.name for p in disabled_path.iterdir() if 'sigmoid' in p.name.lower()]}")

    # Step 4: Disable Nightly
    print(f"\n=== Step 4: Disabling Nightly ===")
    response = api_client.queue_task(
        kind="disable",
        ui_id="setup_multi_disable_nightly",
        params={"node_name": TEST_PACKAGE_ID},
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)  # Use MEDIUM for disable to ensure completion

    # Debug: Check state after Nightly disable
    print(f"Enabled packages: {list(custom_nodes_path.glob('*Sigmoid*'))}")
    print(f"Disabled packages: {[p.name for p in disabled_path.iterdir() if 'sigmoid' in p.name.lower()]}")

    # Verify both disabled
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID
    assert not enabled_package.exists(), "No package should be enabled"

    # Use case-insensitive search for disabled packages
    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower()
    ]
    assert len(disabled_packages) == 2, (
        f"Both CNR and Nightly should be disabled, found {len(disabled_packages)}: "
        f"{[p.name for p in disabled_packages]}"
    )

    yield

    # Cleanup
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)
    if enabled_package.exists():
        shutil.rmtree(enabled_package)


@pytest.fixture
def setup_cnr_enabled_nightly_disabled(api_client, custom_nodes_path):
    """
    CNR enabled, Nightly disabled state.

    Creates:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR 1.0.1 with .tracking)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly with .git)

    Use case: Test 4.1 (Update CNR with Nightly disabled)
    """
    import shutil

    disabled_path = custom_nodes_path / ".disabled"
    disabled_path.mkdir(exist_ok=True)
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # Cleanup any existing sigmoid packages
    if enabled_package.exists():
        shutil.rmtree(enabled_package)
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)

    # Step 1: Install Nightly first
    print(f"\n=== Step 1: Installing Nightly ===")
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_nightly_first",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Step 2: Install CNR (this will automatically disable Nightly)
    print(f"\n=== Step 2: Installing CNR v{TEST_PACKAGE_OLD_VERSION} (will disable Nightly) ===")
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_cnr_enabled",
        params={
            "id": TEST_PACKAGE_ID,
            "version": TEST_PACKAGE_OLD_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Verify state
    assert enabled_package.exists(), "CNR should be enabled"
    assert (enabled_package / ".tracking").exists(), "CNR should have .tracking"

    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower()
    ]
    assert len(disabled_packages) == 1, f"Nightly should be disabled, found {len(disabled_packages)}"

    print(f"✓ Setup complete: CNR v{TEST_PACKAGE_OLD_VERSION} enabled, Nightly disabled")

    yield

    # Cleanup
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)
    if enabled_package.exists():
        shutil.rmtree(enabled_package)


@pytest.fixture
def setup_nightly_enabled_cnr_disabled(api_client, custom_nodes_path):
    """
    Nightly enabled, CNR disabled state.

    Creates:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (Nightly with .git)
        .disabled/comfyui_sigmoidoffsetscheduler@1_0_2/ (CNR v1.0.2 with .tracking)

    Use case: Test 4.2 (Update Nightly with CNR disabled)
    """
    import shutil

    disabled_path = custom_nodes_path / ".disabled"
    disabled_path.mkdir(exist_ok=True)
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # Cleanup any existing sigmoid packages
    if enabled_package.exists():
        shutil.rmtree(enabled_package)
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)

    # Step 1: Install CNR first
    print(f"\n=== Step 1: Installing CNR v{TEST_PACKAGE_NEW_VERSION} ===")
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_cnr_first",
        params={
            "id": TEST_PACKAGE_ID,
            "version": TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Step 2: Disable CNR
    print(f"\n=== Step 2: Disabling CNR ===")
    response = api_client.queue_task(
        kind="disable",
        ui_id="setup_disable_cnr",
        params={"node_name": TEST_PACKAGE_ID},
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Step 3: Install Nightly (enabled)
    print(f"\n=== Step 3: Installing Nightly ===")
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_nightly_enabled",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Verify state
    assert enabled_package.exists(), "Nightly should be enabled"
    assert (enabled_package / ".git").exists(), "Nightly should have .git"

    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower()
    ]
    assert len(disabled_packages) == 1, f"CNR should be disabled, found {len(disabled_packages)}"

    print(f"✓ Setup complete: Nightly enabled, CNR v{TEST_PACKAGE_NEW_VERSION} disabled")

    yield

    # Cleanup
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)
    if enabled_package.exists():
        shutil.rmtree(enabled_package)


@pytest.fixture
def setup_cnr_enabled_multiple_disabled(api_client, custom_nodes_path):
    """
    Old CNR enabled, multiple versions disabled.

    Creates:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR 1.0.1 with .tracking)
        .disabled/comfyui_sigmoidoffsetscheduler@1_0_0/ (CNR v1.0.0 - simulated)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly with .git)

    Use case: Test 4.3 (Update enabled while multiple disabled exist)

    Note: We'll simulate v1.0.0 by installing v1.0.2 and renaming it.
    """
    import shutil

    disabled_path = custom_nodes_path / ".disabled"
    disabled_path.mkdir(exist_ok=True)
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # Cleanup any existing sigmoid packages
    if enabled_package.exists():
        shutil.rmtree(enabled_package)
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)

    # Step 1: Install Nightly first
    print(f"\n=== Step 1: Installing Nightly ===")
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_multi_nightly",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Step 2: Disable Nightly
    print(f"\n=== Step 2: Disabling Nightly ===")
    response = api_client.queue_task(
        kind="disable",
        ui_id="setup_multi_disable_nightly",
        params={"node_name": TEST_PACKAGE_ID},
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Step 3: Install CNR v1.0.1 (enabled)
    print(f"\n=== Step 3: Installing CNR v{TEST_PACKAGE_OLD_VERSION} (enabled) ===")
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_multi_current_cnr",
        params={
            "id": TEST_PACKAGE_ID,
            "version": TEST_PACKAGE_OLD_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Step 4: Manually create a simulated old CNR version in .disabled/
    # Copy the current enabled CNR and rename it to simulate v1.0.0
    print(f"\n=== Step 4: Creating simulated old CNR version ===")
    simulated_old_cnr = disabled_path / "comfyui_sigmoidoffsetscheduler@1_0_0"
    if enabled_package.exists():
        import shutil
        shutil.copytree(enabled_package, simulated_old_cnr)
        print(f"Created simulated old CNR at {simulated_old_cnr.name}")

    # Verify state
    assert enabled_package.exists(), "CNR v1.0.1 should be enabled"
    assert (enabled_package / ".tracking").exists(), "CNR should have .tracking"

    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower()
    ]
    assert len(disabled_packages) == 2, (
        f"Should have 2 disabled packages (old CNR + Nightly), found {len(disabled_packages)}: "
        f"{[p.name for p in disabled_packages]}"
    )

    print(f"✓ Setup complete: CNR v{TEST_PACKAGE_OLD_VERSION} enabled, 2 versions disabled")

    yield

    # Cleanup
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)
    if enabled_package.exists():
        shutil.rmtree(enabled_package)

@pytest.fixture
def setup_nightly_enabled_only(api_client, custom_nodes_path):
    """
    Install Nightly version only (enabled state).

    Creates:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (Nightly with .git)

    Use case: Test 5.1 (Nightly enabled → Install CNR)
    """
    import shutil

    disabled_path = custom_nodes_path / ".disabled"
    disabled_path.mkdir(exist_ok=True)
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # Cleanup any existing sigmoid packages
    if enabled_package.exists():
        shutil.rmtree(enabled_package)
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)

    # Install Nightly
    print(f"\n=== Installing Nightly (enabled) ===")
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_nightly_only",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Verify state
    assert enabled_package.exists(), "Nightly should be enabled"
    assert (enabled_package / ".git").exists(), "Nightly should have .git directory"

    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower()
    ]
    assert len(disabled_packages) == 0, (
        f"No packages should be disabled, found {len(disabled_packages)}: "
        f"{[p.name for p in disabled_packages]}"
    )

    print(f"✓ Setup complete: Nightly enabled only")

    yield

    # Cleanup
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)
    if enabled_package.exists():
        shutil.rmtree(enabled_package)


@pytest.fixture
def setup_cnr_enabled_only(api_client, custom_nodes_path):
    """
    Install CNR version only (enabled state).

    Creates:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR v1.0.2 with .tracking)

    Use case: Test 5.2 (CNR enabled → Install Nightly)
    """
    import shutil

    disabled_path = custom_nodes_path / ".disabled"
    disabled_path.mkdir(exist_ok=True)
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # Cleanup any existing sigmoid packages
    if enabled_package.exists():
        shutil.rmtree(enabled_package)
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)

    # Install CNR v1.0.2
    print(f"\n=== Installing CNR v{TEST_PACKAGE_NEW_VERSION} (enabled) ===")
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_cnr_only",
        params={
            "id": TEST_PACKAGE_ID,
            "version": TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Verify state
    assert enabled_package.exists(), "CNR should be enabled"
    assert (enabled_package / ".tracking").exists(), "CNR should have .tracking file"

    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower()
    ]
    assert len(disabled_packages) == 0, (
        f"No packages should be disabled, found {len(disabled_packages)}: "
        f"{[p.name for p in disabled_packages]}"
    )

    print(f"✓ Setup complete: CNR v{TEST_PACKAGE_NEW_VERSION} enabled only")

    yield

    # Cleanup
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)
    if enabled_package.exists():
        shutil.rmtree(enabled_package)



# ============================================================================
# Dynamic Version Management Helpers
# ============================================================================


def get_installed_version(package_path) -> str | None:
    """
    Get currently installed version from pyproject.toml.

    Args:
        package_path: Path to the package directory (str or Path object)

    Returns:
        Version string (e.g., "1.0.2") or None if not found

    Example:
        >>> version = get_installed_version(custom_nodes_path / "ComfyUI_SigmoidOffsetScheduler")
        >>> print(version)  # "1.0.2"
    """
    import re
    from pathlib import Path

    # Convert to Path if string
    if isinstance(package_path, str):
        package_path = Path(package_path)

    pyproject = package_path / "pyproject.toml"
    if not pyproject.exists():
        return None

    content = pyproject.read_text()
    match = re.search(r'version\s*=\s*"([^"]+)"', content)
    return match.group(1) if match else None


def get_available_cnr_versions(server_url: str, package_id: str) -> list[str]:
    """
    Get list of available CNR versions for a package from ComfyRegistry.

    This function queries the ComfyRegistry API to get all available versions.

    Args:
        server_url: ComfyUI server URL (unused, kept for API compatibility)
        package_id: Package identifier (e.g., "ComfyUI_SigmoidOffsetScheduler")

    Returns:
        List of version strings sorted newest first (e.g., ["1.0.2", "1.0.1"])

    Example:
        >>> versions = get_available_cnr_versions(server_url, "ComfyUI_SigmoidOffsetScheduler")
        >>> print(versions)  # ["1.0.2", "1.0.1", "1.0.0"]
    """
    from packaging import version as pkg_version

    try:
        # Import CNR utils
        from comfyui_manager.common import cnr_utils

        # Query ComfyRegistry for all versions
        version_data = cnr_utils.all_versions_of_node(package_id)

        if version_data and isinstance(version_data, list):
            # Extract version strings from response
            # Response format: [{"version": "1.0.2", ...}, {"version": "1.0.1", ...}]
            versions = [item.get('version') for item in version_data if 'version' in item]

            # Sort by semantic version (newest first)
            return sorted(versions, key=lambda v: pkg_version.parse(v), reverse=True)

    except Exception as e:
        print(f"Info: ComfyRegistry query failed for {package_id}: {e}")

    # Fallback: Known versions for test package
    if package_id == "ComfyUI_SigmoidOffsetScheduler":
        print(f"Info: Using known versions for {package_id}")
        return ["1.0.2", "1.0.1", "1.0.0"]

    print(f"Warning: Could not fetch versions for {package_id}")
    return []


def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two semantic versions.

    Args:
        v1: First version string (e.g., "1.0.1")
        v2: Second version string (e.g., "1.0.2")

    Returns:
        -1 if v1 < v2
         0 if v1 == v2
         1 if v1 > v2

    Example:
        >>> compare_versions("1.0.1", "1.0.2")
        -1
        >>> compare_versions("1.0.2", "1.0.1")
        1
        >>> compare_versions("1.0.1", "1.0.1")
        0
    """
    from packaging import version

    v1_obj = version.parse(v1)
    v2_obj = version.parse(v2)

    if v1_obj < v2_obj:
        return -1
    elif v1_obj > v2_obj:
        return 1
    else:
        return 0


def assert_version_increased(version_before: str, version_after: str, context: str = ""):
    """
    Assert that version increased after an operation.

    Args:
        version_before: Version before operation
        version_after: Version after operation
        context: Additional context for error message

    Raises:
        AssertionError: If version did not increase

    Example:
        >>> assert_version_increased("1.0.1", "1.0.2", "after upgrade")
    """
    assert version_after is not None, f"Version after operation is None {context}"
    assert version_before is not None, f"Version before operation is None {context}"
    assert version_after != version_before, (
        f"Version did not change {context}: {version_before} → {version_after}"
    )
    assert compare_versions(version_after, version_before) > 0, (
        f"Version did not increase {context}: {version_before} → {version_after}"
    )


def assert_version_decreased(version_before: str, version_after: str, context: str = ""):
    """
    Assert that version decreased after an operation (downgrade).

    Args:
        version_before: Version before operation
        version_after: Version after operation
        context: Additional context for error message

    Raises:
        AssertionError: If version did not decrease

    Example:
        >>> assert_version_decreased("1.0.2", "1.0.1", "after downgrade")
    """
    assert version_after is not None, f"Version after operation is None {context}"
    assert version_before is not None, f"Version before operation is None {context}"
    assert version_after != version_before, (
        f"Version did not change {context}: {version_before} → {version_after}"
    )
    assert compare_versions(version_after, version_before) < 0, (
        f"Version did not decrease {context}: {version_before} → {version_after}"
    )
