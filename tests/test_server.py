import shutil
import unittest

from fastapi.testclient import TestClient

from tests import TEST_ROOT  # noqa: F401  (sets the env before the app is imported)
from webapp.server import app
from ytarabic import config, settings

DL = config.DOWNLOAD_DIR


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def setUp(self):
        shutil.rmtree(DL, ignore_errors=True)
        (DL / "single").mkdir(parents=True)
        settings.SETTINGS_FILE.unlink(missing_ok=True)

    def test_status_and_index(self):
        s = self.client.get("/api/status").json()
        self.assertEqual(s["download_dir"], str(DL.resolve()))
        self.assertEqual(s["settings"], settings.DEFAULTS)
        html = self.client.get("/").text
        self.assertNotIn("__V__", html)
        self.assertIn("/static/app.js?v=", html)

    def test_foreign_host_refused(self):
        r = self.client.get("/api/status", headers={"host": "evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_cross_site_post_refused(self):
        r = self.client.post("/api/cleanup", json={}, headers={"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/settings", json={"default_quality": "3"},
                             headers={"origin": "http://localhost:8000"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(settings.get("default_quality"), "3")

    def test_settings_validation(self):
        r = self.client.post("/api/settings", json={"default_quality": "42"}).json()
        self.assertFalse(r["ok"])
        self.assertEqual(r["rejected"], ["default_quality"])

    def test_files_stay_inside_downloads(self):
        (DL / "single" / "a [aaaaaaaaaaa].mp4").write_bytes(b"\0" * 2048)
        (DL / "single" / "a [aaaaaaaaaaa].ar.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nمرحبا\n", encoding="utf-8")
        (DL / "secret.txt").write_text("x", encoding="utf-8")

        ok = self.client.get("/api/media", params={"path": "single/a [aaaaaaaaaaa].mp4"},
                             headers={"range": "bytes=0-9"})
        self.assertEqual(ok.status_code, 206)
        self.assertEqual(len(ok.content), 10)

        vtt = self.client.get("/api/subtitle", params={"path": "single/a [aaaaaaaaaaa].ar.srt"})
        self.assertTrue(vtt.text.startswith("WEBVTT"))
        self.assertIn("00:00:01.000", vtt.text)

        for path in ["../settings.json", "../../tests/__init__.py", "C:/Windows/win.ini"]:
            self.assertEqual(self.client.get("/api/media", params={"path": path}).status_code, 404, path)
            self.assertEqual(self.client.get("/api/text", params={"path": path}).status_code, 404, path)
        # right folder, wrong kind of file
        self.assertEqual(self.client.get("/api/media", params={"path": "secret.txt"}).status_code, 404)

    def test_download_needs_a_link(self):
        self.assertFalse(self.client.post("/api/download", json={"urls": []}).json()["ok"])


if __name__ == "__main__":
    unittest.main()
