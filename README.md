# meeting-transcriber

[![CI](https://github.com/Vovamujik/meeting-transcriber/actions/workflows/ci.yml/badge.svg)](https://github.com/Vovamujik/meeting-transcriber/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**English** · [Русский](README.ru.md)

Transcribe meeting recordings **locally** into a plain-text transcript with timestamps and speaker labels, ready to paste into ChatGPT, Claude or any other LLM. Built on [WhisperX](https://github.com/m-bain/whisperX) (speech recognition + word-level alignment) and [pyannote](https://github.com/pyannote/pyannote-audio) (who spoke when).

Works as a command-line tool and as an [Agent Skill](https://agentskills.io) for Claude Code, Codex, Cursor, GitHub Copilot, Gemini CLI and OpenCode: ask your agent to "transcribe this call and list the action items".

```
File: planning.m4a
Duration: 00:42:13
Language: en
Speakers: 3
Automatic transcript: words and speaker labels may contain errors.

[00:00:03] Speaker 1: Hi all, let's start with the release of the mobile app.

[00:00:09] Speaker 2: We closed twelve tasks this week, three bugs are left in payments.

[00:00:16] Speaker 1: Will we make it by Friday?
```

- **Private.** Audio never leaves your computer. Only model weights are downloaded on the first run; pyannote's usage telemetry is switched off.
- **Speaker labels that follow the words.** Every word is time-aligned and assigned to a speaker, so turns are split correctly even when people interrupt each other.
- **LLM-friendly output.** Consecutive phrases of one speaker are merged into a turn; long monologues are split about every 45 s so timestamps stay useful.
- **Any input ffmpeg can read**: m4a, mp3, wav, ogg, flac, mp4, mov, webm…
- **Uses your GPU** when it can: NVIDIA (CUDA) for everything, Apple Silicon for speaker diarization.
- **Readable progress**: per-stage progress bars with ETA; one broken file doesn't stop a batch.

## Requirements

| | |
|---|---|
| OS | macOS on Apple Silicon, Linux, Windows. Intel Macs are not supported (no PyTorch builds). |
| Tools | [uv](https://docs.astral.sh/uv/getting-started/installation/) and [ffmpeg](https://ffmpeg.org/download.html). uv installs the right Python by itself. |
| Disk | ~2 GB for Python packages (~6 GB on Linux, where PyTorch ships with CUDA) + 2–4 GB for models |
| RAM | 8 GB minimum, 16 GB recommended |
| Speaker labels | a free [Hugging Face](https://huggingface.co) account and token (see below) |

Install the tools:

```bash
# macOS
brew install uv ffmpeg

# Debian / Ubuntu
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt install ffmpeg

# Windows
winget install astral-sh.uv
winget install Gyan.FFmpeg
```

## Install

As a global command (recommended):

```bash
uv tool install git+https://github.com/Vovamujik/meeting-transcriber
```

Or from a clone, if you want to change the code:

```bash
git clone https://github.com/Vovamujik/meeting-transcriber
cd meeting-transcriber
uv sync
uv run meeting-transcriber --help
```

## Hugging Face token (for speaker labels)

The speaker diarization model [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) is free but gated: you have to accept its terms once, which includes sharing your contact information with the pyannote team.

1. Accept the terms on the [model page](https://huggingface.co/pyannote/speaker-diarization-community-1).
2. Create a token of type **Read** at <https://huggingface.co/settings/tokens>.
3. Give it to the tool, one of:
   - `uvx --from huggingface_hub hf auth login` (stores it for all Hugging Face tools);
   - put `HF_TOKEN=hf_...` into `~/.config/meeting-transcriber/.env` (template: [.env.example](.env.example));
   - when running from a clone: a `.env` file in the repository root;
   - `export HF_TOKEN=hf_...` in your shell.

Don't want speaker labels? Skip this and use `--no-diarize`.

Then check everything at once:

```bash
meeting-transcriber --check
```

```
meeting-transcriber 0.1.0 · Python 3.12.6 · Darwin arm64
  ✓ ffmpeg: /opt/homebrew/bin/ffmpeg
  ✓ Whisper on cpu (int8), speaker diarization on mps
  ✓ Hugging Face token found, access to pyannote/speaker-diarization-community-1 confirmed
```

## Usage

```bash
meeting-transcriber ~/Downloads/meeting.m4a --lang en
```

The `.txt` is written next to the recording, and its path is printed to stdout. The first run downloads the models (2–4 GB) into `~/.cache/huggingface`; later runs work offline.

```bash
# several files into one folder
meeting-transcriber ~/Recordings/*.m4a --lang en -o transcripts

# you know how many people spoke: diarization gets more accurate
meeting-transcriber call.mp4 --lang en --speakers 4

# maximum accuracy (2–3x slower)
meeting-transcriber call.mp4 --lang en --model large-v3

# no Hugging Face token: transcript without speaker labels
meeting-transcriber call.mp4 --no-diarize
```

While it runs you see each stage with progress, elapsed time and an estimate of what's left:

```
Loading models
  ✓ speaker diarization (pyannote, mps) · 1.9s
  ✓ whisper large-v3-turbo (cpu, int8) · 2.3s
  ✓ alignment (en) · 0.4s

[1/2] planning.m4a
  42:13 · language en
  ✓ Transcribe    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%  9:12
  ⠴ Align words   ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━  62%  1:05  ~0:40 left
  · Speakers      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Options

| Option | Description |
|---|---|
| `-l, --lang CODE` | Spoken language (`en`, `ru`, `de`, …). Without it the language is detected from the first 30 s. |
| `-m, --model NAME` | `large-v3-turbo` (default, fast), `large-v3` (most accurate), `medium`, `small` |
| `-o, --out DIR` | Where to write the `.txt` files (default: next to each recording) |
| `-s, --speakers N` | Exact number of speakers, if known |
| `--min-speakers N`, `--max-speakers N` | A range, if the exact number isn't known |
| `--no-diarize` | No speaker labels (no token needed) |
| `--device auto\|cuda\|cpu` | Device for speech recognition and alignment. `auto` uses an NVIDIA GPU if there is one. |
| `--diarize-device auto\|cuda\|mps\|cpu` | Device for speaker diarization. `auto`: NVIDIA GPU, then Apple GPU, then CPU. |
| `--compute-type TYPE` | Whisper precision: `float16` on GPU, `int8` on CPU by default |
| `--batch-size N` | Default 8. Lower it if you run out of memory. |
| `--check` | Check ffmpeg, token and devices, then exit |
| `-v, --verbose` | Show library logs and warnings |

Exit codes: `0` all files done, `1` at least one file failed (the others are still processed), `130` interrupted.

### Output format

- A short header (file, duration, language, number of speakers), then one paragraph per speaker turn: `[HH:MM:SS] Speaker N: text`.
- Speakers are numbered in order of first appearance. The tool doesn't know names, so tell the LLM who is who ("Speaker 1 is Anna, she runs the meeting").
- Labels follow the recording language: Russian recordings get `Спикер 1`, `Файл:` and so on; every other language gets English labels.

## Use with AI agents

The repository ships an [Agent Skill](https://agentskills.io) in [`skills/transcribe-meeting`](skills/transcribe-meeting/SKILL.md). It tells the agent how to check the setup, run the transcription in the background, and then work with the transcript (summary, minutes, action items). You still need uv, ffmpeg and, for speaker labels, the Hugging Face token described above.

**Claude Code** (as a plugin):

```
/plugin marketplace add Vovamujik/meeting-transcriber
/plugin install meeting-transcriber@vovamujik
```

**Any agent** (Claude Code, Codex, Cursor, Copilot, Gemini CLI, OpenCode, …) via [`skills`](https://github.com/vercel-labs/skills):

```bash
npx skills add Vovamujik/meeting-transcriber -g
```

Or copy `skills/transcribe-meeting` into your agent's skills folder (for Claude Code: `~/.claude/skills/`).

Then just ask: *"Transcribe ~/Downloads/standup.m4a and list the action items with owners."*

The skill works only with agents that run on your computer. claude.ai and other cloud sandboxes can't download the models and have no GPU.

## Performance

Measured on an Apple M3 Pro (18 GB), `large-v3-turbo`, 3-minute two-speaker recording: about 1 minute in total (3x realtime): transcription 35 s on the CPU, alignment 9 s, speaker diarization 10 s on the Apple GPU (97 s on the CPU). An hour-long meeting takes roughly 20 minutes. NVIDIA GPUs are much faster.

## Troubleshooting

| Problem | Fix |
|---|---|
| `GatedRepoError`, `401`, `403` | The model terms aren't accepted or the token is missing. See [Hugging Face token](#hugging-face-token-for-speaker-labels) and run `--check`. |
| `ffmpeg not found` | Install ffmpeg (see [Requirements](#requirements)). |
| `CERTIFICATE_VERIFY_FAILED` | Handled automatically on macOS. Behind a corporate proxy, point `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to your company's CA bundle. |
| Download stuck or slow | Downloads resume where they stopped: interrupt with Ctrl+C and run again. |
| Out of memory | `--model medium` or `--batch-size 4` |
| CUDA / cuDNN errors on Linux | See WhisperX's [cuDNN notes](https://github.com/m-bain/whisperX/blob/main/CUDNN_TROUBLESHOOTING.md), or use `--device cpu --diarize-device cpu`. |
| Phantom phrases like "Thank you." | Whisper sometimes "hears" stock phrases in long silence. A known quirk of the model. |

## Limitations

- On macOS speech recognition runs on the CPU: faster-whisper (CTranslate2) doesn't support Apple GPUs. Speaker diarization does use the Apple GPU.
- Overlapping speech is attributed to one of the speakers.
- One person can be split into two speakers (for example after switching microphones), and similar voices can merge. `--speakers N` helps.
- Word-level alignment exists for [these languages](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py). For other languages, speakers are assigned per phrase instead of per word.

## Models and licenses

This project's code is MIT-licensed. The models are downloaded from their authors on first use and come with their own terms:

| Model | Used for | License |
|---|---|---|
| [faster-whisper-large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) (OpenAI Whisper) | speech recognition | MIT |
| [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) | speaker diarization | CC BY 4.0, gated |
| [wav2vec2-large-xlsr-53-russian](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-russian) | Russian word alignment | Apache 2.0 |
| [WAV2VEC2_ASR_BASE_960H](https://docs.pytorch.org/audio/stable/generated/torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.html) | English word alignment | MIT |
| [VOXPOPULI_ASR_BASE_10K_*](https://docs.pytorch.org/audio/stable/generated/torchaudio.pipelines.VOXPOPULI_ASR_BASE_10K_FR.html) | French, German, Spanish, Italian alignment | **CC BY-NC 4.0 (non-commercial)** |

Alignment models for other languages are listed in WhisperX; check each model card before commercial use. Whisper output can contain errors and hallucinations, so don't rely on it alone in high-risk settings.

## Development

```bash
uv sync                      # includes pytest and ruff
uv run pytest                # pure-logic tests, no models needed
uv run ruff check src tests
claude plugin validate .     # plugin and skill manifests
```

The code is small: `src/meeting_transcriber/cli.py` (pipeline, CLI, transcript formatting) and `ui.py` (terminal output). Issues and pull requests are welcome; please include your OS, GPU, the command you ran and the output of `--verbose`.

## Acknowledgements

[WhisperX](https://github.com/m-bain/whisperX) by Max Bain et al., [pyannote.audio](https://github.com/pyannote/pyannote-audio) by Hervé Bredin et al., [faster-whisper](https://github.com/SYSTRAN/faster-whisper) by SYSTRAN, and OpenAI's [Whisper](https://github.com/openai/whisper). If you use the diarization results in research, please cite pyannote as asked on its model card.

## License

[MIT](LICENSE)
