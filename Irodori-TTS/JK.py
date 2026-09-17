"""Use Irodori-TTS-500M-v3 with 浅仓透.mp3 as the voice reference.

Run from the Irodori-TTS directory:
    conda run -n Tokyo python -X utf8 JK.py
"""

from __future__ import annotations

from pathlib import Path

import torch

from irodori_tts.inference_runtime import (
    InferenceRuntime,
    RuntimeKey,
    SamplingRequest,
    save_wav,
)


PROJECT_DIR = Path(__file__).resolve().parent
# CHECKPOINT = PROJECT_DIR / "model" / "Irodori-TTS-500M-v3" / "model.safetensors"
CHECKPOINT = PROJECT_DIR / "model" / "model.safetensors"
# REFERENCE_AUDIO = PROJECT_DIR / "浅仓透.mp3"
REFERENCE_AUDIO =  r"D:\夢を叶う担当政府—内阁\文部科学省（もんぶかがくしょう）\開発部\富士見新聞文庫\data\voices\折木奉太郎.wav"
REFERENCE_AUDIO = Path(REFERENCE_AUDIO)
OUTPUT_AUDIO = PROJECT_DIR / "output" / "折木_demo.wav"

# Replace this sentence with the Japanese text to synthesize.
# TEXT = "こんにちは。これは浅仓透さんの参考音声を使った、Irodori-TTSの音声合成テストです。"
TEXT = "東日本大震災で被災して東京都目黒区の区民住宅で避難生活をしていた70代女性が、退去の期限後も住み続けたとして区が家賃などの支払いを求めた訴訟の判決で、最高裁第二小法廷（三浦守裁判長）は14日、女性側の上告を棄却した。女性を敗訴とした一、二審判決が確定した。"
SEED = 42
NUM_STEPS = 40


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def main() -> None:
    checkpoint = require_file(CHECKPOINT, "Model checkpoint")
    reference_audio = require_file(REFERENCE_AUDIO, "Reference audio")

    model_device = "cuda" if torch.cuda.is_available() else "cpu"
    model_precision = "bf16" if model_device == "cuda" else "fp32"

    # Keeping DACVAE on CPU lowers VRAM use for the 500M model.
    codec_device = "cpu" if model_device == "cuda" else model_device
    OUTPUT_AUDIO.parent.mkdir(parents=True, exist_ok=True)

    print(f"Model: {checkpoint}")
    print(f"Reference audio: {reference_audio}")
    print(f"Device: {model_device}; model precision: {model_precision}")
    print(f"Text: {TEXT}")

    runtime = InferenceRuntime.from_key(
        RuntimeKey(
            checkpoint=str(checkpoint),
            model_device=model_device,
            model_precision=model_precision,
            codec_device=codec_device,
            codec_precision="fp32",
            codec_deterministic_encode=True,
            codec_deterministic_decode=True,
        )
    )

    result = runtime.synthesize(
        SamplingRequest(
            text=TEXT,
            ref_wav=str(reference_audio),
            ref_normalize_db=-16.0,
            ref_ensure_max=True,
            max_ref_seconds=30.0,
            num_steps=NUM_STEPS,
            seed=SEED,
            cfg_scale_text=3.0,
            cfg_scale_speaker=5.0,
        ),
        log_fn=print,
    )

    output_path = save_wav(OUTPUT_AUDIO, result.audio, result.sample_rate)
    duration = result.audio.shape[-1] / result.sample_rate
    print(f"Saved: {output_path.resolve()}")
    print(
        f"Audio: {result.sample_rate} Hz, {duration:.2f} seconds; "
        f"seed: {result.used_seed}"
    )
    for stage, seconds in result.stage_timings:
        print(f"{stage}: {seconds * 1000.0:.1f} ms")


if __name__ == "__main__":
    main()
