# transcription-audio-fr

Plugin Claude Code qui transcrit en local des fichiers audio en français avec [Whisper](https://github.com/openai/whisper) : vocaux WhatsApp (.opus/.ogg), .wav, .m4a, .mp3, .flac, .aiff.

Pour chaque lot, il produit :

- un fichier **Markdown** avec le texte continu et les segments horodatés ;
- un fichier **JSON** avec tous les détails (durée, segments, décodeur utilisé).

Claude relit ensuite la transcription, signale les noms et passages incertains et ne corrige rien sans confirmation.

## Où il fonctionne

| Environnement | Statut |
|---|---|
| Claude Code (onglet Code de l'application de bureau, terminal, IDE) sur macOS | Testé |
| Claude Code sous Windows ou Linux | Prévu par l'installateur, pas encore testé |
| Cowork | À tester : l'installation doit se faire dans la machine virtuelle de Cowork et demande un accès Internet |
| Claude chat (claude.ai) | Non pris en charge |

## Prérequis

- **Python 3.10 à 3.14** sur la machine. L'installateur trouve lui-même la bonne version ; s'il n'en trouve aucune, il indique comment l'installer (https://www.python.org/downloads/).
- **Environ 4 Go d'espace disque.**
- **Un accès Internet pour la première installation** : environ 1 à 2 Go de paquets Python depuis PyPI, et 460 Mo pour le modèle Whisper `small` depuis les serveurs d'OpenAI. Derrière un proxy d'entreprise, définir `HTTPS_PROXY`.

ffmpeg n'est pas nécessaire. Seul le format m4a/aac demande `afconvert`, présent sur tout Mac, ou ffmpeg sous Windows et Linux.

## Installer le plugin

Dans un terminal :

```bash
claude plugin marketplace add xgougeon/transcription-audio-fr
claude plugin install transcription-audio-fr@transcription-audio-fr
```

Ou, dans une session Claude Code interactive :

```text
/plugin marketplace add xgougeon/transcription-audio-fr
/plugin install transcription-audio-fr@transcription-audio-fr
```

Redémarrer ensuite la session.

## Utilisation

Il suffit de demander à Claude, par exemple « transcris ce vocal : ~/Downloads/WhatsApp Audio ….opus ». On peut aussi appeler la commande directement :

```text
/transcription-audio-fr:transcrire ~/Downloads/message-01.opus ~/Downloads/message-02.opus
```

À la première utilisation, Claude constate que l'environnement Whisper n'est pas installé : il explique ce qui va être téléchargé et **demande l'accord** avant de lancer l'installation (quelques minutes).

Par défaut, les transcriptions sont écrites dans `~/Documents/Transcriptions`. Claude peut aussi simplement convertir un fichier en WAV.

## Où sont stockées les données

L'environnement Python, le modèle et l'éventuel glossaire personnel sont rangés hors du plugin, pour survivre à ses mises à jour :

| Système | Dossier |
|---|---|
| macOS | `~/Library/Application Support/transcription-audio-fr` |
| Windows | `%LOCALAPPDATA%\transcription-audio-fr` |
| Linux | `~/.local/share/transcription-audio-fr` |

La variable `TRANSCRIPTION_FR_HOME` permet de choisir un autre dossier.

Le **glossaire personnel** (`glossaire.md`) n'existe que si l'utilisateur confirme des graphies (noms propres, termes métier). Il reste sur sa machine et n'est jamais inclus dans le plugin.

## Confidentialité

L'audio est transcrit sur la machine, sans service de transcription en ligne. Comme pour tout contenu d'une conversation, le texte que Claude relit transite par Claude.

## Utilisation sans Claude

```bash
python3 plugins/transcription-audio-fr/skills/transcrire/scripts/install.py --check
python3 plugins/transcription-audio-fr/skills/transcrire/scripts/install.py
python3 plugins/transcription-audio-fr/skills/transcrire/scripts/transcribe.py --name mon_lot fichier1.opus fichier2.opus
```

`transcribe.py --help` détaille les options : `--out-dir`, `--model`, `--keep-wav`, `--convert-only` et `--force`.

## Désinstaller

```bash
claude plugin uninstall transcription-audio-fr@transcription-audio-fr
```

Supprimer ensuite le dossier de données indiqué plus haut, qui occupe environ 2 à 3 Go.
