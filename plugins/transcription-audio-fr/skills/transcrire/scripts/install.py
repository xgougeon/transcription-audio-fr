"""Installe ou vérifie l'environnement Whisper du plugin transcription-audio-fr.

Usage :
    python3 install.py                  installe ce qui manque, puis lance un auto-test
    python3 install.py --check          indique seulement ce qui est prêt ou manquant
    python3 install.py --model medium   installe aussi un autre modèle Whisper
    python3 install.py --python CHEMIN  impose l'interpréteur utilisé pour créer l'environnement
    python3 install.py --model-file small.pt  fournit le modèle à la main (serveur du modèle bloqué)

Tout est installé hors du plugin, dans un dossier propre à l'utilisateur
(macOS : ~/Library/Application Support/transcription-audio-fr ;
Windows : %LOCALAPPDATA%\\transcription-audio-fr ; Linux : ~/.local/share/transcription-audio-fr ;
ou $TRANSCRIPTION_FR_HOME). Première installation : environ 1 à 2 Go de paquets
Python (PyPI) et 460 Mo pour le modèle small (serveurs d'OpenAI).

Bibliothèque standard uniquement : ce script tourne avec n'importe quel python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402


# Ordre de préférence : les versions les plus récentes dont torch et numba publient des wheels.
PREFERRED_PYTHONS = [(3, 13), (3, 12), (3, 11), (3, 14), (3, 10)]
PACKAGES = ["openai-whisper>=20250625", "numpy", "scipy", "soundfile>=0.12"]
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
MIN_FREE_BYTES = 4 * 1024**3

PYPI_INDEX_URL = "https://pypi.org/simple/pip/"
PYPI_JSON_URL = "https://pypi.org/pypi/pip/json"
# Tous les modèles Whisper sont servis par le même hôte : tester le petit suffit.
MODEL_HOST_URL = (
    "https://openaipublic.azureedge.net/main/whisper/models/"
    "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt"
)
DESCRIBE_INTERPRETER = (
    "import json, sys, importlib.util as u; print(json.dumps({"
    "'version': '%d.%d' % sys.version_info[:2], "
    "'venv': bool(u.find_spec('venv')), 'ensurepip': bool(u.find_spec('ensurepip')), "
    "'pip': bool(u.find_spec('pip'))}))"
)

# Exécuté par le Python de l'environnement dédié : renvoie un état en JSON.
PROBE = r"""
import json, os, sys, tempfile
state = {"python": "%d.%d.%d" % sys.version_info[:3]}
try:
    import numpy, scipy, soundfile, torch, whisper
    from importlib.metadata import version
    state["packages"] = {name: version(name) for name in ("openai-whisper", "torch", "numpy", "scipy", "soundfile")}
except Exception as error:
    state["packages_error"] = repr(error)
    print(json.dumps(state)); sys.exit(0)

model = sys.argv[1]
url = whisper._MODELS.get(model)
if url is None:
    state["model_error"] = "modèle inconnu : %s (choix : %s)" % (model, ", ".join(whisper.available_models()))
else:
    path = os.path.join(sys.argv[2], os.path.basename(url))
    state["model_file"] = path
    state["model_present"] = os.path.isfile(path)

formats = soundfile.available_formats()
state["mp3"] = "MP3" in formats
try:
    tone = numpy.sin(numpy.linspace(0, 440 * 2 * numpy.pi, 48000)).astype("float32") * 0.1
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "probe.opus")
        soundfile.write(target, tone, 48000, format="OGG", subtype="OPUS")
        soundfile.read(target)
    state["opus"] = True
except Exception as error:
    state["opus"] = False
    state["opus_error"] = repr(error)
print(json.dumps(state))
"""

SELF_TEST = r"""
import sys, time, numpy, whisper
started = time.monotonic()
model = whisper.load_model(sys.argv[1], download_root=sys.argv[2], device="cpu")
model.transcribe(numpy.zeros(16000 * 2, dtype="float32"), language="fr", task="transcribe", fp16=False, verbose=None)
print("%.1f" % (time.monotonic() - started))
"""


def log(message: str = "") -> None:
    print(message, flush=True)


def describe_interpreter(command: list[str]) -> dict | None:
    """Version de l'interpréteur et présence de venv, ensurepip et pip ; None s'il ne démarre pas."""
    try:
        completed = subprocess.run(
            command + ["-c", DESCRIBE_INTERPRETER], capture_output=True, text=True, timeout=30
        )
        if completed.returncode != 0:
            return None
        return json.loads(completed.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def probe_interpreter(command: list[str]) -> tuple[int, int] | None:
    """Renvoie (majeur, mineur) si l'interpréteur existe et sait créer un venv avec pip."""
    info = describe_interpreter(command)
    if not info or not (info["venv"] and info["ensurepip"]):
        return None
    major, minor = info["version"].split(".")
    return int(major), int(minor)


def candidate_interpreters() -> list[list[str]]:
    candidates = [[sys.executable]]
    if os.name == "nt":
        candidates += [["py", f"-{major}.{minor}"] for major, minor in PREFERRED_PYTHONS]
        candidates += [["python"], ["python3"]]
    else:
        for major, minor in PREFERRED_PYTHONS:
            name = f"python{major}.{minor}"
            for location in (
                shutil.which(name),
                f"/opt/homebrew/bin/{name}",
                f"/usr/local/bin/{name}",
                f"/Library/Frameworks/Python.framework/Versions/{major}.{minor}/bin/{name}",
            ):
                if location and Path(location).is_file():
                    candidates.append([location])
        if shutil.which("python3"):
            candidates.append([shutil.which("python3")])
    unique, seen = [], set()
    for command in candidates:
        key = tuple(command)
        if key not in seen:
            seen.add(key)
            unique.append(command)
    return unique


def find_interpreter() -> tuple[list[str], tuple[int, int]] | None:
    found = []
    for command in candidate_interpreters():
        version = probe_interpreter(command)
        if version in PREFERRED_PYTHONS:
            found.append((PREFERRED_PYTHONS.index(version), command, version))
    if not found:
        return None
    found.sort(key=lambda item: item[0])
    return found[0][1], found[0][2]


def python_help() -> str:
    if sys.platform == "darwin":
        return "Installer Python 3.13 depuis https://www.python.org/downloads/ (ou : brew install python@3.13), puis relancer."
    if os.name == "nt":
        return "Installer Python 3.13 depuis https://www.python.org/downloads/ (cocher « Add python.exe to PATH »), puis relancer."
    return "Installer python3.13 (ou 3.12) avec le paquet venv de la distribution (ex. apt install python3.12-venv), puis relancer."


def m4a_decoder() -> str | None:
    if shutil.which("afconvert"):
        return "afconvert"
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    return None


def check_url(url: str) -> tuple[bool, str]:
    """Accessible seulement si le serveur répond 2xx/3xx : un proxy qui filtre répond souvent 403."""
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "transcription-audio-fr"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return True, f"accessible (HTTP {response.status})"
    except urllib.error.HTTPError as error:
        if error.code in (403, 407):
            return False, f"BLOQUÉ (HTTP {error.code})"
        return False, f"réponse inattendue (HTTP {error.code})"
    except (urllib.error.URLError, OSError) as error:
        return False, f"INACCESSIBLE ({getattr(error, 'reason', error)})"


def pythonhosted_sample_url() -> str | None:
    """Adresse d'un vrai fichier sur files.pythonhosted.org : la racine du site répond 404."""
    try:
        with urllib.request.urlopen(PYPI_JSON_URL, timeout=15) as response:
            return json.load(response)["urls"][0]["url"]
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
        return None


def network_checks() -> dict[str, tuple[bool, str]]:
    """État de chaque hôte nécessaire, par rôle."""
    results = {"pypi": ("pypi.org",) + check_url(PYPI_INDEX_URL)}
    sample = pythonhosted_sample_url()
    results["files"] = ("files.pythonhosted.org",) + (
        check_url(sample) if sample else (False, "non testé, pypi.org ne répond pas")
    )
    if sys.platform.startswith("linux"):
        results["torch"] = ("download.pytorch.org",) + check_url(TORCH_CPU_INDEX + "/torch/")
    results["model"] = ("openaipublic.azureedge.net",) + check_url(MODEL_HOST_URL)
    return results


NETWORK_ROLES = {
    "pypi": "index des paquets Python",
    "files": "fichiers des paquets Python",
    "torch": "torch pour Linux, version CPU",
    "model": "modèle Whisper",
}


def environment_report(network: dict) -> None:
    log(f"Système : {platform.system()} {platform.release()} ({platform.machine()})")
    log(f"Python qui lance ce script : {sys.executable} ({platform.python_version()})")
    log(f"Espace libre : {shutil.disk_usage(_env.data_dir() if _env.data_dir().exists() else Path.home()).free / 1024**3:.1f} Go")
    log("Pythons trouvés :")
    for command in candidate_interpreters():
        info = describe_interpreter(command)
        if info:
            usable = info["venv"] and info["ensurepip"]
            flags = "venv OK" if usable else ("venv sans ensurepip" if info["venv"] else "pas de venv")
            flags += ", pip " + ("présent" if info["pip"] else "absent")
            log(f"  - {' '.join(command)} : {info['version']} ({flags})")
    log("Accès réseau :")
    for key, (host, ok, detail) in network.items():
        log(f"  - {host} ({NETWORK_ROLES[key]}) : {detail}")


def run_probe(model: str) -> dict:
    python = _env.venv_python()
    if not python.exists():
        return {}
    completed = subprocess.run(
        [str(python), "-c", PROBE, model, str(_env.models_dir())],
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"packages_error": (completed.stderr or completed.stdout).strip()[-500:]}


def report(state: dict, model: str) -> bool:
    log(f"Dossier de données : {_env.data_dir()}")
    python_ok = bool(state.get("python"))
    packages_ok = python_ok and "packages" in state
    model_ok = bool(state.get("model_present"))
    log(f"Environnement Python : {'OK, Python ' + state['python'] if python_ok else 'absent'}")
    if packages_ok:
        versions = state["packages"]
        log(f"Paquets : OK (openai-whisper {versions['openai-whisper']}, torch {versions['torch']}, soundfile {versions['soundfile']})")
    else:
        log(f"Paquets : manquants{' (' + state['packages_error'] + ')' if state.get('packages_error') else ''}")
    if state.get("model_error"):
        log(f"Modèle {model} : {state['model_error']}")
    else:
        log(f"Modèle {model} : {'OK' if model_ok else 'absent'}")
    if packages_ok:
        decoders = [
            "wav/flac/aiff OK",
            "opus/ogg (WhatsApp) " + ("OK" if state.get("opus") else "INDISPONIBLE"),
            "mp3 " + ("OK" if state.get("mp3") else "indisponible"),
        ]
        converter = m4a_decoder()
        decoders.append(f"m4a/aac OK via {converter}" if converter else "m4a/aac indisponible (installer ffmpeg)")
        log("Formats audio : " + " ; ".join(decoders))
    log(f"Glossaire personnel : {'présent, ' + str(_env.glossary_path()) if _env.glossary_path().exists() else 'aucun'}")
    ready = packages_ok and model_ok and bool(state.get("opus"))
    log(f"STATUT : {'prêt' if ready else 'incomplet, lancer install.py sans --check'}")
    return ready


def run_step(description: str, command: list[str]) -> None:
    log(f"-> {description}")
    completed = subprocess.run(command)
    if completed.returncode != 0:
        log(
            f"ÉCHEC : {description} (code {completed.returncode}).\n"
            "Si le réseau passe par un proxy d'entreprise, définir HTTPS_PROXY puis relancer."
        )
        sys.exit(1)


def install(args: argparse.Namespace) -> int:
    data_dir = _env.data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(data_dir).free
    if free < MIN_FREE_BYTES:
        log(f"Attention : seulement {free / 1024**3:.1f} Go libres, il en faut environ 4.")

    if args.model_file:
        source = Path(args.model_file).expanduser().resolve()
        if not source.is_file():
            log(f"Fichier de modèle introuvable : {source}")
            return 1
        _env.models_dir().mkdir(parents=True, exist_ok=True)
        target = _env.models_dir() / source.name
        if not target.exists():
            log(f"-> copie du modèle {source.name} dans {_env.models_dir()}")
            shutil.copyfile(source, target)

    state = run_probe(args.model)
    need_packages = "packages" not in state
    need_model = not state.get("model_present") and not args.model_file

    # Vérifier le réseau avant tout téléchargement : mieux vaut s'arrêter tout de suite
    # que d'échouer après 1 Go de paquets.
    network = network_checks() if (need_packages or need_model) else {}
    for key, (host, ok, detail) in network.items():
        log(f"Accès à {host} ({NETWORK_ROLES[key]}) : {detail}")
    blocked = []
    if need_packages and not (network["pypi"][1] and network["files"][1]):
        blocked += [network["pypi"][0], network["files"][0]]
    if need_model and not network["model"][1]:
        blocked.append(network["model"][0])
    if blocked:
        log(
            "\nINSTALLATION IMPOSSIBLE : ces domaines ne sont pas joignables depuis cette machine :\n  "
            + "\n  ".join(sorted(set(blocked)))
            + "\nDemander à l'administrateur (réseau d'entreprise, ou réglages réseau de Cowork) de les autoriser."
        )
        if need_model and not network["model"][1]:
            log(
                "Pour le modèle seulement, on peut aussi fournir le fichier à la main :\n"
                f"  python3 install.py --model-file /chemin/vers/{args.model}.pt"
            )
        return 1
    use_torch_index = sys.platform.startswith("linux") and need_packages and network["torch"][1]
    if sys.platform.startswith("linux") and need_packages and not use_torch_index:
        log("download.pytorch.org injoignable : torch sera pris sur PyPI (téléchargement plus lourd).")

    if need_packages:
        if not _env.venv_python().exists():
            if args.python:
                interpreter = [args.python]
                version = probe_interpreter(interpreter)
                if version is None:
                    log(f"{args.python} ne peut pas créer d'environnement virtuel avec pip.")
                    return 1
            else:
                chosen = find_interpreter()
                if chosen is None:
                    log("Aucun Python 3.10 à 3.14 capable de créer un environnement virtuel n'a été trouvé.")
                    log(python_help())
                    return 1
                interpreter, version = chosen
            log(f"Python retenu : {' '.join(interpreter)} ({version[0]}.{version[1]})")
            if _env.venv_dir().exists():
                shutil.rmtree(_env.venv_dir())
            run_step("création de l'environnement virtuel", interpreter + ["-m", "venv", str(_env.venv_dir())])

        pip = [str(_env.venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off"]
        run_step("mise à jour de pip", pip + ["--upgrade", "pip"])
        if use_torch_index:
            # Sans cet index, pip installe sous Linux la version CUDA de torch (plusieurs Go inutiles).
            run_step("installation de torch (CPU)", pip + ["torch", "--index-url", TORCH_CPU_INDEX])
        run_step("installation de Whisper et des dépendances", pip + PACKAGES)
        state = run_probe(args.model)

    if state.get("model_error"):
        log(state["model_error"])
        return 1

    if not state.get("model_present"):
        log(f"-> téléchargement du modèle {args.model} dans {_env.models_dir()}")
    _env.models_dir().mkdir(parents=True, exist_ok=True)
    log("-> auto-test : chargement du modèle et transcription de 2 s de silence")
    completed = subprocess.run(
        [str(_env.venv_python()), "-c", SELF_TEST, args.model, str(_env.models_dir())],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        log("ÉCHEC de l'auto-test :\n" + (completed.stderr or completed.stdout).strip()[-2000:])
        return 1
    log(f"   auto-test réussi en {completed.stdout.strip().splitlines()[-1]} s")

    log()
    return 0 if report(run_probe(args.model), args.model) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="vérifier sans rien installer")
    parser.add_argument("--model", default=_env.DEFAULT_MODEL, help=f"modèle Whisper (défaut : {_env.DEFAULT_MODEL})")
    parser.add_argument("--python", help="interpréteur Python à utiliser pour créer l'environnement")
    parser.add_argument("--model-file", help="fichier .pt du modèle déjà téléchargé, quand son serveur est bloqué")
    args = parser.parse_args()

    if args.check:
        environment_report(network_checks())
        return 0 if report(run_probe(args.model), args.model) else 1
    return install(args)


if __name__ == "__main__":
    sys.exit(main())
