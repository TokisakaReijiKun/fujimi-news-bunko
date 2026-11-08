"""Exercise preview quota writes over HTTP without a real library service."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from http.server import ThreadingHTTPServer
import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import requests


SPEC = importlib.util.spec_from_file_location(
    "quota_preview_server", Path(__file__).with_name("serve_demo.py")
)
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


class IsolatedPreviewHandler(preview.Handler):
    def log_message(self, _format, *args):
        pass

    def proxy(self, raw=None):
        # An unexpected route must fail locally, never reach the running app.
        self.json_response({"detail": "Live upstream access is forbidden in this test."}, 500)


class PreviewQuotaTests(unittest.TestCase):
    def setUp(self):
        self.original_sources = [
            {"id": 1, "name": "Source A", "homepage": "https://a.example/", "minimum_count": 2},
            {"id": 2, "name": "Source B", "homepage": "https://b.example/", "minimum_count": 3},
        ]
        self.upstream = {
            "/api/settings/news-sources": deepcopy(self.original_sources),
            "/api/settings/daily-content": {"target_count": 10, "source_count": 2, "required_count": 5},
        }
        with preview.LOCK:
            self.previous_settings = deepcopy(preview.SETTINGS)
            preview.SETTINGS.clear()
        self.addCleanup(self.restore_settings)
        upstream_patch = patch.object(preview, "upstream_json", side_effect=self.synthetic_upstream)
        self.mock_upstream = upstream_patch.start()
        self.addCleanup(upstream_patch.stop)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), IsolatedPreviewHandler)
        self.server.daemon_threads = False
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base_url = "http://127.0.0.1:" + str(self.server.server_port)

    def synthetic_upstream(self, path):
        if path not in self.upstream:
            raise AssertionError("Unexpected upstream read: " + path)
        return deepcopy(self.upstream[path])

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())

    def restore_settings(self):
        with preview.LOCK:
            preview.SETTINGS.clear()
            preview.SETTINGS.update(self.previous_settings)
        self.assertEqual(self.upstream["/api/settings/news-sources"], self.original_sources)
        self.assertEqual(self.upstream["/api/settings/daily-content"]["target_count"], 10)

    def put(self, path, payload):
        with requests.Session() as session:
            session.trust_env = False
            response = session.put(self.base_url + path, json=payload, timeout=(2, 5))
        return response.status_code, response.json()

    def source(self, source_id, minimum):
        return self.put(
            "/api/settings/news-sources/" + str(source_id), {"minimum_count": minimum}
        )

    def target(self, count):
        return self.put("/api/settings/daily-content", {"target_count": count})

    def current_sources(self):
        with preview.LOCK:
            return deepcopy(preview.SETTINGS.get("news-sources", self.original_sources))

    def current_target(self):
        with preview.LOCK:
            return preview.SETTINGS.get("daily-content", {"target_count": 10})["target_count"]

    def assert_rejected(self, result):
        status, payload = result
        self.assertEqual(status, 400, payload)
        self.assertTrue(payload.get("detail"), payload)

    def test_source_total_above_target_is_rejected_without_change(self):
        self.assert_rejected(self.source(1, 8))
        self.assertEqual(self.current_sources(), self.original_sources)

    def test_source_total_equal_to_target_is_allowed_and_returns_one_source(self):
        status, payload = self.source(1, 7)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload, {**self.original_sources[0], "minimum_count": 7})
        self.assertEqual([item["minimum_count"] for item in self.current_sources()], [7, 3])

    def test_target_below_total_is_rejected_without_change(self):
        self.assert_rejected(self.target(4))
        self.assertEqual(self.current_target(), 10)

    def test_target_equal_to_total_is_allowed(self):
        status, payload = self.target(5)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["target_count"], 5)
        self.assertEqual(self.current_target(), 5)

    def test_target_uses_updated_preview_source_total(self):
        self.assertEqual(self.source(1, 4)[0], 200)
        self.assertEqual(self.source(2, 4)[0], 200)
        self.assert_rejected(self.target(7))
        self.assertEqual(self.current_target(), 10)
        self.assertEqual(self.target(8)[0], 200)

    def test_concurrent_sources_compete_for_one_remaining_article(self):
        self.assertEqual(self.target(6)[0], 200)
        ready = threading.Barrier(3)

        def reserve(source_id, minimum):
            ready.wait(timeout=3)
            return self.source(source_id, minimum)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(reserve, 1, 3)
            second = pool.submit(reserve, 2, 4)
            ready.wait(timeout=3)
            results = [first.result(timeout=8), second.result(timeout=8)]
        self.assertEqual(sorted(status for status, _ in results), [200, 400], results)
        sources = self.current_sources()
        self.assertEqual(sum(item["minimum_count"] for item in sources), 6)
        self.assertIn([item["minimum_count"] for item in sources], ([3, 3], [2, 4]))

    def test_full_budget_can_be_reallocated_by_decreasing_before_increasing(self):
        self.assertEqual(self.target(5)[0], 200)
        self.assert_rejected(self.source(1, 3))
        self.assertEqual(self.source(2, 2)[0], 200)
        self.assertEqual(self.source(1, 3)[0], 200)
        self.assertEqual([item["minimum_count"] for item in self.current_sources()], [3, 2])
        self.assertEqual(self.current_target(), 5)

    def test_source_range_accepts_zero_and_one_hundred(self):
        self.assertEqual(self.target(103)[0], 200)
        for minimum in (0, 100):
            with self.subTest(minimum=minimum):
                status, payload = self.source(1, minimum)
                self.assertEqual(status, 200, payload)
                self.assertEqual(payload["minimum_count"], minimum)

    def test_source_range_rejects_out_of_range_and_non_integer_values(self):
        for minimum in (-1, 101, 1.5, "3", True, False, None):
            with self.subTest(minimum=minimum):
                self.assert_rejected(self.source(1, minimum))
                self.assertEqual(self.current_sources(), self.original_sources)

    def test_target_range_accepts_one_and_five_hundred(self):
        self.assertEqual(self.source(1, 0)[0], 200)
        self.assertEqual(self.source(2, 0)[0], 200)
        for count in (1, 500):
            with self.subTest(count=count):
                status, payload = self.target(count)
                self.assertEqual(status, 200, payload)
                self.assertEqual(payload["target_count"], count)

    def test_target_range_rejects_out_of_range_and_non_integer_values(self):
        for count in (-1, 0, 501, 5.5, "5", True, False, None):
            with self.subTest(count=count):
                self.assert_rejected(self.target(count))
                self.assertEqual(self.current_target(), 10)


if __name__ == "__main__":
    unittest.main()
