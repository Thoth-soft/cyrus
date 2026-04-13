"""Tests for sekha.schemas: TOOLS constant (6 sekha_* tool descriptors).

RED stage for Plan 05-01 Task 2. These schemas are the source of truth
for the MCP `tools/list` response; they must match 05-CONTEXT.md exactly
and expose the 6 tools required by MCP-03.
"""
from __future__ import annotations

import unittest

from sekha.schemas import TOOLS, TOOLS_BY_NAME


EXPECTED_NAMES = {
    "sekha_save",
    "sekha_search",
    "sekha_list",
    "sekha_delete",
    "sekha_status",
    "sekha_add_rule",
}


class TestSchemas(unittest.TestCase):
    # 1.
    def test_tools_is_list_of_six(self):
        self.assertIsInstance(TOOLS, list)
        self.assertEqual(len(TOOLS), 6)

    # 2.
    def test_tool_names_are_sekha_prefixed_and_complete(self):
        names = {t["name"] for t in TOOLS}
        self.assertEqual(names, EXPECTED_NAMES)
        for name in names:
            self.assertTrue(name.startswith("sekha_"), name)

    # 3.
    def test_every_tool_has_name_description_inputschema(self):
        for t in TOOLS:
            self.assertEqual(
                set(t.keys()),
                {"name", "description", "inputSchema"},
                f"unexpected keys on {t.get('name')}: {set(t.keys())}",
            )

    # 4.
    def test_every_inputschema_is_object_type(self):
        for t in TOOLS:
            schema = t["inputSchema"]
            self.assertEqual(schema.get("type"), "object", t["name"])
            self.assertIn("properties", schema, t["name"])
            self.assertIsInstance(schema["properties"], dict)

    # 5. sekha_save
    def test_sekha_save_required_and_category_enum(self):
        save = TOOLS_BY_NAME["sekha_save"]
        schema = save["inputSchema"]
        self.assertEqual(schema["required"], ["category", "content"])
        self.assertEqual(
            schema["properties"]["category"]["enum"],
            ["sessions", "decisions", "preferences", "projects", "rules"],
        )
        self.assertEqual(schema["properties"]["content"]["type"], "string")
        self.assertEqual(schema["properties"]["tags"]["type"], "array")

    # 6. sekha_search
    def test_sekha_search_required_and_defaults(self):
        search = TOOLS_BY_NAME["sekha_search"]
        schema = search["inputSchema"]
        self.assertEqual(schema["required"], ["query"])
        self.assertEqual(schema["properties"]["limit"]["default"], 10)

    # 7. sekha_list
    def test_sekha_list_has_no_required(self):
        clist = TOOLS_BY_NAME["sekha_list"]
        schema = clist["inputSchema"]
        required = schema.get("required", [])
        self.assertEqual(required, [])
        self.assertEqual(schema["properties"]["limit"]["default"], 20)

    # 8. sekha_delete
    def test_sekha_delete_requires_path(self):
        cdel = TOOLS_BY_NAME["sekha_delete"]
        self.assertEqual(cdel["inputSchema"]["required"], ["path"])
        self.assertEqual(
            cdel["inputSchema"]["properties"]["path"]["type"], "string"
        )

    # 9. sekha_status
    def test_sekha_status_takes_no_params(self):
        cstat = TOOLS_BY_NAME["sekha_status"]
        self.assertEqual(cstat["inputSchema"]["properties"], {})

    # 10. sekha_add_rule
    def test_sekha_add_rule_required_fields(self):
        car = TOOLS_BY_NAME["sekha_add_rule"]
        schema = car["inputSchema"]
        required = set(schema["required"])
        self.assertTrue(
            {"name", "severity", "matches", "pattern", "message"}.issubset(required),
            f"missing required fields: {required}",
        )
        self.assertEqual(
            schema["properties"]["severity"]["enum"], ["block", "warn"]
        )
        self.assertEqual(schema["properties"]["priority"]["default"], 50)

    # 11. Lookup convenience
    def test_tools_lookup_dict_round_trip(self):
        for t in TOOLS:
            self.assertIs(TOOLS_BY_NAME[t["name"]], t)
        self.assertEqual(set(TOOLS_BY_NAME.keys()), EXPECTED_NAMES)


if __name__ == "__main__":
    unittest.main()
