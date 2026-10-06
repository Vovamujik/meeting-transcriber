# meeting-transcriber

[![CI](https://github.com/Vovamujik/meeting-transcriber/actions/workflows/ci.yml/badge.svg)](https://github.com/Vovamujik/meeting-transcriber/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**English** · [Русский](README.ru.md)

Local meeting transcriber with speaker labels, plus an [Agent Skill](https://agentskills.io) for Claude Code, Codex, Cursor, GitHub Copilot, Gemini CLI and OpenCode.

Give your agent a recording or a video of a call and ask for a summary, minutes or action items. It transcribes everything **on your computer** with [WhisperX](https://github.com/m-bain/whisperX) and [pyannote](https://github.com/pyannote/pyannote-audio), then works from a transcript like this:

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

## Set up the skill for your agent

Four steps. Your agent must run on your computer (Claude Code, Codex, Cursor, …); claude.ai and other cloud sandboxes can't download the models.

### 1. Install uv, ffmpeg and git

```bash
# macOS
brew install uv ffmpeg

# Debian / Ubuntu
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt install ffmpeg git

# Windows
winget install astral-sh.uv
winget install Gyan.FFmpeg
winget install Git.Git
```

| You need | |
|---|---|
| OS | macOS 14+ on Apple Silicon, Linux or Windows. Intel Macs are not supported (no PyTorch builds). |
| Tools | [uv](https://docs.astral.sh/uv/getting-started/installation/) (installs the right Python by itself), [ffmpeg](https://ffmpeg.org/download.html) with ffprobe (part of every standard build), [git](https://git-scm.com/downloads) |
| Disk | ~2 GB for Python packages (~7.5 GB on Linux x86_64, where PyTorch ships with CUDA) + 2–4 GB for models |
| RAM | 8 GB minimum, 16 GB recommended |

### 2. Get a Hugging Face token (for speaker labels)

Who-said-what comes from [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1). The model is free but gated: you accept its terms once, which includes sharing your contact information with the pyannote team.

1. Create a free [Hugging Face](https://huggingface.co) account and accept the terms on the [model page](https://huggingface.co/pyannote/speaker-diarization-community-1).
2. Create a token of type **Read** at <https://huggingface.co/settings/tokens>.
3. Save it in your terminal:
   ```bash
   uvx --from huggingface_hub hf auth login
   ```
   Choose **Paste an access token** and paste it. (Tokens from the browser login expire, and this tool can't refresh them.)

Other ways to provide the token: `HF_TOKEN=hf_...` in `~/.config/meeting-transcriber/.env` (template: [.env.example](.env.example)), or `export HF_TOKEN=hf_...`. Never paste a token into the chat with your agent.

No token? Skip this step: the agent will transcribe without speaker labels.

### 3. Add the skill

**Claude Code** (as a plugin), inside a session:

```
/plugin marketplace add Vovamujik/meeting-transcriber
/plugin install meeting-transcriber@vovamujik
```

**Any agent** (Claude Code, Codex, Cursor, Copilot, Gemini CLI, OpenCode, …) via [`skills`](https://github.com/vercel-labs/skills):

```bash
npx skills add Vovamujik/meeting-transcriber -g
```

Or copy [`skills/transcribe-meeting`](skills/transcribe-meeting/SKILL.md) into your agent's skills folder (for Claude Code: `~/.claude/skills/`). Restart the agent afterwards.

### 4. Ask your agent

> Transcribe ~/Downloads/standup.m4a and list the action items with owners.

> Here's yesterday's call: ~/Movies/call.mov. There were 4 of us. Summarise the decisions.

> Расшифруй ~/Downloads/планёрка.m4a и сделай протокол.

What happens:

1. The agent checks the setup (ffmpeg, token, devices) and tells you if something is missing.
2. **The first run takes a while**: it installs the Python packages and downloads the models (10+ minutes). Later runs start in seconds and work offline.
3. It transcribes in the background, roughly a third of the recording's length on an Apple Silicon Mac (1 hour ≈ 20 minutes), much faster on an NVIDIA GPU.
4. It saves the transcript next to the recording (`call.txt`) and answers your request from it.

Tips: say the language and how many people spoke, and tell the agent who is who ("Speaker 1 is Anna"). Videos work as they are; don't convert them first.

Want to check the setup yourself before asking the agent?

```bash
uvx --from git+https://github.com/Vovamujik/meeting-transcriber meeting-transcriber --check
```

```
meeting-transcriber 0.2.0 · Python 3.12.6 · Darwin arm64
  ✓ ffmpeg: /opt/homebrew/bin/ffmpeg
  ✓ Whisper on cpu (int8), speaker diarization on mps
  ✓ Hugging Face token from `hf auth login` (account you), access to pyannote/speaker-diarization-community-1 confirmed
```

## What you get

- **Private.** Audio never leaves your computer. Only model weights are downloaded on the first run; pyannote's usage telemetry is switched off.
- **Audio or video.** m4a, mp3, wav, ogg, flac, mp4, mov, mkv, webm: anything ffmpeg can read. From a video the audio is extracted automatically, and recordings with several audio tracks (e.g. OBS with your microphone and the desktop audio on separate tracks) are mixed so nobody is lost.
- **Speaker labels that follow the words.** Every word is time-aligned and assigned to a speaker, so turns are split correctly even when people interrupt each other.
- **LLM-friendly output.** Consecutive phrases of one speaker are merged into a turn; long monologues are split about every 45 s so timestamps stay useful.
- **Uses your GPU** when it can: NVIDIA (CUDA) on Linux for everything, Apple Silicon for speaker diarization. On Windows it runs on the CPU (PyTorch from PyPI is CPU-only there).

About the transcript:

- A short header (file, duration, language, number of speakers), then one paragraph per speaker turn: `[HH:MM:SS] Speaker N: text`.
- Speakers are numbered in order of first appearance. The tool doesn't know names, so tell the LLM who is who.
- Labels follow the recording language: Russian recordings get `Спикер 1`, `Файл:` and so on; every other language gets English labels.

## Command line (without an agent)

Steps 1 and 2 above apply here too. Then install the command:

```bash
uv tool install git+https://github.com/Vovamujik/meeting-transcriber
```

Or from a clone, if you want to change the code (then prefix the commands below with `uv run`):

```bash
git clone https://github.com/Vovamujik/meeting-transcriber
cd meeting-transcriber
uv sync
uv run meeting-transcriber --help
```

Usage:

```bash
meeting-transcriber ~/Downloads/meeting.m4a --lang en
```

The `.txt` is written next to the recording, and its path is printed to stdout. An existing file is never overwritten: a second run writes `meeting (2).txt`. The first run downloads the models (2–4 GB) into `~/.cache/huggingface`; later runs work offline (if Hugging Face is unreachable, the cached models are used right away).

```bash
# several files into one folder
meeting-transcriber ~/Recordings/*.m4a --lang en -o transcripts

# you know how many people spoke: diarization gets more accurate
meeting-transcriber call.mp4 --lang en --speakers 4

# a video works as is: the audio is extracted automatically
meeting-transcriber ~/Movies/zoom-call.mov --lang en

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

[1/2] planning.mp4
  ✓ Extract audio ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%  0:14
  42:13 · language en · video, 2 audio tracks mixed
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
| `--device auto\|cuda\|cpu` | Device for speech recognition and alignment. `auto` uses an NVIDIA GPU if there is one (Linux; on Windows the default PyTorch is CPU-only). |
| `--diarize-device auto\|cuda\|mps\|cpu` | Device for speaker diarization. `auto`: NVIDIA GPU, then Apple GPU, then CPU. |
| `--compute-type TYPE` | Whisper precision: `float16` on GPU, `int8` on CPU by default |
| `--batch-size N` | Default 8. Lower it if you run out of memory. |
| `--check` | Check ffmpeg, token and devices, then exit |
| `-v, --verbose` | Show library logs and warnings |

Exit codes: `0` all files done, `1` at least one file failed (the others are still processed), `130` interrupted.

## Performance

Measured on an Apple M3 Pro (18 GB), `large-v3-turbo`, 3-minute two-speaker recording: about 1 minute in total (3x realtime): transcription 35 s on the CPU, alignment 9 s, speaker diarization 10 s on the Apple GPU (97 s on the CPU). An hour-long meeting takes roughly 20 minutes. NVIDIA GPUs are much faster.

## Troubleshooting

| Problem | Fix |
|---|---|
| `GatedRepoError`, `401`, `403` | Run `--check`: it says where the active token comes from and what's wrong with it (missing, invalid, terms not accepted for that account, fine-grained token without gated access). See [step 2](#2-get-a-hugging-face-token-for-speaker-labels). |
| Token "invalid or expired (HTTP 401)" right after `hf auth login` | An old `HF_TOKEN` exported in your shell profile (`~/.zshrc`, `~/.bashrc`; on Windows, a user environment variable) or set in a `.env` file wins over the `hf auth login` token. Remove it, open a new terminal and restart your agent; `--check` names where it comes from. |
| Long "Starting…" | The first run after installing or updating compiles the Python packages: up to a few minutes, once. |
| `ffmpeg not found` | Install ffmpeg (see [step 1](#1-install-uv-ffmpeg-and-git)). |
| `CERTIFICATE_VERIFY_FAILED` | Handled automatically on macOS. Behind a corporate proxy, point `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to your company's CA bundle. |
| Download stuck or slow | Downloads resume where they stopped: interrupt with Ctrl+C and run again. |
| Out of memory | `--model medium` or `--batch-size 4` |
| CUDA / cuDNN errors on Linux | See WhisperX's [cuDNN notes](https://github.com/m-bain/whisperX/blob/main/CUDNN_TROUBLESHOOTING.md), or use `--device cpu --diarize-device cpu`. |
| `no audio track in the video` | The recording has no sound at all (e.g. a screen recording made with audio off). |
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
uv run pytest                # no models needed
uv run ruff check src tests
claude plugin validate .     # marketplace and plugin manifests
uvx --from skills-ref agentskills validate skills/transcribe-meeting
```

Releasing: bump the version in `pyproject.toml` and `.claude-plugin/plugin.json`, tag `vX.Y.Z`, push the tag, then pin `RELEASE` in `skills/transcribe-meeting/scripts/run.sh` and the `uvx` line in `SKILL.md` to the new release.

The code is small: `src/meeting_transcriber/cli.py` (pipeline, CLI, transcript formatting), `media.py` (audio extraction) and `ui.py` (terminal output). Issues and pull requests are welcome; please include your OS, GPU, the command you ran and the output of `--verbose`.

## Acknowledgements

[WhisperX](https://github.com/m-bain/whisperX) by Max Bain et al., [pyannote.audio](https://github.com/pyannote/pyannote-audio) by Hervé Bredin et al., [faster-whisper](https://github.com/SYSTRAN/faster-whisper) by SYSTRAN, and OpenAI's [Whisper](https://github.com/openai/whisper). If you use the diarization results in research, please cite pyannote as asked on its model card.

## License

[MIT](LICENSE)
