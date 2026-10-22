"""Paired-device library bundles, imported through the existing file stores.

The wire format contains only one entity's authoritative content files. It never
contains indexes, settings, credentials, tasks, or an instruction to delete data.
"""
from copy import deepcopy
from datetime import date, datetime
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

from article_store import digest, edition_storage_key, safe_path
from epub_parser import sanitize
from tts_service import VoiceStore


MAX_BUNDLE_BYTES = 512 * 1024 * 1024
MAX_FILES = 10000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_LOCAL_STATE = {'id', 'progress', 'last_read_at', 'audio_time', 'reading_position',
                'bookmark_directory', 'cover_url'}


class LibrarySyncError(ValueError):
    pass


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _json_file(folder, name):
    return json.loads(safe_path(folder, name).read_text(encoding='utf-8'))


def _path(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise LibrarySyncError('同步包包含不安全路径。')
    parts = value.split('/')
    if any(not part or part in ('.', '..') or part.endswith((' ', '.')) or
           re.search(r'[\x00-\x1f<>"|?*]', part) or
           re.match(r'^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$)', part, re.I)
           for part in parts):
        raise LibrarySyncError('同步包包含不安全路径。')
    return value


def _complete_audio(path):
    value = str(path).lower()
    return (PurePosixPath(value).suffix in ('.wav', '.mp3') and '_segment_' not in value
            and '.part' not in value and '.tmp' not in value)


def _article_key(article):
    key = article.get('storage_key')
    if not key and article.get('url') and article.get('edition_dates'):
        key = edition_storage_key(article['url'], article['edition_dates'][0])
    if not isinstance(key, str) or not key:
        raise LibrarySyncError('文章缺少跨设备可用的存储标识。')
    return 'article:' + key


def _missing(local, incoming, excluded=()):
    """Preserve local metadata and fill only fields without a local value."""
    result = deepcopy(local)
    for key, value in incoming.items():
        if key in _LOCAL_STATE or key in excluded or key.startswith('_') or 'task' in key:
            continue
        if not result.get(key) and value:
            result[key] = deepcopy(value)
    return result


def _merge_text(local, incoming, label):
    if not incoming:
        return deepcopy(local)
    if not local:
        return deepcopy(incoming)
    if len(local) != len(incoming):
        raise LibrarySyncError(label + '段落数量冲突，已保留本机内容。')
    result = []
    for old, new in zip(local, incoming):
        if old and new and old != new:
            raise LibrarySyncError(label + '内容冲突，已保留本机内容。')
        result.append(old or new)
    return result


class LibrarySync:
    def __init__(self, article_store, book_store, example_store, voice_store=None, browser_voices=None):
        self.articles = article_store
        self.books = book_store
        self.examples = example_store
        self.voices = voice_store or VoiceStore(article_store.data)
        self.browser_voices = browser_voices

    def _entities(self):
        for identifier in self.articles.ids():
            yield 'article', identifier
        for identifier in self.books.ids():
            yield 'book', identifier
        for item in self.examples.list():
            yield 'example', item['id']
        for voice in self.voices.list():
            yield 'voice', voice['name']

    def _lock_for(self, kind):
        if kind == 'voice':
            return self.voices.lock
        return (self.books.locks if kind == 'book' else self.examples.locks if kind == 'example' else self.articles).locked()

    def _read_entity(self, kind, identifier):
        if kind == 'voice':
            return self.voices.root
        if kind == 'article':
            item = self.articles.load(identifier)
            return safe_path(self.articles.root, item['_directory'])
        if kind == 'book':
            self.books.load(identifier)
            return self.books.folder(identifier)
        item = self.examples.get(identifier)
        return safe_path(self.examples.root, item['directory'])

    def _decode(self, kind, folder, voice_name=None):
        """Validate authoritative records and list the only allowed files."""
        if kind == 'voice':
            if not isinstance(voice_name, str) or VoiceStore._name(voice_name) != voice_name:
                raise LibrarySyncError('同步声线名称必须为规范化的有效名称。')
            path = safe_path(folder, voice_name + '.wav')
            if path.stat().st_size > 20 * 1024 * 1024:
                raise LibrarySyncError('参考音频须为 20 MB 以内的非空文件。')
            item = self.voices.validate_synced(voice_name, path.read_bytes())
            item['title'] = item['name']
            paths = {item['file']}
            key = 'voice:' + digest(item['name'].encode('utf-8'))
        elif kind == 'article':
            item = self.articles._read(folder, verify_media=True)
            paths = {'article.json', 'original.txt', 'translation.txt', 'furigana.html'}
            paths.update(entry['path'] for entry in item['_assets'])
            if (folder / 'audio').is_dir():
                paths.update(p.relative_to(folder).as_posix() for p in (folder / 'audio').rglob('*')
                             if p.is_file() and _complete_audio(p.name))
            if item.get('audio_path') and item['audio_path'] not in paths:
                raise LibrarySyncError('文章引用的完整音频缺失。')
            paragraphs = item.get('paragraphs', [])
            if not paragraphs or not all(isinstance(p, str) and p.strip() for p in paragraphs):
                raise LibrarySyncError('文章没有有效正文。')
            for field in ('translated_paragraphs', 'furigana_paragraphs'):
                values = item.get(field, [])
                if values and (len(values) != len(paragraphs) or not all(isinstance(p, str) for p in values)):
                    raise LibrarySyncError('文章增强文本段落数不匹配。')
            key = _article_key(item)
        elif kind == 'book':
            meta = _json_file(folder, 'book.json')
            if meta.get('version') != 2:
                raise LibrarySyncError('不支持的书籍文件格式。')
            source = _path(meta.get('source_file', 'source.epub'))
            if '/' in source or not source.lower().endswith('.epub'):
                raise LibrarySyncError('原始 EPUB 文件名不正确。')
            source_hash = digest(safe_path(folder, source).read_bytes())
            if source_hash != meta.get('source_sha256') or source_hash != meta.get('digest'):
                raise LibrarySyncError('原始 EPUB 校验失败。')
            item = deepcopy(meta['book'])
            item.update(_json_file(folder, 'state.json'))
            paths = {'book.json', 'state.json', source}
            for chapter in item['chapters']:
                relative = _path(chapter['file'])
                if not relative.startswith('chapters/') or not relative.endswith('.json'):
                    raise LibrarySyncError('章节路径不正确。')
                content = safe_path(folder, relative).read_bytes()
                if digest(content) != chapter['sha256']:
                    raise LibrarySyncError('章节校验失败。')
                chapter.update(json.loads(content))
                paths.add(relative)
            for group in ('resources', 'audio'):
                for relative, spec in meta.get(group, {}).items():
                    _path(relative)
                    if group == 'audio' and not _complete_audio(relative):
                        continue
                    path = group + '/' + relative
                    content = safe_path(folder, path).read_bytes()
                    if digest(content) != spec['sha256']:
                        raise LibrarySyncError('书籍附件校验失败：' + path)
                    paths.add(path)
            for chapter in item['chapters']:
                for audio in [chapter.get('audio'), *chapter.get('audio_versions', [])]:
                    if audio and (not isinstance(audio, dict) or 'audio/' + str(audio.get('path', '')) not in paths):
                        raise LibrarySyncError('书籍引用的完整音频缺失。')
            item['_source_file'] = source
            key = 'book:' + source_hash
        elif kind == 'example':
            meta = _json_file(folder, 'example.json')
            original = safe_path(folder, 'original.txt').read_bytes()
            if digest(original) != meta.get('text_sha256'):
                raise LibrarySyncError('示例正文校验失败。')
            item = deepcopy(meta)
            item['title'] = self.examples._clean_text(item.get('title'), '标题', 500)
            item['text'] = self.examples._clean_text(original.decode('utf-8'), '正文', 100000)
            paths = {'example.json', 'original.txt'}
            item['translated_paragraphs'] = []
            translation = folder / 'translation.txt'
            if translation.is_file():
                content = translation.read_bytes()
                if digest(content) != meta.get('translation_sha256'):
                    raise LibrarySyncError('示例译文校验失败。')
                item['translated_paragraphs'] = content.decode('utf-8').split('\n\n') if content else []
                paths.add('translation.txt')
            if item['translated_paragraphs'] and len(item['translated_paragraphs']) != len(self.examples.paragraphs(item['text'])):
                raise LibrarySyncError('示例译文段落数量不匹配。')
            for version in item.get('audio_versions', []):
                path = _path(version['path'])
                if not path.startswith('audio/') or not _complete_audio(path):
                    raise LibrarySyncError('示例音频路径不正确。')
                content = safe_path(folder, path).read_bytes()
                if version.get('audio_sha256') and digest(content) != version['audio_sha256']:
                    raise LibrarySyncError('示例音频校验失败。')
                paths.add(path)
            key = 'example:' + digest(item['title'].encode('utf-8'))
        else:
            raise LibrarySyncError('不支持的同步内容类型。')
        if not isinstance(item.get('title'), str) or not item['title'].strip():
            raise LibrarySyncError('同步内容缺少标题。')
        for path in paths:
            _path(path)
            candidate = safe_path(folder, path)
            if candidate.is_symlink() or not candidate.is_file():
                raise LibrarySyncError('同步内容文件缺失。')
        return key, item, paths

    def _describe(self, kind, identifier):
        folder = self._read_entity(kind, identifier)
        key, item, paths = self._decode(kind, folder, identifier if kind == 'voice' else None)
        specs = []
        total = 0
        for relative in sorted(paths):
            blob = safe_path(folder, relative).read_bytes()
            total += len(blob)
            if total > MAX_BUNDLE_BYTES:
                raise LibrarySyncError('单项内容超过 512 MiB 同步上限。')
            specs.append(dict(path=relative, sha256=digest(blob), size=len(blob)))
        record = dict(version=1, kind=kind, key=key, title=item['title'], files=specs)
        return record, folder

    def manifest(self):
        items, errors = [], []
        entities = []
        try:
            for entity in self._entities():
                entities.append(entity)
        except (OSError, ValueError, KeyError, LookupError) as error:
            errors.append(dict(detail=str(error)))
        for kind, identifier in entities:
            try:
                with self._lock_for(kind):
                    record, _ = self._describe(kind, identifier)
                    items.append({k: record[k] for k in ('key', 'kind', 'title')} |
                                 {'fingerprint': digest(_json_bytes(record['files']))})
            except (OSError, ValueError, KeyError, LookupError) as error:
                errors.append(dict(kind=kind, id=identifier, detail=str(error)))
        browser_voices = []
        if self.browser_voices is not None:
            browser_voices = [{field: voice[field] for field in ('id', 'name', 'provider', 'lang')}
                              for voice in self.browser_voices()]
        return dict(version=1, items=items, errors=errors, browser_voices=browser_voices)

    def export_bundle(self, key):
        for kind, identifier in self._entities():
            if not isinstance(key, str) or not key.startswith(kind + ':'):
                continue
            with self._lock_for(kind):
                try:
                    folder = self._read_entity(kind, identifier)
                    candidate, _, _ = self._decode(kind, folder, identifier if kind == 'voice' else None)
                except (OSError, ValueError, KeyError, LookupError):
                    # Invalid entities are reported by manifest; they must not
                    # prevent a different, validated entity from being sent.
                    continue
                if candidate != key:
                    continue
                record, folder = self._describe(kind, identifier)
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('bundle.json', _json_bytes(record))
                    for spec in record['files']:
                        archive.write(safe_path(folder, spec['path']), 'files/' + spec['path'])
                result = stream.getvalue()
                if len(result) > MAX_BUNDLE_BYTES:
                    raise LibrarySyncError('单项同步包超过 512 MiB。')
                return result
        raise LibrarySyncError('同步内容不存在。')

    def _unpack(self, content, folder):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) > MAX_FILES + 1 or len(set(names)) != len(names) or len({n.casefold() for n in names}) != len(names):
                raise LibrarySyncError('同步包文件重复或数量过多。')
            if 'bundle.json' not in names or archive.getinfo('bundle.json').file_size > MAX_MANIFEST_BYTES:
                raise LibrarySyncError('同步包清单缺失或过大。')
            if sum(info.file_size for info in infos) > MAX_BUNDLE_BYTES:
                raise LibrarySyncError('同步包展开后超过 512 MiB。')
            if any(info.flag_bits & 1 or (info.external_attr >> 16) & 0o170000 == 0o120000 for info in infos):
                raise LibrarySyncError('同步包不能包含加密文件或符号链接。')
            record = json.loads(archive.read('bundle.json'))
            if record.get('version') != 1 or not isinstance(record.get('files'), list):
                raise LibrarySyncError('不支持的同步包格式。')
            if record.get('kind') == 'voice' and (len(record['files']) != 1
                    or sum(info.file_size for info in infos if info.filename != 'bundle.json') > 20 * 1024 * 1024):
                raise LibrarySyncError('声线同步包只能包含一个 20 MB 以内的 WAV 文件。')
            expected = {'bundle.json'}
            for spec in record['files']:
                relative = _path(spec['path'])
                name = 'files/' + relative
                if name in expected:
                    raise LibrarySyncError('同步包清单含重复路径。')
                expected.add(name)
                if name not in names or type(spec.get('size')) is not int or spec['size'] < 0 or archive.getinfo(name).file_size != spec['size']:
                    raise LibrarySyncError('同步文件长度不匹配。')
                blob = archive.read(name)
                if digest(blob) != spec.get('sha256'):
                    raise LibrarySyncError('同步文件 SHA-256 校验失败。')
                target = safe_path(folder, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
            if set(names) != expected:
                raise LibrarySyncError('同步包包含未登记文件。')
            key, item, allowed = self._decode(record.get('kind'), folder, record.get('title') if record.get('kind') == 'voice' else None)
            if key != record.get('key') or {'files/' + path for path in allowed} != expected - {'bundle.json'}:
                raise LibrarySyncError('同步内容标识或文件清单不匹配。')
            return record, item

    def import_bundle(self, content, expected_sha256=None):
        if not isinstance(content, bytes) or not content or len(content) > MAX_BUNDLE_BYTES:
            raise LibrarySyncError('同步包为空或超过 512 MiB。')
        if expected_sha256 is not None and digest(content) != expected_sha256:
            raise LibrarySyncError('同步包 SHA-256 校验失败。')
        try:
            with tempfile.TemporaryDirectory(prefix='fujimi-sync-') as temporary:
                folder = Path(temporary)
                record, incoming = self._unpack(content, folder)
                if record['kind'] == 'article':
                    incoming['furigana_paragraphs'] = [sanitize(value, '', {}) for value in incoming.get('furigana_paragraphs', [])]
                elif record['kind'] == 'book':
                    assets = {spec['path'][len('resources/'):] for spec in record['files'] if spec['path'].startswith('resources/')}
                    for chapter in incoming['chapters']:
                        for block in chapter.get('blocks', []):
                            for field in ('html', 'furigana_html'):
                                if block.get(field):
                                    block[field] = sanitize(block[field], block.get('source_href') or chapter.get('source_href', ''), assets, normalized=True)
                with self._lock_for(record['kind']):
                    method = getattr(self, '_import_' + record['kind'])
                    status, identifier, detail = method(record, incoming, folder)
                return dict(status=status, kind=record['kind'], key=record['key'], id=identifier, detail=detail)
        except LibrarySyncError:
            raise
        except (OSError, ValueError, KeyError, TypeError, LookupError, zipfile.BadZipFile) as error:
            raise LibrarySyncError('同步包无法导入：' + str(error)) from error

    @staticmethod
    def _files_to_add(folder, local_folder, paths):
        files = {}
        for path in paths:
            source = safe_path(folder, path)
            target = safe_path(local_folder, path) if local_folder else None
            if target and target.is_file():
                if digest(source.read_bytes()) != digest(target.read_bytes()):
                    raise LibrarySyncError('附件内容冲突：' + path + '；已保留本机文件。')
            else:
                files[path] = source
        return files

    def _import_voice(self, record, incoming, folder):
        result = self.voices.import_synced(incoming['name'], safe_path(folder, incoming['file']).read_bytes())
        detail = {'created': '自定义声线已保存。', 'unchanged': '本机已有相同声线。',
                  'conflict': '同名声线内容不同，已保留本机声线。'}[result['status']]
        return result['status'], result['id'], detail

    def _import_article(self, record, incoming, folder):
        local = next((self.articles.load(i) for i in self.articles.ids()
                      if _article_key(self.articles.load(i)) == record['key']), None)
        paths = [spec['path'] for spec in record['files'] if spec['path'].startswith(('media/', 'audio/'))]
        try:
            files = self._files_to_add(folder, safe_path(self.articles.root, local['_directory']) if local else None, paths)
            if local and local['paragraphs'] != incoming['paragraphs']:
                raise LibrarySyncError('文章原文冲突，已保留本机内容。')
            merged = _missing(local or {}, incoming, ('paragraphs', 'translated_paragraphs', 'furigana_paragraphs',
                                                      'image_paths', 'video_urls', 'bookmarked', 'storage_key'))
            merged['paragraphs'] = deepcopy(incoming['paragraphs'])
            for field in ('translated_paragraphs', 'furigana_paragraphs'):
                merged[field] = _merge_text((local or {}).get(field, []), incoming.get(field, []), field)
            if local and merged['translated_paragraphs'] != local.get('translated_paragraphs', []):
                merged['full_translation'] = '\n\n'.join(merged['translated_paragraphs'])
            for field in ('image_paths', 'video_urls'):
                merged[field] = list(dict.fromkeys([*(local or {}).get(field, []), *incoming.get(field, [])]))
            assets = {entry['path']: deepcopy(entry) for entry in (local or {}).get('_assets', [])}
            for entry in incoming['_assets']: assets.setdefault(entry['path'], deepcopy(entry))
            merged['_assets'] = list(assets.values())
        except LibrarySyncError as error:
            return 'conflict', (local or {}).get('id'), str(error)
        marked = bool((local or {}).get('bookmarked') or incoming.get('bookmarked'))
        if local:
            changed = merged != local or bool(files) or marked != bool(local.get('bookmarked'))
            if not changed: return 'unchanged', local['id'], '本机已具备这些内容。'
            backup = self.articles.data / 'backups' / ('sync-article-' + str(local['id']) + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            shutil.copytree(safe_path(self.articles.root, local['_directory']), backup)
            saved = self.articles.save(merged, files=files)
        else:
            days = incoming.get('edition_dates', [])
            if not days: raise LibrarySyncError('文章缺少日刊日期。')
            day = days[0]; date.fromisoformat(day)
            merged['storage_key'] = record['key'][len('article:'):]
            # ArticleStore allocates directories from created_at; keep the declared edition authoritative.
            merged['created_at'] = incoming.get('created_at') or day + 'T00:00:00+08:00'
            saved = self.articles.create(merged, day, files=files)
        if marked and not saved.get('bookmarked'):
            saved = self.articles.set_bookmarked(saved['id'], True)
        elif marked and local:
            self.articles.refresh_bookmark(saved['id'])
        return ('updated' if local else 'created'), saved['id'], '文章与完整附件已保存。'

    def _import_book(self, record, incoming, folder):
        local = None
        for identifier in self.books.ids():
            meta = _json_file(self.books.folder(identifier), 'book.json')
            if 'book:' + str(meta.get('source_sha256')) == record['key']:
                local = self.books.load(identifier); break
        paths = [spec['path'] for spec in record['files'] if spec['path'].startswith(('resources/', 'audio/'))]
        try:
            files = self._files_to_add(folder, self.books.folder(local['id']) if local else None, paths)
            merged = _missing(local or {}, incoming, ('chapters', 'bookmarks', 'revision'))
            merged['chapters'] = deepcopy((local or incoming)['chapters'])
            if local:
                if len(local['chapters']) != len(incoming['chapters']):
                    raise LibrarySyncError('书籍章节结构冲突，已保留本机内容。')
                for index, (old, new) in enumerate(zip(local['chapters'], incoming['chapters'])):
                    if old['id'] != new['id'] or [b.get('text_ja') for b in old.get('blocks', [])] != [b.get('text_ja') for b in new.get('blocks', [])]:
                        raise LibrarySyncError('书籍正文结构冲突，已保留本机内容。')
                    chapter = _missing(old, new, ('blocks', 'file', 'sha256'))
                    chapter['blocks'] = []
                    for old_block, new_block in zip(old.get('blocks', []), new.get('blocks', [])):
                        if old_block.get('text_zh') and new_block.get('text_zh') and old_block['text_zh'] != new_block['text_zh']:
                            raise LibrarySyncError('书籍译文冲突，已保留本机内容。')
                        chapter['blocks'].append(_missing(old_block, new_block))
                    merged['chapters'][index] = chapter
            merged['bookmarks'] = deepcopy((local or {}).get('bookmarks') or incoming.get('bookmarks', []))[:1]
        except LibrarySyncError as error:
            return 'conflict', (local or {}).get('id'), str(error)
        assets = {path[len('resources/'):]: source.read_bytes() for path, source in files.items() if path.startswith('resources/')}
        audio = {path[len('audio/'):]: source for path, source in files.items() if path.startswith('audio/')}
        if local:
            if merged == local and not files: return 'unchanged', local['id'], '本机已具备这些内容。'
            self.books.backup(local['id'], 'sync')
            saved = self.books.save(merged, assets=assets, audio_files=audio)
            identifier = saved['id']
        else:
            merged.update(progress={}, last_read_at='')
            identifier, _ = self.books.create(merged, safe_path(folder, incoming['_source_file']).read_bytes(), assets, audio_files=audio)
        return ('updated' if local else 'created'), identifier, '书籍与完整附件已保存。'

    def _import_example(self, record, incoming, folder):
        local = next((item for item in self.examples.list() if item['title'] == incoming['title']), None)
        paths = [spec['path'] for spec in record['files'] if spec['path'].startswith('audio/')]
        try:
            files = self._files_to_add(folder, safe_path(self.examples.root, local['directory']) if local else None, paths)
            if local and local['text'] != incoming['text']:
                raise LibrarySyncError('同名示例正文冲突，已保留本机内容。')
            merged = _missing(local or {}, incoming, ('audio_versions', 'translated_paragraphs', 'schema_version', 'text_sha256', 'translation_sha256'))
            merged['translated_paragraphs'] = _merge_text((local or {}).get('translated_paragraphs', []), incoming.get('translated_paragraphs', []), '示例译文')
            versions = {version['path']: deepcopy(version) for version in (local or {}).get('audio_versions', [])}
            for version in incoming.get('audio_versions', []): versions.setdefault(version['path'], deepcopy(version))
            merged['audio_versions'] = list(versions.values())
        except LibrarySyncError as error:
            return 'conflict', (local or {}).get('id'), str(error)
        if local and merged == local and not files: return 'unchanged', local['id'], '本机已具备这些内容。'
        saved = self.examples.import_content(merged, files)
        return ('updated' if local else 'created'), saved['id'], '示例与完整音频已保存。'
