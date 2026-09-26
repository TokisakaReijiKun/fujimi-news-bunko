"""Generate the same Japanese sentence with every local VOICEVOX talk style.

Run with: conda run --no-capture-output -n Tokyo python -X utf8 voicevox_japanese_demo.py
"""

import csv
from pathlib import Path

from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile


PROJECT_DIR = Path(__file__).resolve().parent
MODEL_DIR = PROJECT_DIR / "model" / "VOICEVOX"
OUTPUT_DIR = PROJECT_DIR / "output" / "voicevox"
TEXT = "今日は澄んだ青空が広がり、街には心地よい風が吹いています。"
TALK_TYPES = {"talk", "streaming_talk"}


def main() -> None:
    runtime = MODEL_DIR / "onnxruntime" / "lib" / Onnxruntime.LIB_RECOMMENDED_VERSIONED_FILENAME
    dictionary = MODEL_DIR / "dict" / "open_jtalk_dic_utf_8-1.11"
    model_files = sorted((MODEL_DIR / "models" / "vvms").glob("*.vvm"))
    if not runtime.is_file() or not dictionary.is_dir() or not model_files:
        raise FileNotFoundError(
            f"VOICEVOX resources are incomplete in {MODEL_DIR}. "
            "Download onnxruntime, dict, and models with the official downloader."
        )

    synthesizer = Synthesizer(
        Onnxruntime.load_once(filename=str(runtime)),
        OpenJtalk(dictionary),
        acceleration_mode="CPU",
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    style_ids = set()

    for model_path in model_files:
        with VoiceModelFile.open(model_path) as model:
            styles = [
                (character.name, style)
                for character in model.metas
                for style in character.styles
                if style.type in TALK_TYPES
            ]
            if not styles:
                continue

            synthesizer.load_voice_model(model)
            try:
                for character_name, style in styles:
                    if style.id in style_ids:
                        raise ValueError(f"Duplicate VOICEVOX style ID: {style.id}")
                    style_ids.add(style.id)
                    output_file = OUTPUT_DIR / f"{style.id:04d}.wav"
                    output_file.write_bytes(synthesizer.tts(TEXT, style.id))
                    rows.append((style.id, character_name, style.name, model_path.name, output_file.name))
                    print(f"{style.id:04d}  {character_name} / {style.name} -> {output_file.name}", flush=True)
            finally:
                synthesizer.unload_voice_model(model.id)

    if not rows:
        raise RuntimeError("No VOICEVOX talk styles were found in the downloaded models")

    with (OUTPUT_DIR / "voices.csv").open("w", encoding="utf-8-sig", newline="") as index:
        writer = csv.writer(index)
        writer.writerow(("style_id", "character", "style", "model", "file"))
        writer.writerows(sorted(rows))

    print(f"Generated {len(rows)} Japanese WAV files in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
