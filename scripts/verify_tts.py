"""Serve an isolated synthetic library for real-model/browser TTS acceptance."""
import argparse
import ast
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import wave
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from book_store import BookStore
from server import create_app, make_local_server, parse_epub


def sample_epub():
    from PIL import Image
    image = io.BytesIO()
    Image.new('RGB', (96, 48), (109, 144, 124)).save(image, 'PNG')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip')
        archive.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="content.opf"/></rootfiles></container>')
        archive.writestr('content.opf', '''<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>朗読の検証用文庫</dc:title><dc:creator>Fujimi TTS Test</dc:creator></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/><item id="image" href="image.png" media-type="image/png"/></manifest><spine><itemref idref="one"/></spine></package>''')
        archive.writestr('nav.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="one.xhtml#start">第一章 春の読書</a></li></ol></nav></body></html>')
        long_text = '静かな図書館で、窓から入るやわらかな光を感じながら、昨日借りてきた日本語の本をゆっくりと読み進め、新しい言葉の意味を確かめたり、物語に登場する人たちの気持ちを想像したりしていると、時間がたつのを忘れてしまい、気がつけば遠くの時計が午後の始まりを知らせていました。'
        archive.writestr('one.xhtml', f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>春の読書</title></head><body><h1 id="start">第一章 春の読書</h1><p><ruby>図書館<rt>としょかん</rt></ruby>で本を読みます。</p><figure><img src="image.png" alt="緑の挿絵"/></figure><p>{long_text}</p><p>明日もまた、この場所に来たいと思います。</p></body></html>')
        archive.writestr('image.png', image.getvalue())
    return output.getvalue()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8428)
    parser.add_argument('--smoke', action='store_true', help='Verify real paragraph synthesis, merge and reuse, then exit')
    parser.add_argument('--jkl', action='store_true', help='Use the exact first paragraph from JKL.py')
    parser.add_argument('--voice-file', type=Path, help='Reference WAV for isolated real-model verification')
    args = parser.parse_args()
    data = Path(tempfile.mkdtemp(prefix='fujimi-tts-acceptance-'))
    app = create_app(data, enable_tts=True)
    if args.voice_file:
        voice = app.extensions['tts'].voices.save(args.voice_file.stem, args.voice_file.read_bytes())
        app.extensions['tts'].setting('voice-mode', {'mode': 'voice', 'voice_id': voice['id']})
    text = '今日は図書館で本を読みました。窓の外では鳥が歌っています。静かな午後でした。\n明日も本を読みたいです。'
    if args.jkl:
        tree = ast.parse((Path(__file__).resolve().parents[1]/'Irodori-TTS/JKL.py').read_text(encoding='utf-8'))
        text = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'TEXT' for t in n.targets))
    expected_units = 1 if args.jkl else 2
    blob = sample_epub()
    book, resources = parse_epub(blob, '朗読検証.epub')
    bid, _ = BookStore(data).create(book, blob, resources)
    with app.test_client() as client:
        article = client.post('/api/articles/text', json={'title': '春の図書館', 'text': text}).json
    print(f'DATA={data}', flush=True)
    print(f"ARTICLE={article['id']} TASK={article.get('audio_task_id')} BOOK={bid}", flush=True)
    if args.smoke:
        controller = app.extensions['tts']
        try:
            deadline = time.monotonic() + 900
            previous = None
            while time.monotonic() < deadline:
                task = controller.queue.get(article['audio_task_id'])
                state = (task['status'], task['stage'], task['completed'], task['total'])
                if state != previous:
                    print(state, flush=True)
                    previous = state
                if task['status'] not in ('queued', 'running'):
                    break
                time.sleep(.5)
            assert task['status'] == 'completed', task
            assert task['completed'] == task['total'] == expected_units, task
            saved = controller.articles.load(article['id'])
            path = controller.articles.asset(article['id'], saved['audio_path'])
            with wave.open(str(path), 'rb') as audio:
                duration = audio.getnframes()/audio.getframerate()
                assert abs(duration-sum(s['duration'] for s in saved['audio_segments'])) < .002
            with app.test_client() as client:
                response = client.post(f"/api/articles/{article['id']}/reread", json={'mode': 'model', 'force': True})
                assert response.status_code == 200 and response.json['status'] == 'ready', response.json
                with client.get(response.json['article']['audio_path'], headers={'Range': 'bytes=0-43'}) as stream:
                    assert stream.status_code == 206 and stream.data[:4] == b'RIFF'
            assert not (data/'diagnostics/tts-tasks').exists()
            assert not (data/'tts').exists()
            print(json.dumps({'status': 'passed', 'paragraphs': expected_units, 'units': task['total'],
                'seconds': duration, 'audio': str(path), 'reused': True}, ensure_ascii=False), flush=True)
        finally:
            controller.close()
        sys.exit(0)
    http = make_local_server(app, '127.0.0.1', args.port)
    try:
        http.serve_forever()
    finally:
        app.extensions['tts'].close()
        http.server_close()
