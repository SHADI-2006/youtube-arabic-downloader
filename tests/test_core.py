import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from tests import TEST_ROOT
from ytarabic import config, gemini, library, media, progress_store, settings, subtitles, transcript, youtube
from ytarabic.config import UTF8_BOM
from ytarabic.utils import (
    classify_url, extract_playlist_id, extract_youtube_id, normalize_playlist_url,
    normalize_youtube_url,
)

DL = config.DOWNLOAD_DIR


def reset_downloads():
    shutil.rmtree(DL, ignore_errors=True)
    DL.mkdir(parents=True)


class UrlTests(unittest.TestCase):
    def test_video_ids(self):
        vid = "dQw4w9WgXcQ"
        for url in [
            f"https://www.youtube.com/watch?v={vid}",
            f"https://youtube.com/watch?v={vid}&list=PLx&si=abc",
            f"https://m.youtube.com/watch?app=desktop&v={vid}",
            f"https://youtu.be/{vid}?si=xyz",
            f"https://www.youtube.com/shorts/{vid}",
            f"https://www.youtube.com/live/{vid}?feature=share",
            f"https://music.youtube.com/watch?v={vid}",
            f"youtube.com/embed/{vid}",
        ]:
            self.assertEqual(extract_youtube_id(url), vid, url)
        for url in ["https://www.youtube.com/playlist?list=PL123", "https://example.com/watch?v=" + vid,
                    "https://www.youtube.com/watch?v=short", "not a url", ""]:
            self.assertIsNone(extract_youtube_id(url), url)

    def test_normalize(self):
        self.assertEqual(normalize_youtube_url("https://youtu.be/dQw4w9WgXcQ?si=1"),
                         "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(extract_playlist_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc_-1"), "PLabc_-1")
        self.assertEqual(normalize_playlist_url("https://youtube.com/playlist?list=PLabc&si=kkk"),
                         "https://www.youtube.com/playlist?list=PLabc")
        self.assertEqual(normalize_playlist_url("https://example.com/x"), "https://example.com/x")

    def test_classify(self):
        self.assertEqual(classify_url("https://youtu.be/dQw4w9WgXcQ"), "youtube")
        self.assertEqual(classify_url("https://www.instagram.com/reel/abc/"), "instagram")
        self.assertEqual(classify_url("https://x.com/user/status/1"), "x")
        self.assertEqual(classify_url("https://twitter.com/user/status/1"), "x")
        self.assertEqual(classify_url("https://netflix.com/x"), "other")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        settings.SETTINGS_FILE.unlink(missing_ok=True)

    def test_defaults_and_update(self):
        self.assertEqual(settings.load(), settings.DEFAULTS)
        data, rejected = settings.update({"default_quality": "5", "translation_order": "gemini_first",
                                          "rate_limit_mb": "2.5", "embed_subtitles": True})
        self.assertEqual(rejected, [])
        self.assertEqual(settings.get("default_quality"), "5")
        self.assertEqual(settings.get("rate_limit_mb"), 2.5)
        self.assertTrue(settings.get("embed_subtitles"))

    def test_invalid_values_rejected(self):
        _, rejected = settings.update({"default_quality": "99", "embed_subtitles": "yes",
                                       "gemini_model": "bad model; rm", "nope": 1, "rate_limit_mb": -1})
        self.assertEqual(sorted(rejected), ["default_quality", "embed_subtitles", "gemini_model", "nope", "rate_limit_mb"])
        self.assertEqual(settings.load(), settings.DEFAULTS)

    def test_corrupt_file_falls_back(self):
        settings.SETTINGS_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(settings.load(), settings.DEFAULTS)
        settings.SETTINGS_FILE.write_text(json.dumps({"default_quality": "1", "subtitle_mode": "klingon"}), encoding="utf-8")
        self.assertEqual(settings.get("default_quality"), "1")
        self.assertEqual(settings.get("subtitle_mode"), "ar")


SRT_TWO_LINES = "1\n00:00:01,000 --> 00:00:02,000\nfirst line\nsecond line\n\n2\n00:00:03,000 --> 00:00:04,000\nonly line\n"


class SubtitleFileTests(unittest.TestCase):
    def setUp(self):
        reset_downloads()
        self.dir = DL / "single"
        self.dir.mkdir()

    def test_language_from_filename(self):
        self.assertEqual(subtitles.sub_lang(Path("Title [abcdefghijk].ar.srt")), "ar")
        self.assertEqual(subtitles.sub_lang(Path("Lesson 3.5 [abcdefghijk].ar-en.vtt")), "ar-en")
        self.assertIsNone(subtitles.sub_lang(Path("Lecture 3.5.srt")))
        self.assertTrue(subtitles.is_arabic_subtitle(Path("x [abcdefghijk].ar-orig.srt")))
        # The old substring check matched "ar." inside a title
        self.assertFalse(subtitles.is_arabic_subtitle(Path("Star. Wars [abcdefghijk].en.srt")))
        self.assertFalse(subtitles.is_arabic_subtitle(Path("Title.ar.mp4")))

    def test_fix_is_idempotent_scoped_and_arabic_only(self):
        ar = self.dir / "A [aaaaaaaaaaa].ar.srt"
        en = self.dir / "A [aaaaaaaaaaa].en.srt"
        other = self.dir / "B [bbbbbbbbbbb].ar.srt"
        for f in (ar, en, other):
            f.write_text(SRT_TWO_LINES, encoding="utf-8")

        for _ in range(3):   # repeated calls must not flip lines back and forth
            subtitles.fix_subtitle_bom(self.dir, "[aaaaaaaaaaa]")

        ar_text = ar.read_bytes()
        self.assertTrue(ar_text.startswith(UTF8_BOM))
        self.assertIn("second line\nfirst line", ar_text.decode("utf-8-sig"))
        en_text = en.read_bytes().decode("utf-8-sig")
        self.assertIn("first line\nsecond line", en_text)             # English never reordered
        self.assertEqual(other.read_text(encoding="utf-8"), SRT_TWO_LINES)  # other video untouched

    def test_failed_refetch_keeps_existing_arabic(self):
        url = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
        old = self.dir / "A [aaaaaaaaaaa].ar.srt"
        old.write_bytes(UTF8_BOM + b"1\n00:00:01,000 --> 00:00:02,000\nold\n")
        Path(str(old) + ".source").write_text("Gemini", encoding="utf-8")

        class NoopYDL:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def download(self, urls): pass

        with mock.patch.object(subtitles, "arabic_lang_options", return_value=(None, None)), \
             mock.patch.object(subtitles.yt_dlp, "YoutubeDL", NoopYDL), \
             mock.patch.object(gemini, "unavailable_reason", return_value="no key (test)"):
            result = subtitles.fetch_subtitles(url, self.dir, log=lambda *a: None, mode="ar")

        self.assertIsNone(result)
        self.assertTrue(old.exists())
        self.assertEqual(subtitles.read_subtitle_source(old), "Gemini")
        self.assertEqual([p.name for p in self.dir.glob("*.bak")], [])

    def test_engine_order_follows_setting(self):
        settings.SETTINGS_FILE.unlink(missing_ok=True)
        self.assertEqual(subtitles._engine_order("auto"), ["manual", "youtube", "gemini", "google"])
        settings.update({"translation_order": "gemini_first"})
        self.assertEqual(subtitles._engine_order("auto"), ["manual", "gemini", "youtube", "google"])
        self.assertEqual(subtitles._engine_order("google"), ["google"])
        settings.SETTINGS_FILE.unlink(missing_ok=True)

    def test_srt_to_vtt(self):
        vtt = media.srt_to_vtt("\ufeff" + SRT_TWO_LINES)
        self.assertTrue(vtt.startswith("WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000"))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        reset_downloads()
        self.single = DL / "single"
        self.single.mkdir()
        big = b"x" * (config.MIN_VIDEO_BYTES + 10)
        (self.single / "Done [aaaaaaaaaaa].mp4").write_bytes(big)
        (self.single / "Done [aaaaaaaaaaa].ar.srt").write_text("1", encoding="utf-8")
        (self.single / "Done [aaaaaaaaaaa].ar.srt.source").write_text("YouTube auto-translate", encoding="utf-8")
        (self.single / "Done [aaaaaaaaaaa].f137.mp4").write_bytes(b"y" * 500)          # leftover stream
        (self.single / "Done [aaaaaaaaaaa].f140.m4a.part").write_bytes(b"z" * 100)      # leftover partial
        (self.single / "Half [bbbbbbbbbbb].f137.mp4.part").write_bytes(b"w" * 300)      # resumable
        (self.single / "Song [ccccccccccc].mp3").write_bytes(b"m" * 2000)
        (DL / ".history.json").write_text("[]", encoding="utf-8")

    def test_scan(self):
        data = library.scan()
        by_name = {i["title"]: i for i in data["items"]}
        self.assertEqual(set(by_name), {"Done", "Song"})
        self.assertTrue(by_name["Done"]["has_arabic"])
        self.assertEqual(by_name["Done"]["subtitles"][0]["source"], "YouTube auto-translate")
        self.assertTrue(by_name["Song"]["is_audio"])
        self.assertEqual(by_name["Done"]["path"], "single/Done [aaaaaaaaaaa].mp4")

    def test_leftovers_and_cleanup(self):
        found = library.find_leftovers()
        self.assertEqual(sorted(e["name"] for e in found["junk"]),
                         ["Done [aaaaaaaaaaa].f137.mp4", "Done [aaaaaaaaaaa].f140.m4a.part"])
        self.assertEqual([e["name"] for e in found["unfinished"]], ["Half [bbbbbbbbbbb].f137.mp4.part"])
        result = library.cleanup(include_unfinished=False, log=lambda *a: None)
        self.assertEqual(result, {"removed": 2, "freed": 600})
        self.assertTrue((self.single / "Half [bbbbbbbbbbb].f137.mp4.part").exists())
        self.assertTrue((self.single / "Done [aaaaaaaaaaa].mp4").exists())

    def test_resolve_refuses_escapes(self):
        self.assertEqual(library.resolve("single/Song [ccccccccccc].mp3").name, "Song [ccccccccccc].mp3")
        for bad in ["../settings.json", "..\\x", "single/../../x", "C:/Windows/win.ini", "/etc/passwd", ""]:
            with self.assertRaises(ValueError, msg=bad):
                library.resolve(bad)


class TranscriptTests(unittest.TestCase):
    def test_render_with_chapters_and_timestamps(self):
        cues = [(0.5, "hello"), (1.0, "hello"), (65, "second part"), (3700, "late")]
        chapters = [{"title": "Intro", "start_time": 0}, {"title": "Main", "start_time": 60}]
        text = transcript._render(cues, chapters, timestamps=True)
        self.assertEqual(text.count("hello"), 1)
        self.assertIn("[0:00] hello", text)
        self.assertIn("[1:05] second part", text)
        self.assertIn("[1:01:40] late", text)
        self.assertLess(text.index("Intro"), text.index("hello"))
        self.assertLess(text.index("Main"), text.index("second part"))

    def test_pick_track(self):
        info = {"language": "en", "subtitles": {"en-US": [], "de": []},
                "automatic_captions": {"en": [], "en-orig": [], "ar": []}}
        self.assertEqual(transcript.pick_track(info, "en"), ("en-US", "manual"))
        self.assertEqual(transcript.pick_track(info, "auto"), ("en-US", "manual"))
        self.assertEqual(transcript.pick_track(info, "ar"), ("ar", "YouTube auto-translated"))
        arabic_video = {"subtitles": {}, "automatic_captions": {"ar-orig": [], "ar": [], "en": []}}
        self.assertEqual(transcript.pick_track(arabic_video, "auto"), ("ar-orig", "auto-generated"))
        self.assertEqual(transcript.pick_track({"subtitles": {}, "automatic_captions": {}}, "auto"), (None, None))


class SizeTests(unittest.TestCase):
    def test_sizes_from_info(self):
        info = {"duration": 100, "formats": [
            {"format_id": "140", "acodec": "mp4a", "vcodec": "none", "filesize": 1_000_000},
            {"format_id": "137", "acodec": "none", "vcodec": "avc1", "height": 1080, "filesize": 20_000_000},
            {"format_id": "136", "acodec": "none", "vcodec": "avc1", "height": 720, "tbr": 800, "filesize": None},
            {"format_id": "18", "acodec": "mp4a", "vcodec": "avc1", "height": 360, "filesize": 3_000_000, "tbr": None},
        ]}
        with mock.patch.object(youtube, "HAS_FFMPEG", True):
            sizes = youtube.sizes_from_info(info)
        self.assertEqual(sizes["2"], "20.0 MB")    # 19.07 MiB video + 0.95 MiB audio
        self.assertTrue(sizes["3"].startswith("~"))  # estimated from bitrate
        self.assertEqual(sizes["5"], "2.9 MB")     # muxed format already has audio
        self.assertEqual(sizes["6"], "977 KB")

    def test_clean_error(self):
        e = Exception("\x1b[0;31mERROR:\x1b[0m [youtube] abcdefghijk: Video unavailable. This video is private")
        self.assertEqual(youtube.clean_error(e), "Video unavailable. This video is private")


class ProgressTests(unittest.TestCase):
    def setUp(self):
        reset_downloads()

    def test_duplicate_playlist_links_merge(self):
        config.PROGRESS_FILE.write_text(json.dumps({
            "https://youtube.com/playlist?list=PLsame&si=one": {"done": ["a_2"], "titles": {"a_2": "A"}},
            "https://youtube.com/playlist?list=PLsame&si=two": {"done": ["a_2", "b_2"], "titles": {"b_2": "B"}},
        }), encoding="utf-8")
        progress = progress_store.load_progress()
        self.assertEqual(list(progress), ["https://www.youtube.com/playlist?list=PLsame"])
        entry = progress["https://www.youtube.com/playlist?list=PLsame"]
        self.assertEqual(entry["done"], ["a_2", "b_2"])
        self.assertEqual(entry["titles"], {"a_2": "A", "b_2": "B"})
        # ...and the merge was saved
        self.assertEqual(list(json.loads(config.PROGRESS_FILE.read_text(encoding="utf-8"))),
                         ["https://www.youtube.com/playlist?list=PLsame"])

    def test_pending_keeps_options(self):
        progress_store.mark_single_pending("u", "3", "T", subtitle_mode="none", embed=None)
        self.assertEqual(progress_store.load_pending()["u"], {"quality": "3", "title": "T", "subtitle_mode": "none"})


if __name__ == "__main__":
    unittest.main()
