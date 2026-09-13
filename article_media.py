"""Download validated article media into the application's local media store."""
import hashlib
import io
import uuid
from pathlib import Path

from PIL import Image


def cache_media(extracted, root, fetch):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    result = {'image_paths': [], 'image_captions': [], 'image_positions': [], 'image_links': [],
              'image_urls': [], 'video_urls': [], 'media_warnings': list(extracted.get('media_warnings', []))}

    def save(blob, extension):
        name = hashlib.sha256(blob).hexdigest() + extension
        path = root / name
        if not path.exists():
            temp = root / (uuid.uuid4().hex + '.tmp')
            try:
                temp.write_bytes(blob)
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)
        return name

    for image in extracted.get('images', [])[:30]:
        try:
            blob, _ = fetch(image['url'])
            with Image.open(io.BytesIO(blob)) as im:
                fmt = im.format
                if im.width * im.height > 40000000: raise ValueError('图片尺寸过大')
                im.verify()
            extension = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'GIF': '.gif', 'AVIF': '.avif'}.get(fmt)
            if not extension: raise ValueError('不支持的图片格式')
            path = save(blob, extension)
            result['image_paths'].append(path)
            result['image_captions'].append(image['caption'])
            result['image_positions'].append(image['position'])
            result['image_links'].append(image['link'])
            result['image_urls'].append(image['url'])
        except Exception as e:
            result['media_warnings'].append(f'正文图片保存失败：{type(e).__name__}。可在原站查看。')
    for url in extracted.get('videos', [])[:5]:
        try:
            blob, _ = fetch(url)
            extension = '.mp4' if len(blob) >= 12 and blob[4:8] == b'ftyp' else '.webm' if blob.startswith(b'\x1aE\xdf\xa3') else None
            if not extension: raise ValueError('返回内容不是支持的视频文件')
            result['video_urls'].append('/api/media/' + save(blob, extension))
        except Exception as e:
            result['media_warnings'].append(f'正文视频保存失败：{type(e).__name__}。可在原站观看。')
    if len(extracted.get('images', [])) > 30 or len(extracted.get('videos', [])) > 5:
        result['media_warnings'].append('媒体数量超过单篇保存上限，剩余内容请在原站查看。')
    return result
