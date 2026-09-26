"""Generate one Japanese sentence with every local Kokoro Japanese voice.

Run with: conda run --no-capture-output -n Tokyo python -X utf8 kokoro_japanese_demo.py
"""

from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from kokoro import KModel, KPipeline


PROJECT_DIR = Path(__file__).resolve().parent
MODEL_DIR = PROJECT_DIR / "model" / "Kokoro"
OUTPUT_DIR = PROJECT_DIR / "output" / "kokoro"
VOICES = ("jf_alpha")
TEXT = "今日は澄んだ青空が広がり、街には心地よい風が吹いています。"
SAMPLE_RATE = 24000


def main() -> None:
    config = MODEL_DIR / "config.json"
    weights = MODEL_DIR / "kokoro-v1_0.pth"
    voice_files = {voice: MODEL_DIR / "voices" / f"{voice}.pt" for voice in VOICES}
    missing = [path for path in (config, weights, *voice_files.values()) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing local Kokoro files:\n" + "\n".join(map(str, missing)))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = KModel(
        repo_id="hexgrad/Kokoro-82M", config=str(config), model=str(weights)
    ).to(device).eval()
    pipeline = KPipeline(lang_code="j", repo_id="hexgrad/Kokoro-82M", model=model)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Model: {MODEL_DIR}")
    print(f"Device: {device}")
    print(f"Text: {TEXT}")
    with torch.inference_mode():
        for voice, voice_file in voice_files.items():
            chunks = []
            for result in pipeline(TEXT, voice=str(voice_file)):
                if result.audio is not None:
                    chunks.append(result.audio.detach().cpu().numpy())
            if not chunks:
                raise RuntimeError(f"Kokoro produced no audio for {voice}")

            output_file = OUTPUT_DIR / f"{voice}.wav"
            sf.write(output_file, np.concatenate(chunks), SAMPLE_RATE)
            print(f"Saved: {output_file}")


if __name__ == "__main__":
    main()
