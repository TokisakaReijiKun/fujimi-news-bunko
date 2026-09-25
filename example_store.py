"""File-backed reading examples, with recoverable updates and browser import."""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path

from article_store import ArticleStore, StorageError, digest, safe_path, write_json, replace_transaction_directory, directory_name

_ALLOWED_VOICE_MODES = {"inherit", "browser", "voice", "none"}
_MAX_TITLE = 500
_MAX_TEXT = 100000

DEFAULT_EXAMPLES = [{'id': 'snow-country', 'title': '雪国（川端康成）', 'text': '国境の長いトンネルを抜けると雪国であった。夜の底が白くなった。信号所に汽車が止まった。\n内側の座席から娘が立って来て、島村の前のガラス窓を落とした。雪の冷気が流れ込んだ。娘は窓いっぱいに乗り出して、遠くへ叫ぶように、\n「駅長さん、駅長さん」\n明かりをさげてゆっくり吹きを踏んできた男は、襟巻で鼻の上まで包み、耳に帽子の毛皮を垂れていた。\nもうそんな寒さかと島村は外を眺めると鉄道の官舎らしいバラックが山裾に寒々と散らばっているだけで、雪の色はそこまで行かぬうちに闇に飲まれていた。\n「駅長さん、私です、御機嫌よろしゅうございます」\n「ああ、葉子さんじゃないか。お帰りかい。また寒くなったよ」\n「弟が今度こちらに勤めさせていただいておりますのですってね。お世話さまですわ」\n「こんなところ、今に寂しくて参るだろうよ。若いのに可哀想だな」\n「ほんの子供ですから、駅長さんからよく教えてやっていただいて、よろしくお願いいたしますわ」\n「よろしい。元気で働いてるよ。これからいそがしくなる。去年は大雪だったよ。よく雪崩れてね、汽車が立往生するんで、村も炊出しがいそがしかったよ」\n「駅長さんずいぶん厚着に見えますわ。弟の手紙には、まだチョッキも着ていないようなことを書いてありましたけれど」\n私は着物を四枚重ねだ。若い者は寒いと酒ばがり飲んでいるよ。それでごろごろあすこにぶっ倒れてるのさ、風邪を引いてね」\n駅長は宿舎の方へ手の明かりを振り向けた。\n「弟もお酒をいただきますでしょうか」\n「いや」\n「駅長さんもうお帰りですの？」\n「私は怪我をして、医者に通ってるんだ」\n「まあ。いけませんわ」\n和服に外套の駅長は寒い立話をさっさと切り上げたいらしく、もう後姿を見せながら、\n「それじゃまあ大事にいらっしゃい」\n「駅長さん、弟は今出ておりませんの？」と葉子は雪の上を目探しして、\n「駅長さん、弟をよく見てやって、お願いです」\n悲しいほど美しい声であった。高い響きのまま夜の雪から木魂して来そうだった。\n汽車が動き出しても、彼女は窓から胸を入れなかった。そうして線路の下を歩いている駅長に追いつくと、\n「駅長さあん、今度の休みの日に家へお帰りって、弟に言ってやって下さあい」\n「はあい」と、駅長が声を張り上げた。\n葉子は窓をしめて、赤らんだ頬に両手をあてた。', 'voice_mode': 'inherit', 'voice_id': None, 'browser_voice_name': ''}, {'id': 'operation-example', 'title': '読書の時間（操作示例）', 'text': '朝の静かな時間に、本を開きました。窓の外では、小さな鳥が歌っています。\n\n知らない言葉に出会ったら、辞書で調べてみましょう。一つの言葉から、新しい世界が広がります。\n\nこれは閲読室の使い方を確認するための例文です。実際のニュースではありません。', 'voice_mode': 'inherit', 'voice_id': None, 'browser_voice_name': ''}]

class ExampleStore:
    def __init__(self, data, article_store=None):
        self.data = Path(data).resolve()
        self.root = self.data / "articles" / "examples"
        self.legacy_root = self.data / "examples"
        self.transactions = self.data / "diagnostics/example-transactions"
        self.locks = article_store or ArticleStore(self.data, initialize=False)
        with self.locks.locked():
            self.root.mkdir(parents=True, exist_ok=True)
            self.transactions.mkdir(parents=True, exist_ok=True)
            self._recover()
            self._migrate_legacy_root()
            for default in DEFAULT_EXAMPLES:
                if not any(item.get("title") == default["title"] for item in self._list_unlocked()):
                    self._commit(dict(default, builtin=True, directory=self._directory_for(default["title"], default["id"])))

    @staticmethod
    def paragraphs(text):
        return [p.strip() for p in re.split(r'\n\s*\n|\n', text) if p.strip()]

    @staticmethod
    def _clean_text(value, field, limit):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"请输入示例{field}。")
        if len(value) > limit:
            raise ValueError(f"示例{field}过长。")
        return value.strip()

    @staticmethod
    def validate_voice(voice_mode="inherit", voice_id=None, browser_voice_name=""):
        if voice_mode not in _ALLOWED_VOICE_MODES:
            raise ValueError("示例声线选项不正确。")
        if voice_mode == "voice":
            if type(voice_id) is not int or not 0 < voice_id <= 9007199254740991:
                raise ValueError("请选择有效的模型声线。")
        else:
            voice_id = None
        if not isinstance(browser_voice_name, str) or len(browser_voice_name) > 300:
            raise ValueError("浏览器声线名称不正确。")
        return dict(voice_mode=voice_mode, voice_id=voice_id,
                    browser_voice_name=browser_voice_name.strip() if voice_mode == "browser" else "")

    def _recover(self):
        for job in self.transactions.iterdir():
            journal = job / "journal.json"
            if not journal.is_file():
                continue
            record = json.loads(journal.read_text(encoding="utf-8"))
            target = safe_path(self.root, record["directory"])
            if record.get("mode") == "files":
                manifest = target / "example.json"
                if manifest.is_file() and digest(manifest.read_bytes()) == record["new_manifest_sha256"]:
                    shutil.rmtree(job)
                    continue
                old = job / "old"
                for relative in record["files"]:
                    previous = safe_path(old, relative)
                    destination = safe_path(target, relative)
                    if previous.is_file():
                        temporary = safe_path(job / "restore", relative)
                        temporary.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(previous, temporary)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        replace_transaction_directory(temporary, destination)
                    elif destination.exists():
                        destination.unlink()
                shutil.rmtree(job)
                continue
            if not target.exists():
                # A crash between the two directory renames must restore the old example.
                source = job / "old" if (job / "old").exists() else job / "new"
                replace_transaction_directory(source, target)
            shutil.rmtree(job)

    def _directory_for(self, title, stable_id):
        base = directory_name(title, stable_id, max_length=90)
        candidate = base
        index = 0
        while (self.root / candidate).exists():
            try:
                manifest = json.loads((self.root / candidate / "example.json").read_text(encoding="utf-8"))
                if manifest.get("id") == stable_id:
                    return candidate
            except (OSError, ValueError, json.JSONDecodeError):
                pass
            index += 1
            candidate = f"{base}--{str(stable_id)[:8]}" if index == 1 else f"{base}--{str(stable_id)[:8]}-{index}"
        return candidate

    def _list_unlocked(self):
        self._recover()
        items = []
        for folder in self.root.iterdir():
            if not folder.is_dir():
                continue
            try:
                items.append(self._load_folder(folder))
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
                continue
        return items

    def _migrate_legacy_root(self):
        if not self.legacy_root.exists():
            return
        backup = self.data / "backups" / f"examples-migration-{uuid.uuid4().hex}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.legacy_root, backup / "examples")
        for folder in self.legacy_root.iterdir():
            if not folder.is_dir():
                continue
            manifest = json.loads((folder / "example.json").read_text(encoding="utf-8"))
            text = (folder / "original.txt").read_text(encoding="utf-8")
            title = self._clean_text(manifest.get("title"), "标题", _MAX_TITLE)
            text = self._clean_text(text, "正文", _MAX_TEXT)
            voice = self.validate_voice(manifest.get("voice_mode", "inherit"), manifest.get("voice_id"), manifest.get("browser_voice_name", ""))
            stable_id = str(manifest.get("id") or f"custom-{uuid.uuid4().hex}")
            self._commit(dict(id=stable_id, title=title, text=text, builtin=bool(manifest.get("builtin")), directory=self._directory_for(title, stable_id), **voice))
        shutil.rmtree(self.legacy_root)

    def _commit(self, item):
        target = safe_path(self.root, item["directory"])
        job = self.transactions / uuid.uuid4().hex
        stage = job / "new"
        stage.mkdir(parents=True)
        try:
            if target.exists():
                backup = self.data / "backups" / f"example-{uuid.uuid4().hex}"
                shutil.copytree(target, backup / "example")
                shutil.copytree(target, stage, dirs_exist_ok=True)
            content = item["text"].encode("utf-8")
            with (stage / "original.txt").open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            translations = item.get("translated_paragraphs", [])
            if translations:
                translation_blob = "\n\n".join(translations).encode("utf-8")
                (stage / "translation.txt").write_bytes(translation_blob)
            else:
                (stage / "translation.txt").unlink(missing_ok=True)
            for audio in item.get("audio_versions", []):
                source = audio.pop("_source", None)
                if source:
                    destination = safe_path(stage, audio["path"])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
            manifest = {key: value for key, value in item.items() if key not in ("text", "directory", "translated_paragraphs")}
            manifest.update(schema_version=1, text_sha256=digest(content))
            if translations:
                manifest["translation_sha256"] = digest(translation_blob)
            write_json(stage / "example.json", manifest)
            if target.exists():
                shutil.copytree(target, job / "old")
                changed = []
                for staged in stage.rglob("*"):
                    if not staged.is_file() or staged.name == "example.json":
                        continue
                    relative = staged.relative_to(stage).as_posix()
                    destination = safe_path(target, relative)
                    if not destination.is_file() or digest(staged.read_bytes()) != digest(destination.read_bytes()):
                        changed.append(relative)
                if (target / "translation.txt").is_file() and not (stage / "translation.txt").exists():
                    changed.append("translation.txt")
                changed.append("example.json")
                write_json(job / "journal.json", {
                    "mode": "files", "directory": item["directory"], "files": changed,
                    "new_manifest_sha256": digest((stage / "example.json").read_bytes()),
                })
                try:
                    for relative in changed:
                        staged = safe_path(stage, relative)
                        destination = safe_path(target, relative)
                        if staged.is_file():
                            temporary = safe_path(job / "install", relative)
                            temporary.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(staged, temporary)
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            replace_transaction_directory(temporary, destination)
                        elif destination.exists():
                            destination.unlink()
                except Exception:
                    self._recover()
                    raise
            else:
                write_json(job / "journal.json", {"directory": item["directory"]})
                replace_transaction_directory(stage, target)
            shutil.rmtree(job)
        except Exception:
            if (job / "journal.json").exists():
                self._recover()
            elif job.exists():
                shutil.rmtree(job)
            raise
        return self._load_folder(target)

    def _load_folder(self, folder):
        safe_path(self.root, folder.name)
        manifest = json.loads(safe_path(folder, "example.json").read_text(encoding="utf-8"))
        content = safe_path(folder, "original.txt").read_bytes()
        if not isinstance(manifest, dict) or not manifest.get("id"):
            raise ValueError("示例标识与目录不一致。")
        if manifest.get("text_sha256") and digest(content) != manifest["text_sha256"]:
            raise ValueError("示例正文校验失败。")
        translated = []
        translation_path = folder / "translation.txt"
        if translation_path.exists():
            translation_content = translation_path.read_text(encoding="utf-8")
            translated = translation_content.split("\n\n") if translation_content.strip() else []
            if manifest.get("translation_sha256") and digest(translation_path.read_bytes()) != manifest["translation_sha256"]:
                raise ValueError("示例译文校验失败。")
        return dict(id=str(manifest['id']), directory=folder.name,
                    title=self._clean_text(manifest.get("title"), "标题", _MAX_TITLE),
                    text=self._clean_text(content.decode("utf-8"), "正文", _MAX_TEXT),
                    **self.validate_voice(manifest.get("voice_mode", "inherit"), manifest.get("voice_id"),
                                          manifest.get("browser_voice_name", "")),
                    translated_paragraphs=translated,
                    audio_versions=manifest.get("audio_versions", []),
                    builtin=bool(manifest.get("builtin")),
                    migration_ids=manifest.get("migration_ids", []))

    def list(self):
        with self.locks.locked():
            self._recover()
            items = self._list_unlocked()
            if len(items) != len([folder for folder in self.root.iterdir() if folder.is_dir()]):
                raise StorageError("示例文件无法读取，请检查 data/articles/examples；原文件已保留。")
            defaults = {item["id"]: index for index, item in enumerate(DEFAULT_EXAMPLES)}
            return sorted(items, key=lambda item: (0, defaults[item["id"]]) if item["id"] in defaults
                          else (1, item["title"].casefold()))

    def create(self, title, text, voice_mode="inherit", voice_id=None, browser_voice_name="", translated_paragraphs=None):
        with self.locks.locked():
            title = self._clean_text(title, "标题", _MAX_TITLE)
            text = self._clean_text(text, "正文", _MAX_TEXT)
            voice = self.validate_voice(voice_mode, voice_id, browser_voice_name)
            existing = next((item for item in self.list() if item["title"] == title), None)
            identifier = existing["id"] if existing else f"custom-{uuid.uuid4().hex}"
            directory = existing["directory"] if existing else self._directory_for(title, identifier)
            if existing and existing["title"] != title:
                directory = self._directory_for(title, identifier)
            item = dict(existing or {}, id=identifier, directory=directory, title=title, text=text,
                        translated_paragraphs=translated_paragraphs if translated_paragraphs is not None else (existing or {}).get('translated_paragraphs', []),
                        **voice, builtin=bool(existing and existing["builtin"]))
            return self._commit(item)

    def get(self, example_id):
        with self.locks.locked():
            for item in self._list_unlocked():
                if item["id"] == str(example_id):
                    return item
        raise LookupError("示例不存在。")

    def save_translation(self, example_id, translations):
        with self.locks.locked():
            item = self.get(example_id)
            paragraphs = [p.strip() for p in re.split(r'\n\s*\n|\n', item["text"]) if p.strip()]
            if not isinstance(translations, list) or len(translations) != len(paragraphs) or not all(isinstance(value, str) and value.strip() for value in translations):
                raise ValueError("示例译文段落数量不匹配。")
            item["translated_paragraphs"] = translations
            return self._commit(item)

    def save_audio(self, example_id, voice_id, source, metadata):
        with self.locks.locked():
            item = next((item for item in self._list_unlocked() if item["id"] == str(example_id)), None)
            if not item:
                raise LookupError("示例不存在。")
            versions = [dict(version) for version in item.get("audio_versions", []) if version.get("voice_id") != voice_id]
            voice_name = str(metadata.get("voice_name") or voice_id)
            safe_voice = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', voice_name).strip(' ._') or str(voice_id)
            safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', item['title']).strip(' ._') or '示例'
            path = f"audio/{safe_voice}_{safe_title}.wav"
            audio_hash = digest(Path(source).read_bytes())
            existing = safe_path(self.root / item['directory'], path)
            if existing.is_file() and digest(existing.read_bytes()) != audio_hash:
                stem = Path(path).stem
                path = f"audio/{stem}-{audio_hash[:8]}.wav"
                index = 2
                while (candidate := safe_path(self.root / item['directory'], path)).is_file() and digest(candidate.read_bytes()) != audio_hash:
                    path = f"audio/{stem}-{audio_hash[:8]}-{index}.wav"
                    index += 1
            version = dict(metadata, voice_id=voice_id, path=path, audio_sha256=audio_hash, _source=str(source))
            versions.append(version)
            item["audio_versions"] = versions
            return self._commit(item)

    def cached_audio(self, example_id, voice_id, text_sha256):
        with self.locks.locked():
            item = next((item for item in self._list_unlocked() if item["id"] == str(example_id)), None)
            if not item:
                return None
            for version in item.get("audio_versions", []):
                if version.get("voice_id") == voice_id and version.get("text_sha256") == text_sha256:
                    path = safe_path(self.root / item["directory"], version["path"])
                    if path.is_file() and (not version.get("audio_sha256") or digest(path.read_bytes()) == version["audio_sha256"]):
                        return path, version
            return None

    def migrate(self, values):
        if not isinstance(values, list) or len(values) > 500:
            raise ValueError("旧示例数据格式不正确。")
        validated = []
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("旧示例数据格式不正确。")
            validated.append(dict(title=self._clean_text(value.get("title"), "标题", _MAX_TITLE),
                                  text=self._clean_text(value.get("text"), "正文", _MAX_TEXT)))
        blob = json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
        with self.locks.locked():
            if not values:
                return self.list()
            backup = self.data / "backups" / f"examples-browser-{digest(blob)}.json"
            if not backup.exists():
                write_json(backup, values)
            for value in validated:
                token = digest(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))
                items = self.list()
                if any(token in item.get("migration_ids", []) for item in items):
                    continue
                same = next((item for item in items if item["title"] == value["title"]), None)
                if same and same["text"] == value["text"]:
                    item = same
                else:
                    title = value["title"]
                    if same:
                        title = title[:450] + f"（浏览器导入 {token[:8]}）"
                    identifier = "custom-" + uuid.uuid4().hex
                    item = dict(value, title=title, id=identifier, directory=self._directory_for(title, identifier),
                                builtin=False, **self.validate_voice())
                item["migration_ids"] = [*item.get("migration_ids", []), token]
                self._commit(item)
            return self.list()
