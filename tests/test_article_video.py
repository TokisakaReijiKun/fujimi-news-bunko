import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from article_media import cache_media, download_hls
from server import WorkCancelled


class ArticleVideoTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg/ffprobe required')
    def test_standard_aes_hls_is_downloaded_and_decoded_with_local_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);key=root/'origin.key';key.write_bytes(bytes(range(16)))
            key_info=root/'key-info.txt';key_info.write_text('https://example.com/key\n'+key.as_posix()+'\n',encoding='utf8')
            playlist=root/'origin.m3u8'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=10',
                            '-t','1','-c:v','libx264','-hls_time','1','-hls_key_info_file',str(key_info),str(playlist)],
                           check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            def fetch(url):
                if url.endswith('/key'):return key.read_bytes(),url
                return (root/url.rsplit('/',1)[-1]).read_bytes(),url
            cached=cache_media({'videos':['https://example.com/origin.m3u8']},root,fetch)
            self.assertEqual(cached['media_warnings'],[])
            output=root/cached['video_urls'][0].removeprefix('/api/media/')
            result=subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(output)],
                                  check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(json.loads(result.stdout)['streams'][0]['codec_name'],'h264')

    def test_rejects_live_encrypted_and_unsafe_segments(self):
        playlists=[b'#EXTM3U\n#EXTINF:1,\na.ts\n',
                   b'#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"\na.ts\n#EXT-X-ENDLIST',
                   b'#EXTM3U\nfile:///private.ts\n#EXT-X-ENDLIST']
        with tempfile.TemporaryDirectory() as directory:
            for playlist in playlists:
                fetch=Mock(return_value=(playlist,'https://example.com/a.m3u8'))
                with self.assertRaises(ValueError):download_hls('https://example.com/a.m3u8',Path(directory),fetch)
                self.assertEqual(fetch.call_count,1)

    def test_cancellation_cannot_become_media_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(WorkCancelled):
                cache_media({'videos':['https://example.com/a.mp4']},directory,
                            Mock(side_effect=WorkCancelled()),cancelled_error=WorkCancelled)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg/ffprobe required')
    def test_hls_segments_produce_decodable_local_mp4(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);segment=root/'sample.ts'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=10',
                            '-t','1','-c:v','libx264','-f','mpegts',str(segment)],check=True,
                           capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            def fetch(url):
                if url.endswith('.m3u8'):
                    return b'#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\na.ts\n#EXT-X-ENDLIST',url
                self.assertEqual(url,'https://example.com/a.ts')
                return segment.read_bytes(),url
            cached=cache_media({'videos':['https://example.com/a.m3u8']},root,fetch)
            self.assertEqual(cached['media_warnings'],[])
            output=root/cached['video_urls'][0].removeprefix('/api/media/')
            result=subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(output)],
                                  check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(json.loads(result.stdout)['streams'][0]['codec_name'],'h264')
