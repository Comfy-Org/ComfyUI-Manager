from test_invalid_installation import run


def test_a_registry_nodepack_is_listed_with_its_id_as_its_pyproject_spells_it():
    data = run('''
pack('ComfyUI_SigmoidOffsetScheduler', 'ComfyUI_SigmoidOffsetScheduler', version='1.1.1', tracking=True)
emit(core.get_installed_node_packs())
''')

    assert data == {
        'ComfyUI_SigmoidOffsetScheduler': {'ver': '1.1.1', 'cnr_id': 'ComfyUI_SigmoidOffsetScheduler', 'aux_id': None,
                                           'enabled': True}}
