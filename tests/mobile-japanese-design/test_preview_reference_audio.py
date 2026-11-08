"""Read reference samples from an isolated preview server and synthetic WAVs."""
from copy import deepcopy
from http.server import ThreadingHTTPServer
import importlib.util
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
import wave

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from tts_service import VoiceStore


SPEC = importlib.util.spec_from_file_location(
    "reference_preview_server", Path(__file__).with_name("serve_demo.py")
)
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


class IsolatedReferenceHandler(preview.Handler):
    def log_message(self, _format, *args):
        pass

    def proxy(self, raw=None):
        # Even malformed paths must never contact the running application.
        self.json_response({"detail": "No live upstream is available in this test."}, 404)


class PreviewReferenceAudioTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="fujimi-reference-test-")
        self.addCleanup(temporary.cleanup)
        self.temporary_root = Path(temporary.name)
        self.root = self.temporary_root / "project"
        self.voice_name = "合成テスト音声"
        self.voice_id = VoiceStore._id(self.voice_name)
        self.voice_path = self.root / "data" / "voices" / (self.voice_name + ".wav")
        self.write_wav(self.voice_path)
        self.wav_bytes = self.voice_path.read_bytes()
        self.outside = self.temporary_root / "outside.wav"
        self.outside.write_bytes(b"synthetic-outside-file-must-not-be-served")
        self.catalog = [{"id": self.voice_id, "name": self.voice_name, "duration": 1.0, "active": True}]

        root_patch = patch.object(preview, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        here_patch = patch.object(preview, "HERE", self.root)
        here_patch.start()
        self.addCleanup(here_patch.stop)
        upstream_patch = patch.object(preview, "upstream_json", side_effect=self.synthetic_upstream)
        self.mock_upstream = upstream_patch.start()
        self.addCleanup(upstream_patch.stop)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), IsolatedReferenceHandler)
        self.server.daemon_threads = False
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base_url = "http://127.0.0.1:" + str(self.server.server_port)

    @staticmethod
    def write_wav(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(struct.pack("<h", 2000) * 8000 + struct.pack("<h", -2000) * 8000)

    def synthetic_upstream(self, path):
        if path != "/api/settings/voices":
            raise AssertionError("Unexpected upstream read: " + path)
        return deepcopy(self.catalog)

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())

    def get(self, path):
        with requests.Session() as session:
            session.trust_env = False
            return session.get(self.base_url + path, timeout=(2, 5), allow_redirects=False)

    def reference_path(self, voice_id=None):
        return "/api/preview/voices/" + str(self.voice_id if voice_id is None else voice_id) + "/reference"

    def snapshot(self):
        return {
            path.relative_to(self.temporary_root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.temporary_root.rglob("*") if path.is_file()
        }

    def assert_error(self, response, status):
        self.assertEqual(response.status_code, status, response.text)
        self.assertTrue(response.json().get("detail"))

    def test_returns_original_wav_bytes_and_audio_headers(self):
        response = self.get(self.reference_path())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["Content-Type"].split(";", 1)[0], "audio/wav")
        self.assertEqual(int(response.headers["Content-Length"]), len(self.wav_bytes))
        self.assertEqual(response.content, self.wav_bytes)
        self.mock_upstream.assert_called_with("/api/settings/voices")

    def test_local_voice_outside_upstream_catalog_cannot_be_read(self):
        hidden_name = "未登録の合成音声"
        hidden_id = VoiceStore._id(hidden_name)
        self.write_wav(self.voice_path.with_name(hidden_name + ".wav"))
        before = self.snapshot()
        self.assert_error(self.get(self.reference_path(hidden_id)), 404)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_voice_id_returns_not_found(self):
        self.assert_error(self.get(self.reference_path(self.voice_id + 1)), 404)

    def test_catalogued_voice_with_missing_local_file_returns_not_found(self):
        self.voice_path.unlink()
        before = self.snapshot()
        self.assert_error(self.get(self.reference_path()), 404)
        self.assertEqual(self.snapshot(), before)

    def test_reading_reference_does_not_modify_or_create_files(self):
        before = self.snapshot()
        for _ in range(2):
            response = self.get(self.reference_path())
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.content, self.wav_bytes)
        self.assertEqual(self.snapshot(), before)

    def test_path_traversal_cannot_read_outside_file(self):
        before = self.snapshot()
        paths = [
            "/api/preview/voices/%2e%2e%2foutside.wav/reference",
            "/api/preview/voices/" + str(self.voice_id) + "%2f..%2f..%2foutside.wav/reference",
            "/api/preview/voices/" + str(self.voice_id) + "%5c..%5c..%5coutside.wav/reference",
            self.reference_path() + "/%2e%2e/%2e%2e/outside.wav",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(self.outside.read_bytes(), response.content)
        self.assertEqual(self.snapshot(), before)

    def test_upstream_failure_returns_service_unavailable(self):
        self.mock_upstream.side_effect = requests.ConnectionError("synthetic upstream outage")
        before = self.snapshot()
        self.assert_error(self.get(self.reference_path()), 503)
        self.assertEqual(self.snapshot(), before)

    def test_local_file_read_failure_returns_service_unavailable(self):
        before = self.snapshot()
        original_read = Path.read_bytes

        def read_with_failure(path):
            if path == self.voice_path:
                raise PermissionError("synthetic read failure")
            return original_read(path)

        with patch.object(Path, "read_bytes", read_with_failure):
            self.assert_error(self.get(self.reference_path()), 503)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
