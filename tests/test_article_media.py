import shutil
import subprocess
import tempfile
import unittest
import json
from pathlib import Path

from article_media import download_hls


class HlsMediaTest(unittest.TestCase):
    @staticmethod
    def _mpegts(*inputs):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise unittest.SkipTest("ffmpeg is required for HLS media tests")
        result = subprocess.run(
            [ffmpeg, "-nostdin", "-v", "error", *inputs, "-f", "mpegts", "pipe:1"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout

    def test_discovers_aac_after_video_only_lead(self):
        # MPEG-TS can announce AAC in the PMT before audio packets begin. A short
        # default probe can see the video while leaving AAC parameters unset.
        segment = self._mpegts(
            "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
            "-itsoffset", "8", "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000",
            "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        )
        url = "https://media.example.test/video.m3u8"
        files = {
            url: b"#EXTM3U\n#EXT-X-TARGETDURATION:12\n#EXTINF:12,\nvideo.ts\n#EXT-X-ENDLIST\n",
            "https://media.example.test/video.ts": segment,
        }
        with tempfile.TemporaryDirectory() as folder:
            output = download_hls(url, Path(folder), lambda address: (files[address], address))
            ffprobe = shutil.which("ffprobe")
            if not ffprobe:
                self.skipTest("ffprobe is required for HLS media tests")
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "stream=codec_name,codec_type,sample_rate",
                 "-of", "json", "-i", "pipe:0"],
                input=output, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            audio = [item for item in json.loads(result.stdout)["streams"] if item["codec_type"] == "audio"]
            self.assertEqual(len(audio), 1)
            self.assertEqual(audio[0]["codec_name"], "aac")
            self.assertEqual(audio[0]["sample_rate"], "48000")

    def test_master_playlist_keeps_separate_audio_rendition(self):
        video = self._mpegts(
            "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-t", "1",
            "-an", "-c:v", "mpeg2video", "-g", "10",
        )
        audio = self._mpegts(
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=8000", "-t", "1",
            "-vn", "-c:a", "mp2",
        )
        root_url = "https://media.example.test/"
        files = {
            root_url + "master.m3u8": (
                b"#EXTM3U\n"
                b'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="main",DEFAULT=YES,URI="audio.m3u8"\n'
                b'#EXT-X-STREAM-INF:BANDWIDTH=100000,AUDIO="audio"\n'
                b"video.m3u8\n"
            ),
            root_url + "video.m3u8": b"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nvideo.ts\n#EXT-X-ENDLIST\n",
            root_url + "audio.m3u8": b"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\naudio.ts\n#EXT-X-ENDLIST\n",
            root_url + "video.ts": video,
            root_url + "audio.ts": audio,
        }

        def fetch(url):
            return files[url], url

        with tempfile.TemporaryDirectory() as folder:
            output = download_hls(root_url + "master.m3u8", Path(folder), fetch)
            ffprobe = shutil.which("ffprobe")
            if not ffprobe:
                self.skipTest("ffprobe is required for HLS media tests")
            streams = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", "-i", "pipe:0"],
                input=output,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.decode().replace(",", "").splitlines()
            self.assertIn("video", streams)
            self.assertIn("audio", streams)


if __name__ == "__main__":
    unittest.main()
