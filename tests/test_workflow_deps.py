"""Regression tests for workflow dependency discovery."""
import ast
import asyncio
import json
import os
import re
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MANAGER_CORE_PATH = REPO_ROOT / "glob" / "manager_core.py"


def load_functions():
    tree = ast.parse(MANAGER_CORE_PATH.read_text())
    functions = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {
            "collect_nodes_from_workflow",
            "extract_nodes_from_workflow",
            "simple_check_custom_node",
        }
    ]
    namespace = {"json": json, "os": os, "re": re}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(MANAGER_CORE_PATH), "exec"), namespace)
    return namespace


FUNCTIONS = load_functions()
COLLECT_NODES = FUNCTIONS["collect_nodes_from_workflow"]
EXTRACT_NODES = FUNCTIONS["extract_nodes_from_workflow"]
SIMPLE_CHECK = FUNCTIONS["simple_check_custom_node"]


class WorkflowNodeCollectionTest(unittest.TestCase):
    def test_collects_ui_api_group_and_subgraph_nodes(self):
        workflow = {
            "nodes": [
                {"type": "TopLevelNode"},
                {"type": "subgraph-uuid"},
                {"type": "Reroute"},
                {"type": "workflow/VirtualNode"},
            ],
            "extra": {"groupNodes": {"group": {"nodes": [{"type": "GroupNode"}]}}},
            "definitions": {"subgraphs": [{
                "id": "subgraph-uuid",
                "nodes": [{"type": "SubgraphNode"}, {"type": "Note"}],
            }]},
            "1": {"class_type": "ApiNode", "inputs": {}},
            "2": {"class_type": "workflow>VirtualApiNode", "inputs": {}},
        }

        self.assertEqual(
            COLLECT_NODES(workflow),
            {"TopLevelNode", "GroupNode", "SubgraphNode", "ApiNode"},
        )

    def test_collects_mapping_subgraphs(self):
        workflow = {
            "definitions": {"subgraphs": {
                "subgraph-uuid": {"nodes": [{"type": "SubgraphNode"}]},
            }},
            "nodes": [{"type": "subgraph-uuid"}],
        }

        self.assertEqual(COLLECT_NODES(workflow), {"SubgraphNode"})

    def test_extracts_dependencies_from_all_workflow_formats(self):
        async def get_data_by_mode(*_args):
            return {
                "https://github.com/comfyanonymous/ComfyUI": [["TopLevelNode"], {}],
                "https://github.com/example/custom-pack": [
                    ["GroupNode", "SubgraphNode", "ApiNode"],
                    {},
                ],
            }

        EXTRACT_NODES.__globals__["get_data_by_mode"] = get_data_by_mode
        workflow = {
            "nodes": [{"type": "TopLevelNode"}, {"type": "subgraph-uuid"}],
            "extra": {"groupNodes": {"group": {"nodes": [{"type": "GroupNode"}]}}},
            "definitions": {"subgraphs": [{
                "id": "subgraph-uuid",
                "nodes": [{"type": "SubgraphNode"}],
            }]},
            "1": {"class_type": "ApiNode", "inputs": {}},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as workflow_file:
            json.dump(workflow, workflow_file)
            workflow_file.flush()
            used_extensions, unknown_nodes = asyncio.run(EXTRACT_NODES(workflow_file.name))

        self.assertEqual(used_extensions, {"https://github.com/example/custom-pack"})
        self.assertEqual(unknown_nodes, set())


class CustomNodeStateTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.custom_nodes = Path(self.temp_dir.name)
        SIMPLE_CHECK.__globals__["get_default_custom_nodes_path"] = lambda: str(self.custom_nodes)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_matches_installed_directory_case_insensitively(self):
        (self.custom_nodes / "FooPack").mkdir()

        self.assertEqual(
            SIMPLE_CHECK("https://github.com/example/foopack"),
            "installed",
        )

    def test_detects_disabled_directory_layouts(self):
        (self.custom_nodes / ".disabled").mkdir()
        (self.custom_nodes / ".disabled" / "FooPack").mkdir()

        self.assertEqual(
            SIMPLE_CHECK("https://github.com/example/foopack"),
            "disabled",
        )

        (self.custom_nodes / ".disabled" / "FooPack").rmdir()
        (self.custom_nodes / "FooPack.disabled").mkdir()

        self.assertEqual(
            SIMPLE_CHECK("https://github.com/example/foopack"),
            "disabled",
        )
