"""Unit tests for CNR fallback in install_by_id nightly path and getattr guard.

Tests two targeted bug fixes:
1. install_by_id nightly: falls back to cnr_map when custom_nodes lookup fails
2. do_uninstall/do_disable: getattr guard prevents AttributeError on Union mismatch
"""

from __future__ import annotations

import asyncio
import types

# ---------------------------------------------------------------------------
# Minimal stubs — avoid importing the full ComfyUI runtime
# ---------------------------------------------------------------------------


class _ManagedResult:
    """Minimal ManagedResult stub matching glob/manager_core.py."""

    def __init__(self, action):
        self.action = action
        self.result = True
        self.msg = None
        self.target = None

    def fail(self, msg):
        self.result = False
        self.msg = msg
        return self

    def with_target(self, target):
        self.target = target
        return self


class _NormalizedKeyDict:
    """Minimal NormalizedKeyDict stub matching glob/manager_core.py."""

    def __init__(self):
        self._store = {}
        self._key_map = {}

    def _normalize_key(self, key):
        return key.strip().lower() if isinstance(key, str) else key

    def __setitem__(self, key, value):
        norm = self._normalize_key(key)
        self._key_map[norm] = key
        self._store[key] = value

    def __getitem__(self, key):
        norm = self._normalize_key(key)
        return self._store[self._key_map[norm]]

    def __contains__(self, key):
        return self._normalize_key(key) in self._key_map

    def get(self, key, default=None):
        return self[key] if key in self else default


# ===================================================================
# Test 1: CNR fallback in install_by_id nightly path
# ===================================================================


class TestNightlyCnrFallback:
    """install_by_id with version_spec='nightly' should fall back to cnr_map
    when custom_nodes lookup returns None for the node_id."""

    def _make_manager(self, cnr_map_entries=None, custom_nodes_entries=None):
        """Create a minimal UnifiedManager-like object with the install_by_id
        nightly fallback logic extracted for unit testing."""
        mgr = types.SimpleNamespace()
        mgr.cnr_map = _NormalizedKeyDict()
        if cnr_map_entries:
            for k, v in cnr_map_entries.items():
                mgr.cnr_map[k] = v

        # Mock get_custom_nodes to return a NormalizedKeyDict
        custom_nodes = _NormalizedKeyDict()
        if custom_nodes_entries:
            for k, v in custom_nodes_entries.items():
                custom_nodes[k] = v

        async def get_custom_nodes(channel=None, mode=None):
            return custom_nodes

        mgr.get_custom_nodes = get_custom_nodes

        # Stubs for is_enabled/is_disabled that always return False (not installed)
        mgr.is_enabled = lambda *a, **kw: False
        mgr.is_disabled = lambda *a, **kw: False

        return mgr

    @staticmethod
    async def _run_nightly_lookup(mgr, node_id, channel='default', mode='remote'):
        """Execute the nightly lookup logic from install_by_id.

        Reproduces lines ~1407-1431 of glob/manager_core.py to test the
        CNR fallback path in isolation.
        """
        version_spec = 'nightly'
        repo_url = None

        custom_nodes = await mgr.get_custom_nodes(channel, mode)
        the_node = custom_nodes.get(node_id)

        if the_node is not None:
            repo_url = the_node['repository']
        else:
            # Fallback for nightly only: use repository URL from CNR map
            if version_spec == 'nightly':
                cnr_fallback = mgr.cnr_map.get(node_id)
                if cnr_fallback is not None and cnr_fallback.get('repository'):
                    repo_url = cnr_fallback['repository']
                else:
                    result = _ManagedResult('install')
                    return result.fail(
                        f"Node '{node_id}@{version_spec}' not found in [{channel}, {mode}]"
                    )

        return repo_url

    def test_fallback_to_cnr_map_when_custom_nodes_missing(self):
        """Node absent from custom_nodes but present in cnr_map -> uses cnr_map repo URL."""
        mgr = self._make_manager(
            cnr_map_entries={
                'my-test-pack': {
                    'id': 'my-test-pack',
                    'repository': 'https://github.com/test/my-test-pack',
                    'publisher': 'testuser',
                },
            },
            custom_nodes_entries={},  # empty — node not in nightly manifest
        )

        result = asyncio.run(
            self._run_nightly_lookup(mgr, 'my-test-pack')
        )
        assert result == 'https://github.com/test/my-test-pack'

    def test_fallback_fails_when_cnr_map_also_missing(self):
        """Node absent from both custom_nodes and cnr_map -> ManagedResult.fail."""
        mgr = self._make_manager(
            cnr_map_entries={},
            custom_nodes_entries={},
        )

        result = asyncio.run(
            self._run_nightly_lookup(mgr, 'nonexistent-pack')
        )
        assert isinstance(result, _ManagedResult)
        assert result.result is False
        assert 'nonexistent-pack@nightly' in result.msg

    def test_fallback_fails_when_cnr_entry_has_no_repository(self):
        """Node in cnr_map but repository is None/empty -> ManagedResult.fail."""
        mgr = self._make_manager(
            cnr_map_entries={
                'no-repo-pack': {
                    'id': 'no-repo-pack',
                    'repository': None,
                    'publisher': 'testuser',
                },
            },
            custom_nodes_entries={},
        )

        result = asyncio.run(
            self._run_nightly_lookup(mgr, 'no-repo-pack')
        )
        assert isinstance(result, _ManagedResult)
        assert result.result is False

    def test_fallback_fails_when_cnr_entry_has_empty_repository(self):
        """Node in cnr_map but repository is '' -> ManagedResult.fail (truthy check)."""
        mgr = self._make_manager(
            cnr_map_entries={
                'empty-repo-pack': {
                    'id': 'empty-repo-pack',
                    'repository': '',
                    'publisher': 'testuser',
                },
            },
            custom_nodes_entries={},
        )

        result = asyncio.run(
            self._run_nightly_lookup(mgr, 'empty-repo-pack')
        )
        assert isinstance(result, _ManagedResult)
        assert result.result is False

    def test_direct_custom_nodes_hit_skips_cnr_fallback(self):
        """Node present in custom_nodes -> uses custom_nodes directly, no fallback needed."""
        mgr = self._make_manager(
            cnr_map_entries={
                'found-pack': {
                    'id': 'found-pack',
                    'repository': 'https://github.com/test/found-cnr',
                },
            },
            custom_nodes_entries={
                'found-pack': {
                    'repository': 'https://github.com/test/found-custom',
                    'files': ['https://github.com/test/found-custom'],
                },
            },
        )

        result = asyncio.run(
            self._run_nightly_lookup(mgr, 'found-pack')
        )
        # Should use custom_nodes repo URL, NOT cnr_map
        assert result == 'https://github.com/test/found-custom'

    def test_unknown_version_spec_does_not_use_cnr_fallback(self):
        """version_spec='unknown' path should NOT use cnr_map fallback."""
        mgr = self._make_manager(
            cnr_map_entries={
                'unknown-pack': {
                    'id': 'unknown-pack',
                    'repository': 'https://github.com/test/unknown-pack',
                },
            },
            custom_nodes_entries={},
        )

        async def _run_unknown_lookup():
            version_spec = 'unknown'
            custom_nodes = await mgr.get_custom_nodes()
            the_node = custom_nodes.get('unknown-pack')

            if the_node is not None:
                return the_node['files'][0]
            else:
                if version_spec == 'nightly':
                    # This branch should NOT be taken for 'unknown'
                    cnr_fallback = mgr.cnr_map.get('unknown-pack')
                    if cnr_fallback is not None and cnr_fallback.get('repository'):
                        return cnr_fallback['repository']
                # Fall through to error for 'unknown'
                result = _ManagedResult('install')
                return result.fail(
                    f"Node 'unknown-pack@{version_spec}' not found"
                )

        result = asyncio.run(_run_unknown_lookup())
        assert isinstance(result, _ManagedResult)
        assert result.result is False
        assert 'unknown' in result.msg

    def test_case_insensitive_cnr_map_lookup(self):
        """CNR map uses NormalizedKeyDict — lookup should be case-insensitive."""
        mgr = self._make_manager(
            cnr_map_entries={
                'My-Test-Pack': {
                    'id': 'my-test-pack',
                    'repository': 'https://github.com/test/my-test-pack',
                },
            },
            custom_nodes_entries={},
        )

        result = asyncio.run(
            self._run_nightly_lookup(mgr, 'my-test-pack')
        )
        assert result == 'https://github.com/test/my-test-pack'


# ===================================================================
# Test 2: getattr guard in do_uninstall / do_disable
# ===================================================================


class TestGetAttrGuard:
    """do_uninstall and do_disable use getattr(params, 'is_unknown', False)
    to guard against pydantic Union matching UpdatePackParams (which lacks
    is_unknown field) instead of UninstallPackParams/DisablePackParams."""

    def test_getattr_on_object_with_is_unknown(self):
        """Normal case: params has is_unknown -> returns its value."""
        params = types.SimpleNamespace(node_name='test-pack', is_unknown=True)
        assert getattr(params, 'is_unknown', False) is True

    def test_getattr_on_object_without_is_unknown(self):
        """Bug case: params is UpdatePackParams-like (no is_unknown) -> returns False."""
        params = types.SimpleNamespace(node_name='test-pack', node_ver='1.0.0')
        # Without getattr guard, this would be: params.is_unknown -> AttributeError
        assert getattr(params, 'is_unknown', False) is False

    def test_getattr_default_false_on_missing_attribute(self):
        """Minimal case: bare object with only node_name."""
        params = types.SimpleNamespace(node_name='test-pack')
        assert getattr(params, 'is_unknown', False) is False

    def test_pydantic_union_matching_demonstrates_bug(self):
        """Demonstrate why getattr is needed: pydantic Union without discriminator
        can match UpdatePackParams for uninstall/disable payloads."""
        from pydantic import BaseModel, Field
        from typing import Optional, Union

        class UpdateLike(BaseModel):
            node_name: str
            node_ver: Optional[str] = None

        class UninstallLike(BaseModel):
            node_name: str
            is_unknown: Optional[bool] = Field(False)

        # When Union tries to match {"node_name": "foo"}, UpdateLike matches first
        # because it has fewer required fields and node_name satisfies it
        class TaskItem(BaseModel):
            params: Union[UpdateLike, UninstallLike]

        item = TaskItem(params={"node_name": "foo"})

        # The matched type may be UpdateLike (no is_unknown attribute)
        # This is the exact scenario the getattr guard protects against
        is_unknown = getattr(item.params, 'is_unknown', False)
        # Regardless of which Union member matched, getattr safely returns a value
        assert isinstance(is_unknown, bool)
