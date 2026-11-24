"""The Update button of a nodepack that is only in the registry, through the real get_unified_total_nodes."""

from test_flagged_nodepack_policy import run


def test_registry_only_rows_offer_update_only_for_an_older_version():
    data = run('''
manager.reload = AsyncMock()
manager.get_custom_nodes = AsyncMock(return_value={})
core.flag_invalid_installation = lambda *a, **k: None
packs = ('active-1.0.0', 'active-nightly', 'active-2.0.0', 'disabled-1.0.0', 'not-installed')
for pack in packs:
    manager.cnr_map[pack] = {'id': pack, 'name': pack, 'publisher': {'name': 'p'},
                             'latest_version': {'version': '2.0.0'}}
manager.active_nodes['active-1.0.0'] = ('1.0.0', str(nodes / 'active-1.0.0'))
manager.active_nodes['active-nightly'] = ('nightly', str(nodes / 'active-nightly'))
manager.active_nodes['active-2.0.0'] = ('2.0.0', str(nodes / 'active-2.0.0'))
manager.cnr_inactive_nodes['disabled-1.0.0'] = {'1.0.0': str(nodes / '.disabled/disabled-1.0.0')}
rows = asyncio.run(core.get_unified_total_nodes(core.DEFAULT_CHANNEL, 'cache'))
print(json.dumps({pack: rows[pack].get('update-state') for pack in packs}))
''')
    assert data == {'active-1.0.0': 'true', 'active-nightly': 'false', 'active-2.0.0': 'false',
                    'disabled-1.0.0': 'false', 'not-installed': 'false'}
