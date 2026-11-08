"""Download validated article media into the application's local media store."""
import hashlib
import io
import uuid
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urljoin, urlparse
from pathlib import Path

from PIL import Image


def _hls_attributes(value):
    attrs = {}
    for match in re.finditer(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', value):
        raw = match.group(2)
        attrs[match.group(1)] = raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw
    return attrs


def _download_hls_playlist(playlist, base, folder, prefix, fetch, check, budget):
    if '#EXT-X-ENDLIST' not in playlist:
        raise ValueError('不保存直播或未结束的视频')
    if any(tag in playlist for tag in ('#EXT-X-BYTERANGE:', '#EXT-X-MAP:', '#EXT-X-STREAM-INF:')):
        raise ValueError('不支持此类分段视频')
    segments = [line.strip() for line in playlist.splitlines() if line.strip() and not line.startswith('#')]
    if not 0 < len(segments) <= 500:
        raise ValueError('视频分段数量超出限制')
    lines = []
    index = keys = 0
    for line in playlist.splitlines():
        if not line.strip():
            continue
        if line.startswith('#EXT-X-KEY:') and 'METHOD=NONE' not in line:
            attrs = _hls_attributes(line.partition(':')[2])
            if attrs.get('METHOD') not in ('NONE', 'AES-128') or attrs.get('KEYFORMAT', 'identity') != 'identity':
                raise ValueError('不支持 DRM 视频')
            target = urljoin(base, attrs.get('URI', ''))
            if urlparse(target).scheme != 'https' or not attrs.get('URI') or keys >= 20:
                raise ValueError('HLS 密钥信息无效')
            check(); key, _ = fetch(target)
            if len(key) != 16:
                raise ValueError('HLS AES-128 密钥无效')
            name = f'{prefix}-key-{keys:02d}.key'; keys += 1
            (folder / name).write_bytes(key)
            iv = attrs.get('IV')
            if iv and not re.fullmatch(r'0x[0-9a-fA-F]{32}', iv):
                raise ValueError('HLS IV 无效')
            lines.append(f'#EXT-X-KEY:METHOD=AES-128,URI="{name}"' + (f',IV={iv}' if iv else ''))
            continue
        if line.startswith('#'):
            # Never pass arbitrary source URI tags to a local-file demuxer.
            allowed = {'#EXTM3U', '#EXT-X-VERSION', '#EXT-X-TARGETDURATION', '#EXT-X-MEDIA-SEQUENCE',
                       '#EXT-X-PLAYLIST-TYPE', '#EXTINF', '#EXT-X-ENDLIST', '#EXT-X-DISCONTINUITY',
                       '#EXT-X-INDEPENDENT-SEGMENTS'}
            if line == '#EXT-X-KEY:METHOD=NONE' or line.split(':', 1)[0] in allowed:
                lines.append(line)
            continue
        check(); target = urljoin(base, line.strip())
        if urlparse(target).scheme != 'https':
            raise ValueError('视频分段必须使用 HTTPS')
        data, _ = fetch(target)
        budget[0] += len(data)
        if budget[0] > 32 * 1024 * 1024:
            raise ValueError('视频超过 32 MB 上限')
        path = folder / f'{prefix}-{index:04d}.ts'; index += 1
        path.write_bytes(data); lines.append(path.name)
    if not 0 < index <= 500:
        raise ValueError('视频分段数量超出限制')
    listing = folder / f'{prefix}.m3u8'
    listing.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return listing


def download_hls(url, root, fetch, check=lambda: None):
    """Fetch bounded VOD and standard AES-128 keys; ffmpeg sees local files only."""
    check()
    blob, base = fetch(url)
    playlist = blob.decode('utf-8-sig')
    if not playlist.startswith('#EXTM3U'):
        raise ValueError('不是 HLS 播放列表')
    audio_url = None
    if '#EXT-X-STREAM-INF:' in playlist:
        master_lines = playlist.splitlines()
        media = [_hls_attributes(line.partition(':')[2]) for line in master_lines if line.startswith('#EXT-X-MEDIA:')]
        variants = []
        for index, line in enumerate(master_lines[:-1]):
            if not line.startswith('#EXT-X-STREAM-INF:'):
                continue
            relative = master_lines[index + 1].strip()
            if relative and not relative.startswith('#'):
                variants.append((_hls_attributes(line.partition(':')[2]), relative))
        if not variants:
            raise ValueError('视频没有有效清晰度')
        def bandwidth(item):
            try:
                return int(item[0].get('BANDWIDTH', '0') or 0)
            except (TypeError, ValueError):
                return 0
        attrs, relative = min(variants, key=bandwidth)
        group = attrs.get('AUDIO')
        audio = next((item for item in media if item.get('TYPE') == 'AUDIO'
                      and item.get('GROUP-ID') == group and item.get('URI')), None)
        if audio:
            audio_url = urljoin(base, audio['URI'])
        variant_url = urljoin(base, relative)
        if urlparse(variant_url).scheme != 'https' or (audio_url and urlparse(audio_url).scheme != 'https'):
            raise ValueError('HLS 播放列表必须使用 HTTPS')
        blob, base = fetch(variant_url)
        playlist = blob.decode('utf-8-sig')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('本地未安装 ffmpeg，无法合并分段视频')
    with tempfile.TemporaryDirectory(dir=root) as folder:
        folder = Path(folder)
        budget = [0]
        video_listing = _download_hls_playlist(playlist, base, folder, 'video', fetch, check, budget)
        audio_listing = None
        if audio_url:
            audio_blob, audio_base = fetch(audio_url)
            audio_playlist = audio_blob.decode('utf-8-sig')
            audio_listing = _download_hls_playlist(audio_playlist, audio_base, folder, 'audio', fetch, check, budget)
        output = folder / 'video.mp4'
        # NHK can announce AAC before its first audio packets arrive. Probe
        # enough of the bounded local VOD to learn the sample rate/channels;
        # otherwise ffmpeg silently omits audio or cannot mux an explicit map.
        input_options = ['-protocol_whitelist', 'file,crypto', '-allowed_extensions', 'ts,key',
                         '-probesize', str(32 * 1024 * 1024), '-analyzeduration', '100000000']
        command = [ffmpeg, '-nostdin', '-v', 'error', *input_options, '-i', str(video_listing)]
        if audio_listing:
            command += [*input_options, '-i', str(audio_listing), '-map', '0:v:0', '-map', '1:a:0']
        else:
            # Keep an AAC/MP2 track when the selected variant carries audio in
            # the same MPEG-TS stream.  Explicit mapping avoids ffmpeg's
            # default stream selection changing with codec metadata.
            command += ['-map', '0:v:0', '-map', '0:a:0?']
        command += ['-c', 'copy', '-movflags', '+faststart', str(output)]
        check()
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (subprocess.SubprocessError, OSError):
            raise ValueError('视频分段合并失败') from None
        check()
        if output.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('合并视频超过 32 MB 上限')
        return output.read_bytes()


def cache_media(extracted, root, fetch, *, check=lambda: None, cancelled_error=()):
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
        except cancelled_error:
            raise
        except Exception as e:
            result['media_warnings'].append(f'正文图片保存失败：{type(e).__name__}。可在原站查看。')
    for url in extracted.get('videos', [])[:5]:
        try:
            blob = download_hls(url,root,fetch,check) if urlparse(url).path.endswith('.m3u8') else fetch(url)[0]
            extension = '.mp4' if len(blob) >= 12 and blob[4:8] == b'ftyp' else '.webm' if blob.startswith(b'\x1aE\xdf\xa3') else None
            if not extension: raise ValueError('返回内容不是支持的视频文件')
            result['video_urls'].append('/api/media/' + save(blob, extension))
        except cancelled_error:
            raise
        except Exception as e:
            status=getattr(getattr(e,'response',None),'status_code',None)
            reason=f'HTTP {status}' if status else type(e).__name__
            result['media_warnings'].append(f'正文视频未下载：{reason}。原站未返回可保存的视频文件。')
    if len(extracted.get('images', [])) > 30 or len(extracted.get('videos', [])) > 5:
        result['media_warnings'].append('媒体数量超过单篇保存上限，剩余内容请在原站查看。')
    return result
