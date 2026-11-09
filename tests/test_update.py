"""更新检查与安装包下载的测试：版本比较、地址白名单、流式落盘。"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lyceum import backup as B  # noqa: E402


class VersionTest(unittest.TestCase):
    def test_newer_compares_numerically_not_lexically(self):
        self.assertTrue(B.newer("0.3.0", "0.2.1"))
        self.assertTrue(B.newer("0.10.0", "0.9.9"))
        self.assertFalse(B.newer("0.3.0", "0.3.0"))
        self.assertFalse(B.newer("0.2.9", "0.3.0"))

    def test_missing_parts_are_zero(self):
        self.assertTrue(B.newer("1.0", "0.9.9"))
        self.assertFalse(B.newer("1.0", "1.0.0"))


class ReleaseTest(unittest.TestCase):
    def fake(self, tag="v0.3.0"):
        return {"tag_name": tag, "html_url": "https://github.com/x/releases/tag/" + tag, "body": "notes",
                "assets": [{"name": "Lyceum-Setup-0.3.0.exe", "browser_download_url": "https://github.com/x/Lyceum-Setup-0.3.0.exe"},
                           {"name": "Lyceum-0.3.0-macOS.dmg", "browser_download_url": "https://github.com/x/a.dmg"}]}

    def test_picks_the_exe_asset_and_reports_newer(self):
        r = B.check_update("0.2.1", fetch=lambda url: self.fake())
        self.assertTrue(r["ok"])
        self.assertEqual(r["latest"], "0.3.0")
        self.assertTrue(r["newer"])
        self.assertTrue(r["exe"].endswith(".exe"))
        self.assertTrue(r["dmg"].endswith(".dmg"))

    def test_same_version_is_not_newer(self):
        r = B.check_update("0.3.0", fetch=lambda url: self.fake())
        self.assertFalse(r["newer"])

    def test_network_error_is_reported_not_raised(self):
        def boom(url):
            raise OSError("no route")
        r = B.check_update("0.2.1", fetch=boom)
        self.assertFalse(r["ok"])
        self.assertIn("查不到更新", r["error"])


class UrlTest(unittest.TestCase):
    def test_accepts_github_release_urls(self):
        for u in ("https://github.com/a/b.exe",
                  "https://objects.githubusercontent.com/x/y.exe"):
            self.assertEqual(B.safe_installer_url(u), u)

    def test_rejects_http_other_hosts_and_non_exe(self):
        for u in ("http://github.com/a.exe", "https://evil.example.com/a.exe",
                  "https://github.com/a.dmg", "https://github.com/a.msi?x=.exe"):
            with self.assertRaises(ValueError):
                B.safe_installer_url(u)


class DownloadTest(unittest.TestCase):
    class Resp:
        def __init__(self, data):
            self.data, self.i = data, 0
            self.headers = {"Content-Length": str(len(data))}

        def read(self, n):
            chunk = self.data[self.i:self.i + n]
            self.i += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Opener:
        def __init__(self, data):
            self.data = data

        def open(self, req, timeout=None):
            return DownloadTest.Resp(self.data)

    def test_streams_to_disk_and_reports_progress(self):
        payload = b"PK\x03\x04" + b"x" * 5000
        seen = []
        with tempfile.TemporaryDirectory() as d:
            r = B.download_installer("https://github.com/a/Lyceum-Setup-9.9.9.exe", d,
                                     opener=self.Opener(payload), on_progress=lambda g, t: seen.append((g, t)))
            self.assertEqual(r["bytes"], len(payload))
            self.assertTrue(os.path.isfile(r["path"]))
            with open(r["path"], "rb") as f:
                self.assertEqual(f.read(), payload)
            self.assertTrue(seen)
            self.assertEqual(seen[-1][0], len(payload))

    def test_oversize_aborts_and_leaves_no_file(self):
        old = B.MAX_INSTALLER
        B.MAX_INSTALLER = 1000
        try:
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):
                    B.download_installer("https://github.com/a/b.exe", d, opener=self.Opener(b"x" * 5000))
                self.assertEqual([n for n in os.listdir(d) if n.endswith(".exe")], [])
        finally:
            B.MAX_INSTALLER = old

    def test_bad_url_never_touches_the_network(self):
        class Exploding:
            def open(self, *a, **k):
                raise AssertionError("不该发起请求")
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                B.download_installer("https://evil.example.com/x.exe", d, opener=Exploding())


if __name__ == "__main__":
    unittest.main()
