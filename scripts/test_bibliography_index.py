"""Regression checks for choosing an actual, permitted U00 work item from an event snapshot."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import render_html as view


class BibliographyTests(unittest.TestCase):
    def test_priority_deadline_dependencies_and_scope(self):
        def task(kind, **changes):
            return dict({"entity_id":"w", "task_type":kind, "task_state":"pending",
                         "priority":"normal", "deadline_at_utc":None, "dependency_ids":[]}, **changes)
        tasks = {
            "excluded":task("fulltext", priority="high", deadline_at_utc="2020-01-01T00:00:00Z"),
            "blocked":task("abstract", priority="high", dependency_ids=["unknown-id"]),
            "closed":task("references", task_state="verified_complete"),
            "deferred":task("citations", priority="high", retry_at="2030-01-01T00:00:00Z"),
            "restricted":task("metadata", task_state="restricted", priority="high"),
            "ordinary":task("references", deadline_at_utc="2020-01-01T00:00:00Z"),
            "late":task("authors", priority="high", deadline_at_utc="2026-01-01T11:00:00Z"),
            "a":task("field_review", field_path="doi", priority="high", dependency_ids=["closed"],
                     deadline_at_utc="2026-01-01T17:00:00+08:00"),
            "b":task("metadata", priority="high", deadline_at_utc="2026-01-01T09:00:00Z"),
        }
        now = datetime(2026,11,28,tzinfo=timezone.utc)
        self.assertEqual(view.next_actions(tasks, {"w":"w"}, now)["w"], "核对DOI")
        self.assertEqual(view.next_actions({"x":tasks["excluded"]}, {"w":"w"}, now)["w"], "待核实")
        self.assertEqual(view.next_actions({"x":tasks["blocked"]}, {"w":"w"}, now)["w"], "等待现有工单的复查条件")
        self.assertEqual(view.next_actions({"x":tasks["closed"]}, {"w":"w"}, now), {})

    def test_topic_projection_and_missing_fields(self):
        w = dict(work_id="w", work_key="Key", canonical_title="A < B & C", authors=[],
                 notes="PRIVATE_FIELD_SENTINEL", abstract_items=[{"text":"ABSTRACT_SENTINEL"}])
        data = view.make_payload([w], "CP-0011", groups={"L01":{"Key"},"L02":{"Key"}})
        self.assertEqual(data["rows"], [["Key","A < B & C","",None,0,""]])
        self.assertEqual(data["groups"], {"L01":[0],"L02":[0]})
        self.assertEqual(data["venues"], [""])
        self.assertNotIn("SENTINEL", view.compact(data))
        misc = view.make_payload([w], "CP-0011", actions={})
        self.assertEqual(misc["actions"], ["暂无已登记动作"])
        self.assertEqual(misc["reasons"], [])

    def test_interrupted_publish_restores_previous_files(self):
        with TemporaryDirectory() as tmp:
            dest=Path(tmp)
            first, second=dest/"one", dest/"two"
            first.write_bytes(b"before")
            original=view.write_file
            def fail_on_second(path, raw):
                if path == second:
                    raise OSError("simulated write failure")
                original(path, raw)
            with patch.object(view, "write_file", side_effect=fail_on_second), self.assertRaises(OSError):
                view.publish(dest, {first:b"after",second:b"new"})
            self.assertEqual(first.read_bytes(),b"before")
            self.assertFalse(second.exists())


if __name__=="__main__":
    unittest.main()
