"""`openapi.yaml` lists, for `db_mode` and the update policy, the values the routes accept."""
import ast

import pytest
import yaml

from legacy_html_testutil import PACKAGE

SPEC = yaml.safe_load((PACKAGE.parent / "openapi.yaml").read_text(encoding="utf-8"))
ACCEPTED = {node.targets[0].id: ast.literal_eval(node.value)
            for node in ast.parse((PACKAGE / "glob/utils/environment_utils.py").read_text(encoding="utf-8")).body
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "").startswith("ALLOWED_")}


@pytest.mark.parametrize("route, accepted", [
    ("/v2/manager/db_mode", "ALLOWED_DB_MODES"),
    ("/v2/manager/policy/update", "ALLOWED_UPDATE_POLICIES"),
])
def test_values_of_a_setting_route_are_the_ones_the_route_accepts(route, accepted):
    answered = SPEC["paths"][route]["get"]["responses"]["200"]["content"]["text/plain"]["schema"]["enum"]
    asked = SPEC["paths"][route]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["value"]["enum"]

    assert sorted(answered) == sorted(asked) == sorted(ACCEPTED[accepted])
