"""Custom reference voices sync as validated WAV files, without transcoding."""
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
import unicodedata
import wave
import zipfile

from article_store import ArticleStore
from book_store import BookStore
from example_store import ExampleStore
from library_sync import LibrarySync, LibrarySyncError
from tts_service import VoiceStore


def wav_blob(seconds=1, frequency=220, channels=1, silent=False):
    output = io.BytesIO()
    frames = b''.join(struct.pack('<h', 0 if silent else int(12000 * math.sin(2 * math.pi * frequency * n / 8000))) * channels
                      for n in range(int(8000 * seconds)))
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(frames)
    return output.getvalue()


def voice_bundle(name, blob, *, filename=None, key=None, extra=None):
    filename = filename or name + '.wav'
    files = {filename: blob, **(extra or {})}
    record = dict(version=1, kind='voice', title=name,
                  key=key or 'voice:' + hashlib.sha256(unicodedata.normalize('NFC', name).encode()).hexdigest(),
                  files=[dict(path=path, size=len(value), sha256=hashlib.sha256(value).hexdigest())
                         for path, value in files.items()])
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('bundle.json', json.dumps(record, ensure_ascii=False))
        for path, value in files.items():
            archive.writestr('files/' + path, value)
    return output.getvalue()


class VoiceSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.voices = []
        self.sync = []
        for side in ('pc', 'phone'):
            data = self.root / side
            article = ArticleStore(data)
            self.voices.append(VoiceStore(data))
            self.sync.append(LibrarySync(article, BookStore(data), ExampleStore(data, article)))

    def test_manifest_and_bundle_include_the_exact_reference_wav(self):
        name = '朽木冬子'
        blob = wav_blob(channels=2)
        (self.voices[0].root / (name + '.wav')).write_bytes(blob)
        manifest = self.sync[0].manifest()
        voices = [item for item in manifest['items'] if item['kind'] == 'voice']
        self.assertEqual(len(voices), 1, manifest)
        expected_key = 'voice:' + hashlib.sha256(name.encode()).hexdigest()
        self.assertEqual(voices[0]['key'], expected_key)
        self.assertEqual(voices[0]['title'], name)
        with zipfile.ZipFile(io.BytesIO(self.sync[0].export_bundle(expected_key))) as archive:
            self.assertEqual(set(archive.namelist()), {'bundle.json', 'files/朽木冬子.wav'})
            self.assertEqual(archive.read('files/朽木冬子.wav'), blob)

    def test_valid_voice_round_trip_preserves_bytes_and_stable_id(self):
        name = '自定义声线'
        blob = wav_blob(channels=2)
        bundle = voice_bundle(name, blob)
        first = self.sync[1].import_bundle(bundle)
        self.assertEqual(first['status'], 'created')
        self.assertEqual(first['kind'], 'voice')
        self.assertEqual(first['id'], int(hashlib.sha256(name.encode()).hexdigest()[:12], 16))
        saved = self.voices[1].get(first['id'])
        self.assertEqual(self.voices[1].reference(saved).read_bytes(), blob)
        self.assertEqual(sorted(path.name for path in self.voices[1].root.iterdir()), [name + '.wav'])
        self.assertEqual(self.sync[1].import_bundle(bundle)['status'], 'unchanged')
        returned = self.sync[0].import_bundle(self.sync[1].export_bundle(first['key']))
        self.assertEqual(returned['status'], 'created')
        self.assertEqual(self.voices[0].reference(self.voices[0].get(first['id'])).read_bytes(), blob)

    def test_same_name_different_audio_is_a_conflict_without_overwrite(self):
        saved = self.voices[1].save('同名声线', wav_blob(frequency=110))
        original = self.voices[1].reference(saved).read_bytes()
        result = self.sync[1].import_bundle(voice_bundle('同名声线', wav_blob(frequency=440)))
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(self.voices[1].reference(saved).read_bytes(), original)
        self.assertEqual(len(self.voices[1].list()), 1)

    def test_invalid_voice_payload_is_rejected_before_creating_files(self):
        cases = [
            ('short', voice_bundle('短音频', wav_blob(seconds=.5))),
            ('long', voice_bundle('长音频', wav_blob(seconds=121))),
            ('silent', voice_bundle('静音', wav_blob(silent=True))),
            ('multichannel', voice_bundle('多声道', wav_blob(channels=3))),
            ('not-wav', voice_bundle('错误格式', b'not a wav')),
            ('different-name', voice_bundle('真实名称', wav_blob(), filename='其他名称.wav')),
            ('bad-id', voice_bundle('错误标识', wav_blob(), key='voice:' + '0' * 64)),
            ('extra-file', voice_bundle('多余文件', wav_blob(), extra={'voice.json': b'{}'})),
            ('bad-name', voice_bundle('CON', wav_blob())),
            ('nested-path', voice_bundle('嵌套目录', wav_blob(), filename='sub/嵌套目录.wav')),
            ('oversized', voice_bundle('超大文件', b'0' * (20 * 1024 * 1024 + 1))),
        ]
        for label, bundle in cases:
            with self.subTest(label=label):
                with self.assertRaises(LibrarySyncError):
                    self.sync[1].import_bundle(bundle)
                self.assertEqual(list(self.voices[1].root.iterdir()), [])

    def test_nfc_name_is_used_for_identity_and_destination(self):
        name = unicodedata.normalize('NFC', 'か\u3099')
        blob = wav_blob()
        result = self.sync[1].import_bundle(voice_bundle(name, blob))
        self.assertEqual(result['id'], VoiceStore._id(name))
        self.assertEqual(self.voices[1].list()[0]['name'], name)

    def test_browser_voice_directory_only_exposes_portable_catalog_fields(self):
        directory = [dict(id='kokoro:jf_alpha', name='アルファ', provider='kokoro', lang='ja-JP',
                          model='private-model-file', available=False, detail='local dependency details')]
        article = self.sync[0].articles
        sync = LibrarySync(article, self.sync[0].books, self.sync[0].examples,
                           browser_voices=lambda: directory)
        self.assertEqual(sync.manifest()['browser_voices'], [
            dict(id='kokoro:jf_alpha', name='アルファ', provider='kokoro', lang='ja-JP')])
        directory.append(dict(id='voicevox:8', name='春日部つむぎ', provider='voicevox', lang='ja-JP'))
        self.assertEqual(len(sync.manifest()['browser_voices']), 2)


if __name__ == '__main__':
    unittest.main()
