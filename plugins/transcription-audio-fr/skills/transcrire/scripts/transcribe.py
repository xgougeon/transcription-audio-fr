"""Transcrit des fichiers audio en français avec Whisper, en local.

Usage :
    python3 transcribe.py --name NOM [--title TITRE] [--out-dir DIR] [--model small]
                          [--keep-wav] [--force] FICHIER...
    python3 transcribe.py --convert-only [--out-dir DIR] FICHIER...

Les fichiers sont traités dans l'ordre donné. opus/ogg (WhatsApp), wav, flac, aiff et mp3
sont décodés par soundfile ; les autres formats (m4a, aac...) passent par afconvert (macOS)
ou ffmpeg. Produit NOM.md (texte continu + segments horodatés) et NOM.json dans --out-dir
(défaut : ~/Documents/Transcriptions).

--keep-wav enregistre aussi, pour chaque fichier, le WAV mono 16 kHz transmis à Whisper ;
--convert-only fait uniquement cette conversion, sans transcrire.

Le script se relance tout seul avec le Python de l'environnement créé par install.py.
Codes de sortie : 2 fichier introuvable, 3 sortie déjà présente, 4 format illisible,
10 environnement non installé.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402

if __name__ == "__main__":
    _env.relaunch_in_venv(Path(__file__).resolve())

import argparse  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from scipy.signal import resample_poly  # noqa: E402


class UnreadableAudio(Exception):
    pass


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def to_mono_16k(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sample_rate != _env.SAMPLE_RATE:
        audio = resample_poly(audio, _env.SAMPLE_RATE, sample_rate)
    return audio.astype(np.float32)


def convert_externally(path: Path, tmp_dir: Path) -> tuple[Path, str]:
    target = tmp_dir / f"{path.stem}.16k.wav"
    if shutil.which("afconvert"):
        tool = "afconvert"
        command = ["afconvert", "-f", "WAVE", "-d", f"LEI16@{_env.SAMPLE_RATE}", "-c", "1", str(path), str(target)]
    elif shutil.which("ffmpeg"):
        tool = "ffmpeg"
        command = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(path),
                   "-ac", "1", "-ar", str(_env.SAMPLE_RATE), "-c:a", "pcm_s16le", str(target)]
    else:
        raise UnreadableAudio(f"{path.name} : format non pris en charge par soundfile, et ni afconvert ni ffmpeg n'est installé")
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0 or not target.exists():
        detail = (completed.stderr or completed.stdout).strip()
        raise UnreadableAudio(f"{path.name} : {tool} n'a pas pu convertir le fichier ({detail})")
    return target, tool


def load_audio(path: Path, tmp_dir: Path) -> tuple[np.ndarray, str]:
    """Renvoie l'audio mono 16 kHz et le décodeur utilisé."""
    try:
        data, sample_rate = sf.read(str(path), dtype="float32")
        return to_mono_16k(data, sample_rate), "soundfile"
    except (RuntimeError, TypeError, ValueError):
        pass
    converted, tool = convert_externally(path, tmp_dir)
    data, sample_rate = sf.read(str(converted), dtype="float32")
    return to_mono_16k(data, sample_rate), tool


def save_wav(audio: np.ndarray, source: Path, out_dir: Path) -> Path | None:
    target = out_dir / f"{source.stem}.16k.wav"
    if target.exists():
        log(f"  {target.name} existe déjà, non écrasé")
        return None
    sf.write(str(target), audio, _env.SAMPLE_RATE, subtype="PCM_16")
    return target


def fmt_ts(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    minutes, rest = divmod(total_ms, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def render_markdown(title: str, model: str, results: list[dict]) -> str:
    lines = [
        f"# {title}",
        "",
        f"_Transcription automatique Whisper (modèle {model}), langue forcée en français._",
        "",
    ]
    for item in results:
        lines.extend([f"## {item['name']}", "", item["text"].strip() or "_[Aucune parole détectée]_", ""])
        segments = [seg for seg in item.get("segments") or [] if seg.get("text", "").strip()]
        if segments:
            lines.extend(["### Segments", ""])
            for seg in segments:
                lines.append(f"- `{fmt_ts(seg['start'])}` - `{fmt_ts(seg['end'])}` {seg['text'].strip()}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path, help="fichiers audio, dans l'ordre voulu")
    parser.add_argument("--name", help="nom de base des sorties, sans extension (obligatoire pour transcrire)")
    parser.add_argument("--title", help="titre du Markdown (défaut : --name)")
    parser.add_argument("--out-dir", type=Path, default=_env.default_out_dir())
    parser.add_argument("--model", default=_env.DEFAULT_MODEL, help=f"modèle Whisper (défaut : {_env.DEFAULT_MODEL})")
    parser.add_argument("--keep-wav", action="store_true", help="enregistrer aussi le WAV 16 kHz de chaque fichier")
    parser.add_argument("--convert-only", action="store_true", help="convertir en WAV 16 kHz sans transcrire")
    parser.add_argument("--force", action="store_true", help="écraser des sorties .md/.json existantes")
    args = parser.parse_args()
    if not args.convert_only and not args.name:
        parser.error("--name est obligatoire, sauf avec --convert-only")
    return args


def main() -> int:
    args = parse_args()
    files = [path.expanduser().resolve() for path in args.files]
    out_dir = args.out_dir.expanduser().resolve()

    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        log("Fichiers introuvables :\n  " + "\n  ".join(missing))
        return 2

    if not args.convert_only:
        outputs = [out_dir / f"{args.name}.md", out_dir / f"{args.name}.json"]
        existing = [str(path) for path in outputs if path.exists()]
        if existing and not args.force:
            log("Ces sorties existent déjà (choisir un autre --name ou passer --force) :\n  " + "\n  ".join(existing))
            return 3

    out_dir.mkdir(parents=True, exist_ok=True)

    # Tout décoder d'abord : un fichier illisible doit arrêter le lot avant le chargement du modèle.
    decoded = []
    with tempfile.TemporaryDirectory(prefix="transcription-fr-") as tmp:
        for path in files:
            try:
                audio, decoder = load_audio(path, Path(tmp))
            except UnreadableAudio as error:
                log(f"Format illisible : {error}")
                return 4
            decoded.append((path, audio, decoder))

    for path, audio, _ in decoded:
        if args.keep_wav or args.convert_only:
            written = save_wav(audio, path, out_dir)
            if written:
                print(written)
    if args.convert_only:
        return 0

    import whisper

    log(f"Chargement du modèle {args.model} (CPU)...")
    model = whisper.load_model(args.model, download_root=str(_env.models_dir()), device="cpu")

    results = []
    for index, (path, audio, decoder) in enumerate(decoded, start=1):
        log(f"[{index}/{len(decoded)}] {path.name}")
        started = time.monotonic()
        result = model.transcribe(
            audio,
            language="fr",
            task="transcribe",
            fp16=False,
            verbose=None,
            condition_on_previous_text=False,
        )
        duration = len(audio) / _env.SAMPLE_RATE
        log(f"  {duration:.1f} s d'audio traités en {time.monotonic() - started:.1f} s")
        results.append(
            {
                "name": path.name,
                "path": str(path),
                "duration_seconds": round(duration, 3),
                "decoder": decoder,
                "language": "fr",
                "model": args.model,
                "text": result.get("text", "").strip(),
                "segments": result.get("segments", []),
            }
        )

    md_path, json_path = outputs
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(args.title or args.name, args.model, results), encoding="utf-8")
    print(md_path)
    print(json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
