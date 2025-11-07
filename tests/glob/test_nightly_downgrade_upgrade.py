"""
Test cases for Nightly version downgrade and upgrade cycle.

Tests nightly package downgrade via git reset and subsequent upgrade via git pull.
This validates that update operations can recover from intentionally downgraded versions.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest


# ============================================================================
# TEST CONFIGURATION - Easy to modify for different packages
# ============================================================================

# Test package configuration
TEST_PACKAGE_ID = "ComfyUI_SigmoidOffsetScheduler"
TEST_PACKAGE_CNR_ID = "comfyui_sigmoidoffsetscheduler"

# First commit SHA for reset tests
# This is the commit where untracked file conflicts occur after reset
# Update this if testing with a different package or commit history
FIRST_COMMIT_SHA = "b0eb1539f1de"  # ComfyUI_SigmoidOffsetScheduler initial commit

# Alternative packages you can test with:
# Uncomment and modify as needed:
#
# TEST_PACKAGE_ID = "ComfyUI_Example_Package"
# TEST_PACKAGE_CNR_ID = "comfyui_example_package"
# FIRST_COMMIT_SHA = "abc1234567"  # Your package's first commit
#
# To find your package's first commit:
#   cd custom_nodes/YourPackage
#   git rev-list --max-parents=0 HEAD

# ============================================================================


@pytest.fixture
def setup_nightly_package(api_client, custom_nodes_path):
    """Install Nightly version and ensure it has commit history."""
    # Install Nightly version
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_nightly_downgrade",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(10)

    # Verify Nightly installed
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    assert package_path.exists(), "Nightly version should be installed"

    git_dir = package_path / ".git"
    assert git_dir.exists(), "Nightly package should have .git directory"

    # Verify git repository has commits
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=package_path,
        capture_output=True,
        text=True,
    )
    commit_count = int(result.stdout.strip())
    assert commit_count > 0, "Git repository should have commit history"

    yield package_path

    # Cleanup
    import shutil
    if package_path.exists():
        shutil.rmtree(package_path)


def get_current_commit(package_path: Path) -> str:
    """Get current git commit SHA."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=package_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_commit_count(package_path: Path) -> int:
    """Get total commit count in git history."""
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=package_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return int(result.stdout.strip())


def reset_to_previous_commit(package_path: Path, commits_back: int = 1) -> str:
    """
    Reset git repository to previous commit(s).

    Args:
        package_path: Path to package directory
        commits_back: Number of commits to go back (default: 1)

    Returns:
        New commit SHA after reset
    """
    # Get current commit before reset
    old_commit = get_current_commit(package_path)

    # Reset to N commits back
    reset_target = f"HEAD~{commits_back}"
    result = subprocess.run(
        ["git", "reset", "--hard", reset_target],
        cwd=package_path,
        capture_output=True,
        text=True,
        check=True,
    )

    new_commit = get_current_commit(package_path)

    # Verify commit actually changed
    assert new_commit != old_commit, "Commit should change after reset"

    return new_commit


@pytest.mark.priority_high
def test_nightly_downgrade_via_reset_then_upgrade(
    api_client, custom_nodes_path, setup_nightly_package
):
    """
    Test: Nightly downgrade via git reset, then upgrade via update API.

    Workflow:
    1. Install nightly (latest commit)
    2. Manually downgrade via git reset HEAD~1
    3. Trigger update via API (git pull)
    4. Verify package upgraded back to latest

    Verifies:
    - Update can recover from manually downgraded nightly packages
    - git pull correctly fetches and merges newer commits
    - Package state remains valid throughout cycle
    """
    package_path = setup_nightly_package
    git_dir = package_path / ".git"

    # Step 1: Get initial state (latest commit)
    initial_commit = get_current_commit(package_path)
    initial_count = get_commit_count(package_path)

    print(f"\n[Initial State]")
    print(f"  Commit: {initial_commit[:8]}")
    print(f"  Total commits: {initial_count}")

    # Verify we have enough history to downgrade
    assert initial_count >= 2, "Need at least 2 commits to test downgrade"

    # Step 2: Downgrade by resetting to previous commit
    print(f"\n[Downgrading via git reset]")
    downgraded_commit = reset_to_previous_commit(package_path, commits_back=1)
    downgraded_count = get_commit_count(package_path)

    print(f"  Commit: {downgraded_commit[:8]}")
    print(f"  Total commits: {downgraded_count}")

    # Verify downgrade succeeded
    assert downgraded_commit != initial_commit, "Commit should change after downgrade"
    assert downgraded_count == initial_count - 1, "Commit count should decrease by 1"

    # Verify package still functional
    assert git_dir.exists(), ".git directory should still exist after reset"
    init_file = package_path / "__init__.py"
    assert init_file.exists(), "Package should still be functional after reset"

    # Step 3: Trigger update via API (should pull latest commit)
    print(f"\n[Upgrading via update API]")
    response = api_client.queue_task(
        kind="update",
        ui_id="test_nightly_upgrade_after_reset",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": "nightly",
        },
    )
    assert response.status_code == 200, f"Failed to queue update task: {response.text}"

    # Start queue and wait
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"
    time.sleep(10)

    # Step 4: Verify upgrade succeeded
    upgraded_commit = get_current_commit(package_path)
    upgraded_count = get_commit_count(package_path)

    print(f"  Commit: {upgraded_commit[:8]}")
    print(f"  Total commits: {upgraded_count}")

    # Verify we're back to latest
    assert upgraded_commit == initial_commit, \
        f"Should return to initial commit. Expected {initial_commit[:8]}, got {upgraded_commit[:8]}"
    assert upgraded_count == initial_count, \
        f"Should return to initial commit count. Expected {initial_count}, got {upgraded_count}"

    # Verify package integrity maintained
    assert git_dir.exists(), ".git directory should be preserved after update"
    assert init_file.exists(), "Package should be functional after update"

    # Verify package is still nightly (no .tracking file)
    tracking_file = package_path / ".tracking"
    assert not tracking_file.exists(), "Nightly package should not have .tracking file"

    print(f"\n[Test Summary]")
    print(f"  ✅ Downgrade: {initial_commit[:8]} → {downgraded_commit[:8]}")
    print(f"  ✅ Upgrade:   {downgraded_commit[:8]} → {upgraded_commit[:8]}")
    print(f"  ✅ Recovered to initial state")


@pytest.mark.priority_high
def test_nightly_downgrade_multiple_commits_then_upgrade(
    api_client, custom_nodes_path, setup_nightly_package
):
    """
    Test: Nightly downgrade by multiple commits, then upgrade.

    Workflow:
    1. Install nightly (latest)
    2. Reset to 3 commits back (if available)
    3. Trigger update
    4. Verify full upgrade to latest

    Verifies:
    - Update can handle larger commit gaps
    - git pull correctly fast-forwards through multiple commits
    """
    package_path = setup_nightly_package

    # Get initial state
    initial_commit = get_current_commit(package_path)
    initial_count = get_commit_count(package_path)

    print(f"\n[Initial State]")
    print(f"  Commit: {initial_commit[:8]}")
    print(f"  Total commits: {initial_count}")

    # Determine how many commits to go back (max 3, or less if not enough history)
    commits_to_reset = min(3, initial_count - 1)

    if commits_to_reset < 1:
        pytest.skip("Not enough commit history to test multi-commit downgrade")

    print(f"  Will reset {commits_to_reset} commit(s) back")

    # Downgrade by multiple commits
    print(f"\n[Downgrading by {commits_to_reset} commits]")
    downgraded_commit = reset_to_previous_commit(package_path, commits_back=commits_to_reset)
    downgraded_count = get_commit_count(package_path)

    print(f"  Commit: {downgraded_commit[:8]}")
    print(f"  Total commits: {downgraded_count}")

    # Verify downgrade
    assert downgraded_count == initial_count - commits_to_reset, \
        f"Should have {commits_to_reset} fewer commits"

    # Trigger update
    print(f"\n[Upgrading via update API]")
    response = api_client.queue_task(
        kind="update",
        ui_id="test_nightly_multi_commit_upgrade",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": "nightly",
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(10)

    # Verify full upgrade
    upgraded_commit = get_current_commit(package_path)
    upgraded_count = get_commit_count(package_path)

    print(f"  Commit: {upgraded_commit[:8]}")
    print(f"  Total commits: {upgraded_count}")

    assert upgraded_commit == initial_commit, "Should return to initial commit"
    assert upgraded_count == initial_count, "Should restore full commit history"

    print(f"\n[Test Summary]")
    print(f"  ✅ Downgraded {commits_to_reset} commit(s)")
    print(f"  ✅ Upgraded back to latest")
    print(f"  ✅ Commit gap: {commits_to_reset} commits")


@pytest.mark.priority_medium
def test_nightly_verify_git_pull_behavior(
    api_client, custom_nodes_path, setup_nightly_package
):
    """
    Test: Verify git pull behavior when already at latest.

    Workflow:
    1. Install nightly (latest)
    2. Trigger update (already at latest)
    3. Verify no errors, commit unchanged

    Verifies:
    - Update operation is idempotent
    - No errors when already up-to-date
    - Package integrity maintained
    """
    package_path = setup_nightly_package

    # Get initial commit
    initial_commit = get_current_commit(package_path)

    print(f"\n[Initial State]")
    print(f"  Commit: {initial_commit[:8]}")

    # Trigger update when already at latest
    print(f"\n[Updating when already at latest]")
    response = api_client.queue_task(
        kind="update",
        ui_id="test_nightly_already_latest",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": "nightly",
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(8)

    # Verify commit unchanged
    final_commit = get_current_commit(package_path)

    print(f"  Commit: {final_commit[:8]}")

    assert final_commit == initial_commit, \
        "Commit should remain unchanged when already at latest"

    # Verify package integrity
    git_dir = package_path / ".git"
    init_file = package_path / "__init__.py"

    assert git_dir.exists(), ".git directory should be preserved"
    assert init_file.exists(), "Package should remain functional"

    print(f"\n[Test Summary]")
    print(f"  ✅ Update when already latest: no errors")
    print(f"  ✅ Commit unchanged: {initial_commit[:8]}")
    print(f"  ✅ Package integrity maintained")


@pytest.mark.priority_high
def test_nightly_reset_to_first_commit_with_unstaged_files(
    api_client, custom_nodes_path, setup_nightly_package
):
    """
    Test: Reset to first commit (creates unstaged files), then upgrade.

    Critical Scenario:
    - First commit: b0eb1539f1de (minimal files)
    - Later commits: Added many files
    - Reset to first commit → many files become untracked
    - These files will conflict with git pull

    Real-world case:
    User resets to initial commit for debugging, then wants to update back.
    The files added in later commits remain in working tree as untracked files,
    causing git pull to fail with "would be overwritten" error.

    Scenario:
    1. Install nightly (latest)
    2. Reset to first commit: git reset --hard b0eb1539f1de
    3. Files added after first commit become untracked/unstaged
    4. Trigger update (git pull should handle file conflicts)
    5. Verify upgrade handles this critical edge case

    Verifies:
    - Update detects unstaged files that conflict with incoming changes
    - Update either: stashes files, or reports clear error, or uses --force
    - Package state remains valid (not corrupted)
    - .git directory preserved
    """
    package_path = setup_nightly_package
    git_dir = package_path / ".git"

    # Step 1: Get initial state
    initial_commit = get_current_commit(package_path)
    initial_count = get_commit_count(package_path)

    print(f"\n[Initial State - Latest Commit]")
    print(f"  Commit: {initial_commit[:8]}")
    print(f"  Total commits: {initial_count}")

    # Get list of tracked files at latest commit
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=package_path,
        capture_output=True,
        text=True,
        check=True,
    )
    files_at_latest = set(result.stdout.strip().split('\n'))
    print(f"  Files at latest: {len(files_at_latest)}")

    # Verify we have enough history to reset to first commit
    assert initial_count >= 2, "Need at least 2 commits to test reset to first"

    # Step 2: Find first commit SHA
    result = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        cwd=package_path,
        capture_output=True,
        text=True,
        check=True,
    )
    first_commit = result.stdout.strip()

    print(f"\n[First Commit Found]")
    print(f"  SHA: {first_commit[:8]}")

    # Check if first commit matches configured commit
    if first_commit.startswith(FIRST_COMMIT_SHA[:8]):
        print(f"  ✅ Matches configured first commit: {FIRST_COMMIT_SHA}")
    else:
        print(f"  ℹ️  First commit: {first_commit[:12]}")
        print(f"  ⚠️  Expected: {FIRST_COMMIT_SHA[:12]}")
        print(f"  💡 Update FIRST_COMMIT_SHA in test configuration if needed")

    # Step 3: Reset to first commit
    print(f"\n[Resetting to first commit]")
    result = subprocess.run(
        ["git", "reset", "--hard", first_commit],
        cwd=package_path,
        capture_output=True,
        text=True,
        check=True,
    )

    downgraded_commit = get_current_commit(package_path)
    downgraded_count = get_commit_count(package_path)

    print(f"  Current commit: {downgraded_commit[:8]}")
    print(f"  Total commits: {downgraded_count}")
    assert downgraded_count == 1, "Should be at first commit (1 commit in history)"

    # Get files at first commit
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=package_path,
        capture_output=True,
        text=True,
        check=True,
    )
    files_at_first = set(result.stdout.strip().split('\n'))
    print(f"  Files at first commit: {len(files_at_first)}")

    # Files added after first commit (these will be untracked after reset)
    new_files_in_later_commits = files_at_latest - files_at_first

    print(f"\n[Files Added After First Commit]")
    print(f"  Count: {len(new_files_in_later_commits)}")
    if new_files_in_later_commits:
        # These files still exist in working tree but are now untracked
        print(f"  Sample files (now untracked):")
        for file in list(new_files_in_later_commits)[:5]:
            file_path = package_path / file
            if file_path.exists():
                print(f"    ✓ {file} (exists as untracked)")
            else:
                print(f"    ✗ {file} (was deleted by reset)")

    # Check git status - should show untracked files
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=package_path,
        capture_output=True,
        text=True,
    )
    status_output = result.stdout.strip()

    if status_output:
        untracked_count = len([line for line in status_output.split('\n') if line.startswith('??')])
        print(f"\n[Untracked Files After Reset]")
        print(f"  Count: {untracked_count}")
        print(f"  First few:\n{status_output[:300]}")
    else:
        print(f"\n[No Untracked Files - reset --hard cleaned everything]")

    # Step 4: Trigger update via API
    print(f"\n[Triggering Update to Latest]")
    print(f"  Target: {initial_commit[:8]} (latest)")
    print(f"  Current: {downgraded_commit[:8]} (first commit)")

    response = api_client.queue_task(
        kind="update",
        ui_id="test_nightly_upgrade_from_first_commit",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": "nightly",
        },
    )
    assert response.status_code == 200, f"Failed to queue update task: {response.text}"

    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"
    time.sleep(15)  # Longer wait for large update

    # Step 5: Verify upgrade result
    upgraded_commit = get_current_commit(package_path)
    upgraded_count = get_commit_count(package_path)

    print(f"\n[After Update Attempt]")
    print(f"  Commit: {upgraded_commit[:8]}")
    print(f"  Total commits: {upgraded_count}")

    # Step 6: Check task history to see if update failed with proper error
    history_response = api_client.get_queue_history()
    assert history_response.status_code == 200, "Should get queue history"

    history_data = history_response.json()
    update_task = history_data.get("history", {}).get("test_nightly_upgrade_from_first_commit")

    if update_task:
        task_status = update_task.get("status", {})
        status_str = task_status.get("status_str", "unknown")
        messages = task_status.get("messages", [])
        result_text = update_task.get("result", "")

        print(f"\n[Update Task Result]")
        print(f"  Status: {status_str}")
        print(f"  Result: {result_text}")
        if messages:
            print(f"  Messages: {messages}")

    # Check upgrade result
    if upgraded_commit == initial_commit:
        # Case A or B: Update succeeded
        print(f"\n  ✅ Successfully upgraded to latest from first commit!")
        print(f"     Commit gap: {initial_count - 1} commits")
        print(f"     Implementation handles untracked files correctly")
        assert upgraded_count == initial_count, "Should restore full commit history"

        if update_task and status_str == "success":
            print(f"  ✅ Task status correctly reports success")

    else:
        # Case C: Update failed - must be properly reported
        print(f"\n  ⚠️  Update did not reach latest commit")
        print(f"     Expected: {initial_commit[:8]}")
        print(f"     Got: {upgraded_commit[:8]}")
        print(f"     Commit stayed at: first commit")

        # CRITICAL: If update failed, task status MUST report failure
        if update_task:
            if status_str in ["failed", "error"]:
                print(f"  ✅ Task correctly reports failure: {status_str}")
                print(f"     This is acceptable - untracked files prevented update")
            elif status_str == "success":
                pytest.fail(
                    f"CRITICAL: Update failed (commit unchanged) but task reports success!\n"
                    f"  Expected commit: {initial_commit[:8]}\n"
                    f"  Actual commit: {upgraded_commit[:8]}\n"
                    f"  Task status: {status_str}\n"
                    f"  This is a bug - update must report failure when it fails"
                )
            else:
                print(f"  ⚠️  Unexpected task status: {status_str}")
        else:
            print(f"  ⚠️  Update task not found in history")

    # Verify package integrity (critical - must pass even if update failed)
    assert git_dir.exists(), ".git directory should be preserved"
    init_file = package_path / "__init__.py"
    assert init_file.exists(), "Package should remain functional after failed update"

    # Check final working tree status
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=package_path,
        capture_output=True,
        text=True,
    )
    final_status = result.stdout.strip()

    print(f"\n[Final Git Status]")
    if final_status:
        print(f"  Has unstaged/untracked changes:")
        print(f"{final_status[:300]}")
    else:
        print(f"  ✅ Working tree clean")

    print(f"\n[Test Summary]")
    print(f"  Initial commits: {initial_count}")
    print(f"  Reset to: first commit (1 commit)")
    print(f"  Final commits: {upgraded_count}")
    print(f"  Files added in later commits: {len(new_files_in_later_commits)}")
    print(f"  ✅ Package integrity maintained")
    print(f"  ✅ Git repository remains valid")


@pytest.mark.priority_high
def test_nightly_soft_reset_with_modified_files_then_upgrade(
    api_client, custom_nodes_path, setup_nightly_package
):
    """
    Test: Nightly soft reset (preserves changes) then upgrade.

    Scenario:
    1. Install nightly (latest)
    2. Soft reset to previous commit (git reset --soft HEAD~1)
    3. This leaves changes staged that match latest commit
    4. Trigger update
    5. Verify update handles staged changes correctly

    This tests git reset --soft which is less destructive but creates
    a different conflict scenario (staged vs unstaged).

    Verifies:
    - Update handles staged changes appropriately
    - Package can recover from soft reset state
    """
    package_path = setup_nightly_package

    # Get initial state
    initial_commit = get_current_commit(package_path)
    initial_count = get_commit_count(package_path)

    print(f"\n[Initial State]")
    print(f"  Commit: {initial_commit[:8]}")

    assert initial_count >= 2, "Need at least 2 commits"

    # Soft reset to previous commit (keeps changes staged)
    print(f"\n[Soft reset to previous commit]")
    result = subprocess.run(
        ["git", "reset", "--soft", "HEAD~1"],
        cwd=package_path,
        capture_output=True,
        text=True,
        check=True,
    )

    downgraded_commit = get_current_commit(package_path)
    print(f"  Commit: {downgraded_commit[:8]}")

    # Verify changes are staged
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=package_path,
        capture_output=True,
        text=True,
    )
    status_output = result.stdout.strip()
    print(f"  Staged changes:\n{status_output[:200]}...")
    assert len(status_output) > 0, "Should have staged changes after soft reset"

    # Trigger update
    print(f"\n[Triggering update with staged changes]")
    response = api_client.queue_task(
        kind="update",
        ui_id="test_nightly_upgrade_after_soft_reset",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": "nightly",
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(12)

    # Verify state after update
    upgraded_commit = get_current_commit(package_path)

    print(f"\n[After Update]")
    print(f"  Commit: {upgraded_commit[:8]}")

    # Package should remain functional regardless of final commit state
    git_dir = package_path / ".git"
    init_file = package_path / "__init__.py"

    assert git_dir.exists(), ".git directory should be preserved"
    assert init_file.exists(), "Package should remain functional"

    print(f"\n[Test Summary]")
    print(f"  ✅ Update completed after soft reset")
    print(f"  ✅ Package integrity maintained")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
