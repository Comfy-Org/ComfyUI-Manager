from test_invalid_installation import core, custom_nodes, pack  # noqa: F401 -- fixtures


def test_a_registry_nodepack_is_listed_with_its_id_as_its_pyproject_spells_it(core, custom_nodes):  # noqa: F811
    pack(custom_nodes / 'ComfyUI_SigmoidOffsetScheduler', 'ComfyUI_SigmoidOffsetScheduler', version='1.1.1', tracking=True)

    assert core.get_installed_node_packs() == {
        'ComfyUI_SigmoidOffsetScheduler': {'ver': '1.1.1', 'cnr_id': 'ComfyUI_SigmoidOffsetScheduler', 'aux_id': None,
                                           'enabled': True}}
