"""Generate real local VOICEVOX samples only for the isolated demo."""
from pathlib import Path
import hashlib
import io
import json
import sys
import wave

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from browser_tts import BrowserTTS


def main():
    content = json.loads((HERE / 'demo-content.json').read_text(encoding='utf-8'))
    output = HERE / 'demo-audio'
    output.mkdir(exist_ok=True)
    groups = {}
    for article in content['articles']:
        groups['article:' + article['id']] = [p['ja'] for p in article['paragraphs']]
    for book in content['books']:
        for index, chapter in enumerate(book['chapters']):
            groups[f"book:{book['id']}:{index}"] = chapter['paragraphs']
    for word in content['words']:
        groups['word:' + word['id']] = [word['kana'] + '。' + word['ja']]
    manifest = {'voice': {'id': 'voicevox:8', 'name': '春日部つむぎ'}, 'groups': {}}
    synthesizer = BrowserTTS(ROOT)
    try:
        for group, texts in groups.items():
            segments = []
            for index, text in enumerate(texts):
                digest = hashlib.sha256((manifest['voice']['id'] + '\n' + text).encode('utf-8')).hexdigest()[:16]
                target = output / f'{digest}.wav'
                if not target.exists():
                    audio = synthesizer.synthesize(text, manifest['voice']['id'])
                    with wave.open(io.BytesIO(audio), 'rb') as sample:
                        assert sample.getnframes() > 0
                    target.write_bytes(audio)
                with wave.open(str(target), 'rb') as sample:
                    duration = sample.getnframes() / sample.getframerate()
                segments.append({'url': 'demo-audio/' + target.name, 'duration': duration, 'paragraph': index})
            manifest['groups'][group] = segments
            print(json.dumps({'group': group, 'segments': len(segments)}, ensure_ascii=False), flush=True)
        (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        synthesizer.close()


if __name__ == '__main__':
    main()
