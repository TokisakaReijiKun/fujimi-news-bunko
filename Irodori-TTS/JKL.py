"""直接调用项目使用的 Irodori-TTS，生成一段日语 WAV。

运行：
    /Work21/2025/zhangjingyu/anaconda3/envs/kimi-nozomu-voice/bin/python scripts/demo_tts.py

修改下面的 TEXT、REF_AUDIO、OUTPUT_FILE 即可更换台词、音色和输出文件。
此示例使用本机真实路径，不需要启动 FastAPI、DeepSeek 或 ASR。
"""

import os
import sys
from pathlib import Path


IRODORI_REPO = Path("D:\夢を叶う担当政府—内阁\文部科学省（もんぶかがくしょう）\開発部\富士見新聞文庫\Irodori-TTS")
MODEL_FILE = Path(
    "D:\夢を叶う担当政府—内阁\文部科学省（もんぶかがくしょう）\開発部\富士見新聞文庫\Irodori-TTS\model\model.safetensors"
)
CODEC_FILE = Path(
    "D:\夢を叶う担当政府—内阁\文部科学省（もんぶかがくしょう）\開発部\富士見新聞文庫\Irodori-TTS\model\Semantic-DACVAE-Japanese-32dim\weights.pth"
)
# 本机 Irodori-TTS 的 tokenizer.py 已使用此本地 tokenizer 目录。
TOKENIZER_DIR = Path(
    "D:\夢を叶う担当政府—内阁\文部科学省（もんぶかがくしょう）\開発部\富士見新聞文庫\Irodori-TTS\model\llm-jp-3-150m"
)
REF_AUDIO = Path(
    "D:\夢を叶う担当政府—内阁\文部科学省（もんぶかがくしょう）\開発部\富士見新聞文庫\Irodori-TTS\朽木冬子.mp3"
)
# TEXT = "おかえりなさい。今日はどんな一日でしたか。よかったら、少しお話ししましょう。"
TEXT = "東日本大震災で被災して東京都目黒区の区民住宅で避難生活をしていた70代女性が、退去の期限後も住み続けたとして区が家賃などの支払いを求めた訴訟の判決で、最高裁第二小法廷（三浦守裁判長）は14日、女性側の上告を棄却した。女性を敗訴とした一、二審判決が確定した。"
OUTPUT_FILE = Path(
    r"D:\夢を叶う担当政府—内阁\文部科学省（もんぶかがくしょう）\開発部\富士見新聞文庫\Irodori-TTS\tts_demo.wav"
)
DEVICE = "cuda:0"


def main() -> None:
    for path in (IRODORI_REPO, MODEL_FILE, CODEC_FILE, TOKENIZER_DIR, REF_AUDIO):
        if not path.exists():
            raise FileNotFoundError(f"所需文件或目录不存在：{path}")

    # 在导入模型依赖前启用离线模式，并添加本机 Irodori-TTS 源码目录。
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(IRODORI_REPO))
    from irodori_tts.inference_runtime import (
        RuntimeKey,
        SamplingRequest,
        get_cached_runtime,
        save_wav,
    )

    # 1. 加载模型；同一进程内相同 RuntimeKey 会复用已加载的模型。
    runtime, _ = get_cached_runtime(
        RuntimeKey(
            checkpoint=str(MODEL_FILE),
            model_device=DEVICE,
            model_precision="bf16",
            codec_repo=str(CODEC_FILE),
            codec_device=DEVICE,
            codec_precision="bf16",
        )
    )

    # 2. 以参考音频作为音色条件，合成指定日语。
    # 当前原生接口没有 ref_text 参数；项目业务层才要求参考文本。
    # 这里直接使用 TEXT；项目 TTSService 还会先应用 pronunciation_map.json。
    result = runtime.synthesize(
        SamplingRequest(
            text=TEXT,
            ref_wav=str(REF_AUDIO),
            no_ref=False,
            num_steps=40,
            cfg_scale_text=3.0,
            cfg_scale_speaker=5.0,
            max_seconds=30.0,
            seed=42,
        ),
        log_fn=print,
    )

    # 3. 保存到指定文件（重复运行会覆盖该文件），采样率使用模型返回值。
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    save_wav(OUTPUT_FILE, result.audio.float(), result.sample_rate)
    print(f"生成完成：{OUTPUT_FILE}")
    print(f"采样率：{result.sample_rate} Hz")


if __name__ == "__main__":
    main()