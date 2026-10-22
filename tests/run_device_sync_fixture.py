"""Temporary PC library for browser/emulator acceptance; never loads personal configuration."""
import argparse
import io
import json
import hashlib
import math
from pathlib import Path
import struct
import sys
import tempfile
import wave
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import create_app, make_local_server
from epub_parser import parse_epub
from tts_service import VoiceStore
from tts_integration import TTSController


def tone_wav(frequency, seconds=6, sample_rate=24000):
    """Audible, deterministic PCM fixtures; never invoke a speech service/model."""
    frames = bytearray()
    count = int(sample_rate * seconds)
    for index in range(count):
        envelope = min(1, index / (sample_rate * .02), (count - index - 1) / (sample_rate * .02))
        frames.extend(struct.pack('<h', int(10000 * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))))
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(frames)
    return output.getvalue()


def seed_voice_acceptance(app, root):
    """Seed two distinguishable full recordings using the production naming/store APIs."""
    library = app.extensions['device_sync'].library
    voice_store = VoiceStore(root)
    voice = voice_store.save('同期テスト声線', tone_wav(220, seconds=1))
    title = '声線同期・二つの録音'
    article = library.articles.create(dict(title=title, url='https://example.test/device-sync/voice-audio',
        paragraphs=['一つ目の声を確かめます。', '二つ目の声を確かめます。'],
        translated_paragraphs=['确认第一条声线。', '确认第二条声线。'], furigana_paragraphs=[],
        source_name='声线同步验收', status='ready', created_at='2026-10-17T10:01:00+08:00'), '2026-10-17')
    specs = []
    with tempfile.TemporaryDirectory(prefix='fujimi-voice-fixture-') as temporary:
        files = {}
        for name, frequency, mode, identifier in [(voice['name'], 440, 'voice', voice['id']), ('アルファ', 880, 'browser', 'kokoro:jf_alpha')]:
            relative = 'audio/' + TTSController._article_audio_filename(name, title)
            blob = tone_wav(frequency)
            source = Path(temporary) / (name + '.wav')
            source.write_bytes(blob)
            files[relative] = source
            specs.append(dict(name=name, mode=mode, voice_id=identifier, path=relative, sha256=hashlib.sha256(blob).hexdigest(),
                              duration=6, frequency=frequency, sample_rate=24000))
        article.update(audio_status='ready', audio_path=specs[0]['path'], audio_voice_mode='voice',
                       audio_voice_id=voice['id'], audio_voice_name=voice['name'],
                       audio_segments=[dict(duration=3, speech_start_offset=0), dict(duration=3, speech_start_offset=0)])
        article = library.articles.save_tts(article, files=files)
    missing = library.articles.create(dict(title='声線同期・録音なし', url='https://example.test/device-sync/voice-missing',
        paragraphs=['この本文には同期済みの音声がありません。'], translated_paragraphs=[], furigana_paragraphs=[],
        source_name='声线同步验收', status='ready', created_at='2026-10-17T10:02:00+08:00'), '2026-10-17')
    return dict(fixture='voice-sync-v1', date='2026-10-17', voice=voice,
                article=dict(id=article['id'], title=article['title'], url=article['url'], recordings=specs),
                missing=dict(id=missing['id'], title=missing['title'], url=missing['url']))


def seed_synced_audio_acceptance(app, voice):
    """Legacy metadata and long WAVs exercise the real Android Media3 route."""
    library = app.extensions['device_sync'].library
    day = '2026-10-18'
    old_title = '作成当時の長い見出し・声線名の保存を始める前に完成した新聞の朗読'
    article = library.articles.create(dict(title=old_title,
        url='https://example.test/device-sync/legacy-registered-audio',
        paragraphs=['保存済みの最初の段落を聞きます。', '三十秒後の二番目の段落です。', '最後まで録音された三番目の段落です。'],
        translated_paragraphs=['听取已保存的第一段。', '三十秒后的第二段。', '完整录音的第三段。'],
        furigana_paragraphs=[], source_name='旧録音同期の検証', status='ready',
        created_at=day + 'T10:00:00+08:00'), day)
    article_relative = 'audio/旧仕様_作成当時の長い見出し_全編録音.wav'
    book_filename = '旧録音 第一章 #50% 完全版.wav'
    specs = {}
    with tempfile.TemporaryDirectory(prefix='fujimi-legacy-audio-fixture-') as temporary:
        sources = {}
        for kind, frequency, relative in [('article', 330, article_relative), ('book', 660, book_filename)]:
            blob = tone_wav(frequency, seconds=90, sample_rate=48000)
            source = Path(temporary) / (kind + '.wav')
            source.write_bytes(blob)
            sources[kind] = source
            specs[kind] = dict(path=relative, sha256=hashlib.sha256(blob).hexdigest(),
                               duration=90, frequency=frequency, sample_rate=48000, channels=1, bits=16)
        segments = [dict(duration=30, speech_start_offset=0) for _ in range(3)]
        article.update(audio_status='ready', audio_path=article_relative, audio_voice_mode='voice',
                       audio_voice_id=voice['id'], audio_segments=segments)
        article = library.articles.save_tts(article, files={article_relative: sources['article']})
        # Renaming must not break the explicitly registered, old-format filename.
        article = library.articles.patch(article['id'], {'title': '同期録音・改題した新聞'})
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('mimetype', 'application/epub+zip')
            z.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
            z.writestr('content.opf', '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">legacy-audio-qa-v1</dc:identifier><dc:title>同期録音・特殊文字のある本</dc:title><dc:language>ja</dc:language></metadata><manifest><item id="ch" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="ch"/></spine></package>')
            z.writestr('nav.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="chapter.xhtml">保存済みの第一章</a></li></ol></nav></body></html>')
            z.writestr('chapter.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>保存済みの第一章</title></head><body><p>保存済みの本の最初の段落です。</p><p>三十秒後の二番目の段落です。</p><p>最後まで録音された三番目の段落です。</p></body></html>')
        epub = archive.getvalue()
        book, assets = parse_epub(epub, '特殊文字の録音.epub')
        chapter = book['chapters'][0]
        chapter.update(voice_mode='voice', audio=dict(status='ready', path=book_filename,
                       voice_id=voice['id'], segments=segments))
        bid, duplicate = library.books.create(book, epub, assets, audio_files={book_filename: sources['book']})
        assert not duplicate
        book = library.books.load(bid)
    assert 'audio_voice_name' not in article and 'audio_voice_sha256' not in article
    assert 'voice_name' not in book['chapters'][0]['audio'] and 'voice_sha256' not in book['chapters'][0]['audio']
    return dict(fixture='synced-audio-v1', date=day, voice=dict(id=voice['id'], name=voice['name']),
        article=dict(id=article['id'], title=article['title'], old_title=old_title, url=article['url'], recording=specs['article']),
        book=dict(id=bid, title=book['title'], chapter_id=book['chapters'][0]['id'], recording=specs['book']),
        missing_voice=dict(mode='browser', id='kokoro:jf_alpha', name='アルファ'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--port', type=int, default=18428)
    parser.add_argument('--sync-port', type=int, default=18429)
    parser.add_argument('--prepare-only', action='store_true', help='Validate and seed temporary content without opening either server.')
    args = parser.parse_args()
    if not 18000 <= args.port <= 18999 or not 18000 <= args.sync_port <= 18999 or args.port == args.sync_port:
        raise ValueError('Acceptance ports must be distinct 18xxx ports.')
    root = Path(args.data).resolve()
    if root.exists():
        raise RuntimeError('Acceptance data must be a new isolated directory.')
    app = create_app(root)
    app.extensions['device_sync'].port = args.sync_port
    library = app.extensions['device_sync'].library
    library.articles.create(dict(title='同步验收・PCから', url='https://example.test/device-sync/pc',
        paragraphs=['これはパソコンから同期した本文です。'], translated_paragraphs=['这是从电脑同步的正文。'],
        furigana_paragraphs=[], source_name='同步验收', status='ready', created_at='2026-10-17T10:00:00+08:00'), '2026-10-17')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr('content.opf', '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">sync-qa</dc:identifier><dc:title>同期した本</dc:title><dc:language>ja</dc:language></metadata><manifest><item id="ch" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="ch"/></spine></package>')
        z.writestr('nav.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="chapter.xhtml">第一章</a></li></ol></nav></body></html>')
        z.writestr('chapter.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>第一章</title></head><body><h1>第一章</h1><p>これは同期した本の本文です。</p></body></html>')
    blob = archive.getvalue()
    book, assets = parse_epub(blob, '同期した本.epub')
    library.books.create(book, blob, assets)
    library.examples.create('同步验收例文', '同期した例文です。')
    fixture = seed_voice_acceptance(app, root)
    fixture.update(port=args.port, sync_port=args.sync_port, data=str(root))
    app.add_url_rule('/api/test/voice-sync-fixture', 'voice_sync_fixture', lambda: fixture)
    synced_audio = seed_synced_audio_acceptance(app, fixture['voice'])
    synced_audio.update(port=args.port, sync_port=args.sync_port, data=str(root))
    app.add_url_rule('/api/test/synced-audio-fixture', 'synced_audio_fixture', lambda: synced_audio)
    print(json.dumps(fixture, ensure_ascii=False), flush=True)
    print(json.dumps(synced_audio, ensure_ascii=False), flush=True)
    server = None
    try:
        if args.prepare_only:
            return
        server = make_local_server(app, '127.0.0.1', args.port)
        server.serve_forever()
    finally:
        app.extensions['device_sync'].shutdown()
        app.extensions['tts'].close()
        app.extensions['browser_tts'].close()
        if server:
            server.server_close()


if __name__ == '__main__':
    main()
