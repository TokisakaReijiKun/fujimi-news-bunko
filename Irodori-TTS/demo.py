"""Minimal local voice-cloning test for Irodori-TTS.

Run from this directory with:
    conda run -n Tokyo python demo.py
"""

from __future__ import annotations

import os
from pathlib import Path

import torch

from irodori_tts.inference_runtime import (
    InferenceRuntime,
    RuntimeKey,
    SamplingRequest,
    save_wav,
)


PROJECT_DIR = Path(__file__).resolve().parent
# CHECKPOINT = PROJECT_DIR / "model" / "model.safetensors"
CHECKPOINT = 'D:\夢を叶う担当政府—内阁\文部科学省（もんぶかがくしょう）\開発部\富士見新聞文庫\Irodori-TTS\model\Irodori-TTS-500M-v3\model.safetensors'
# CHECKPOINT = 'D:\夢を叶う担当政府—内阁\文部科学省（もんぶかがくしょう）\開発部\富士見新聞文庫\Irodori-TTS\model\Irodori-TTS-v4-Small\model.safetensors'
# CHECKPOINT = 'D:\夢を叶う担当政府—内阁\文部科学省（もんぶかがくしょう）\開発部\富士見新聞文庫\Irodori-TTS\model\Irodori-TTS-v4.1-Small\model.safetensors'
# REFERENCE_AUDIO = PROJECT_DIR / "朽木冬子.mp3"
CHECKPOINT = Path(CHECKPOINT)
REFERENCE_AUDIO = PROJECT_DIR / "浅仓透.mp3"
OUTPUT_AUDIO = PROJECT_DIR / "demo_output1.wav"

# A short, natural Japanese test sentence.
# TEXT = "おじんぽください。豚の私を妊娠させてください。"
TEXT = "東日本大震災で被災して東京都目黒区の区民住宅で避難生活をしていた70代女性が、退去の期限後も住み続けたとして区が家賃などの支払いを求めた訴訟の判決で、最高裁第二小法廷（三浦守裁判長）は14日、女性側の上告を棄却した。女性を敗訴とした一、二審判決が確定した。"
SEED = 20260907


def main() -> None:
    for path in (CHECKPOINT, REFERENCE_AUDIO):
        if not path.is_file():
            raise FileNotFoundError(f"Required file not found: {path}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    # BF16 substantially reduces VRAM use on supported NVIDIA GPUs.
    model_precision = "bf16" if device == "cuda" else "fp32"

    print(f"Conda environment: {os.environ.get('CONDA_DEFAULT_ENV', '(unknown)')}")
    print(f"Device: {device}; model precision: {model_precision}")
    print(f"Text: {TEXT}")
    print(f"Reference: {REFERENCE_AUDIO}")

    runtime = InferenceRuntime.from_key(
        RuntimeKey(
            checkpoint=str(CHECKPOINT),
            model_device=device,
            model_precision=model_precision,
            # Keep the codec on CPU so the 8 GB GPU has enough room for the TTS model.
            codec_device="cpu",
            codec_precision="fp32",
        )
    )

    result = runtime.synthesize(
        SamplingRequest(
            text=TEXT,
            ref_wav=str(REFERENCE_AUDIO),
            num_steps=40,
            seed=SEED,
        ),
        log_fn=print,
    )

    output_path = save_wav(OUTPUT_AUDIO, result.audio, result.sample_rate)
    duration = result.audio.shape[-1] / result.sample_rate
    print(f"Saved: {output_path}")
    print(
        f"Audio: {result.sample_rate} Hz, {duration:.2f} seconds; "
        f"seed: {result.used_seed}"
    )


if __name__ == "__main__":
    main()
