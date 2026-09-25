"""Tokyo-only inference process. Protocol uses files; model stdout stays in logs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

from article_store import digest
from tts_protocol import read_json, write_json


def runtime_options(model):
    """Use the local GPU/BF16 inference setup proven by Irodori-TTS/JKL.py."""
    return dict(checkpoint=str(model), model_device='cuda:0', model_precision='bf16',
                codec_repo=str(Path(model).parent/'Semantic-DACVAE-Japanese-32dim/weights.pth'),
                codec_device='cuda:0', codec_precision='bf16')


def sampling_options(text, reference, seed):
    return dict(text=text, ref_wav=reference, no_ref=False, num_steps=40,
                cfg_scale_text=3.0, cfg_scale_speaker=5.0, max_seconds=30.0, seed=seed)


def segment_plan(paragraphs, tokenizer, limit):
    """Return stable, ordered chunks while retaining their source paragraph."""
    planned = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        for chunk_index, text in enumerate(split_text(paragraph, tokenizer, limit)):
            planned.append({'paragraph_index': paragraph_index, 'chunk_index': chunk_index,
                            'text': text, 'text_sha256': digest(text.encode('utf-8'))})
    return planned


def segment_path(segment_directory, voice_name, index):
    return Path(segment_directory) / f'{voice_name}_segment_{index + 1:02d}.wav'


def segment_manifest_path(segment_directory, voice_name):
    """Legacy manifest path, retained only so successful jobs can clean it."""
    return Path(segment_directory) / f'{voice_name}_segment_manifest.json'


def valid_cached_segment(path, expected_sha256, expected_sample_rate=48000):
    if not path.is_file():
        return False
    try:
        import soundfile as sf
        info = sf.info(str(path))
        return info.samplerate == expected_sample_rate and info.channels == 1 and info.frames > 0 and (not expected_sha256 or digest(path.read_bytes()) == expected_sha256)
    except (OSError, RuntimeError):
        return False


def resumable_segment_prefix(plan, segment_directory, voice_name):
    """Return the contiguous valid numbered WAVs at the start of a job."""
    reusable = []
    for index in range(len(plan)):
        path = segment_path(segment_directory, voice_name, index)
        if not valid_cached_segment(path, ''):
            break
        reusable.append(path)
    return reusable


def split_text(text, count_tokens, limit, max_chars=256):
    """Keep whole paragraphs within the token budget; split only oversized ones.

    max_chars is retained as a call-compatible name, but denotes a token budget.
    """
    limit = min(limit, max_chars)
    if text and count_tokens(text) <= limit:
        return [text]
    pieces = []
    for sentence in re.findall(r'.+?(?:[。！？!?\n]+|$)', text, flags=re.S):
        while sentence:
            size = len(sentence)
            while size and count_tokens(sentence[:size]) > limit:
                size -= 1
            if not size:
                raise ValueError('单个字符超过模型文本限制。')
            if size < len(sentence):
                boundary = max(sentence.rfind(c, 0, size) for c in '、，,；; ')
                if boundary >= size // 2:
                    size = boundary + 1
            pieces.append(sentence[:size])
            sentence = sentence[size:]
    if ''.join(pieces) != text:
        raise ValueError('朗读分段未能完整保留原文。')
    return pieces


def merge_segments(plan, paths, paragraph_count, output_path, cancelled=lambda: False):
    """Stream PCM frames in order, retaining the original paragraph timeline."""
    import wave
    frames = [0] * paragraph_count
    temporary = output_path.with_suffix('.tmp')
    try:
        with wave.open(str(temporary), 'wb') as output:
            output.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            for item, path in zip(plan, paths):
                if cancelled():
                    raise InterruptedError()
                with wave.open(str(path), 'rb') as source:
                    if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 48000):
                        raise ValueError('分段音频格式不匹配。')
                    frames[item['paragraph_index']] += source.getnframes()
                    while blob := source.readframes(48000):
                        if cancelled():
                            raise InterruptedError()
                        output.writeframesraw(blob)
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return [{'duration': n / 48000, 'speech_start_offset': 0} for n in frames]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    parent_pid = os.getppid()
    # The child must not keep GPU memory after a forced server shutdown.
    import threading
    def watch_parent():
        if os.name == 'nt':
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x00100000, False, parent_pid)
            if not handle:
                os._exit(1)
            try:
                if kernel.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:
                    os._exit(0)
            finally:
                kernel.CloseHandle(handle)
        else:
            while os.getppid() == parent_pid:
                time.sleep(1)
            os._exit(0)
    threading.Thread(target=watch_parent, daemon=True).start()
    workspace, model = Path(args.workspace), Path(args.model)
    # All required assets have been downloaded; never implicitly download weights.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    sys.path.insert(0, str(model.parent.parent))
    import numpy as np
    import soundfile as sf
    import torch
    from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey, SamplingRequest

    try:
        if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
            raise RuntimeError('Irodori 需要支持 BF16 的 CUDA GPU。')
        options = runtime_options(model)
        if not Path(options['codec_repo']).is_file():
            raise FileNotFoundError('本地 DACVAE 权重不存在。')
        def loading(stage):
            write_json(workspace/'loading.json', {'stage': stage})
            print(f'[loading {time.strftime("%Y-%m-%d %H:%M:%S")}] pid={os.getpid()} stage={stage}', flush=True)
        runtime = InferenceRuntime.from_key(RuntimeKey(**options), progress=loading)
        # Return unused initialization allocations to CUDA before real inference.
        torch.cuda.empty_cache()
        write_json(workspace/'ready.json', {'ready': True})
    except Exception as error:
        write_json(workspace/'ready.json', {'error': f'模型加载失败：{type(error).__name__}；请检查 TTS 日志和本地模型依赖。'})
        raise

    while not (workspace/'stop').exists():
        request_path = workspace/'request.json'
        if not request_path.exists():
            time.sleep(.1)
            continue
        request = read_json(request_path)
        request_path.unlink()
        job = Path(request['directory'])
        try:
            paragraphs = request['paragraphs']
            plan = segment_plan(paragraphs, lambda s: runtime.tokenizer.encode(s).numel(), runtime.default_text_max_len)
            total = len(plan)
            completed = 0
            segment_directory = Path(request['segment_directory'])
            segment_directory.mkdir(parents=True, exist_ok=True)
            voice_name = request['voice_name']
            segment_paths = (resumable_segment_prefix(plan, segment_directory, voice_name)
                             if request.get('reuse_segments', True) else [])
            completed = len(segment_paths)
            if completed:
                write_json(job/'progress.json', {'stage': 'tts', 'completed': completed, 'total': total,
                    'message': f'音声を生成中 {completed}/{total} 段'})
            # Existing numbered WAVs form the durable prefix. Generate from the
            # first missing or invalid number and overwrite any later stale files.
            for index in range(completed, total):
                item = plan[index]
                if (job/'cancel').exists():
                    raise InterruptedError()
                path = segment_path(segment_directory, voice_name, index)
                write_json(job/'progress.json', {'stage': 'tts', 'completed': completed, 'total': total,
                    'message': f'音声を生成中 {completed}/{total} 段'})
                print(f'[tts] segment={index + 1}/{total} codec=cuda:0/bf16', flush=True)
                result = runtime.synthesize(SamplingRequest(**sampling_options(
                    item['text'], request['reference'], request['seed'] + index)), log_fn=print)
                if (job/'cancel').exists():
                    raise InterruptedError()
                audio = result.audio.detach().float().cpu().numpy().reshape(-1)
                if result.sample_rate != 48000 or not len(audio) or not np.isfinite(audio).all() or float(np.abs(audio).max()) < 1e-6:
                    raise ValueError('模型返回了无效或静音音频。')
                temporary = path.with_suffix('.tmp')
                sf.write(temporary, audio, result.sample_rate, format='WAV', subtype='PCM_16')
                temporary.replace(path)
                segment_paths.append(path)
                completed += 1
                write_json(job/'progress.json', {'stage': 'tts', 'completed': completed, 'total': total,
                    'message': f'音声を生成中 {completed}/{total} 段'})
            # Only after every durable segment is ready do we create the merged task output.
            write_json(job/'progress.json', {'stage': 'merging', 'completed': completed, 'total': total,
                'message': '音声を結合しています…'})
            segments = merge_segments(plan, segment_paths, len(paragraphs), job/'audio.wav',
                                      lambda: (job/'cancel').exists())
            write_json(job/'result.json', {'segments': segments, 'sample_rate': 48000,
                'completed': completed, 'total': total})
        except InterruptedError:
            write_json(job/'result.json', {'cancelled': True})
        except Exception as error:
            import traceback
            traceback.print_exc()
            write_json(job/'result.json', {'error': f'音声生成失败：{type(error).__name__}；请检查 TTS 日志后重试。'})
    runtime.unload()


if __name__ == '__main__':
    main()
