"""meeting-transcriber: transcribe meeting recordings locally into an LLM-ready .txt.

Pipeline: Whisper (speech → text) → wav2vec2 (word-level timestamps) → pyannote (who speaks when) →
words grouped into speaker turns → "[00:01:23] Speaker 1: text".
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from rich.markup import escape

from . import __version__
from .ui import Stages, console, fmt_dur, loading, short_path

# pyannote 4 sends anonymous usage telemetry by default; recordings are private, so turn it off before import.
os.environ["PYANNOTE_METRICS_ENABLED"] = "false"
# The HF xet downloader stalled on model downloads in testing; plain HTTP is more reliable.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
# Ops missing on Apple GPUs (MPS) fall back to CPU instead of crashing.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
if sys.platform == "darwin":
    # python.org builds of Python on macOS have no CA store until "Install Certificates.command" is run, so the
    # torchaudio alignment models (en/fr/de/es/it, downloaded via urllib) fail with CERTIFICATE_VERIFY_FAILED.
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())

DIARIZE_MODEL = "pyannote/speaker-diarization-community-1"
SENTENCE_END = (".", "?", "!", "…")
MAX_TURN_SECONDS = 45  # split long monologues at a sentence end so timestamps stay frequent
LANGS_WITHOUT_SPACES = {"ja", "zh"}
CONFIG_ENV = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "meeting-transcriber" / ".env"
REPO_ENV = Path(__file__).resolve().parents[2] / ".env"  # .env in the root of a git checkout (src/ layout)
FFMPEG_HINT = "macOS: brew install ffmpeg · Linux: sudo apt install ffmpeg · Windows: winget install Gyan.FFmpeg"

# Transcript labels follow the recording's language; anything other than Russian gets English.
LABELS = {
    "en": {
        "file": "File", "duration": "Duration", "language": "Language", "speakers": "Speakers", "speaker": "Speaker",
        "note": "Automatic transcript: words and speaker labels may contain errors.",
    },
    "ru": {
        "file": "Файл", "duration": "Длительность", "language": "Язык", "speakers": "Спикеров", "speaker": "Спикер",
        "note": "Расшифровка автоматическая: возможны ошибки в словах и в определении спикеров.",
    },
}


@dataclass
class Turn:
    start: float
    end: float
    speaker: str | None
    parts: list[str] = field(default_factory=list)


def fmt_ts(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def iter_units(segments: list[dict]):
    """Words (when alignment ran) or whole segments, as (start, end, text, speaker).

    Words that couldn't be aligned (often numbers) have no timing or speaker; they inherit from the previous word.
    """
    for seg in segments:
        words = seg.get("words") or []
        if not words:
            yield seg["start"], seg["end"], seg["text"].strip(), seg.get("speaker")
            continue
        last_t, last_spk = seg["start"], seg.get("speaker")
        for w in words:
            start = w.get("start", last_t)
            end = w.get("end", start)
            spk = w.get("speaker", last_spk)
            last_t, last_spk = end, spk
            yield start, end, w["word"].strip(), spk


def build_turns(segments: list[dict]) -> list[Turn]:
    """Groups words into turns: a new turn on speaker change, or after ~45 s of monologue at a sentence end."""
    turns: list[Turn] = []
    cur: Turn | None = None
    for start, end, text, speaker in iter_units(segments):
        if not text:
            continue
        if (
            cur is None
            or speaker != cur.speaker
            or (start - cur.start > MAX_TURN_SECONDS and cur.parts[-1].endswith(SENTENCE_END))
        ):
            cur = Turn(start, end, speaker)
            turns.append(cur)
        cur.parts.append(text)
        cur.end = max(cur.end, end)
    return turns


def render(turns: list[Turn], *, source: str, duration: float, language: str) -> str:
    lb = LABELS.get(language, LABELS["en"])
    names: dict[str, str] = {}
    for t in turns:
        if t.speaker and t.speaker not in names:
            names[t.speaker] = f"{lb['speaker']} {len(names) + 1}"

    joiner = "" if language in LANGS_WITHOUT_SPACES else " "
    header = [
        f"{lb['file']}: {source}",
        f"{lb['duration']}: {fmt_ts(duration)}",
        f"{lb['language']}: {language}",
    ]
    if names:
        header.append(f"{lb['speakers']}: {len(names)}")
    header.append(lb["note"])

    lines = []
    for t in turns:
        label = f" {names[t.speaker]}:" if t.speaker in names else ""
        lines.append(f"[{fmt_ts(t.start)}]{label} {joiner.join(t.parts)}")
    return "\n".join(header) + "\n\n" + "\n\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="meeting-transcriber",
        description="Transcribe meeting recordings locally into a timestamped, speaker-labelled .txt "
        "(WhisperX + pyannote). The path of each finished .txt is printed to stdout.",
    )
    p.add_argument("files", nargs="*", type=Path, help="audio/video files (anything ffmpeg can read)")
    p.add_argument("-l", "--lang", help="spoken language code, e.g. en, ru, de (default: detect from the first 30 s)")
    p.add_argument("-m", "--model", default="large-v3-turbo",
                   help="Whisper model: large-v3-turbo (default, fast), large-v3 (most accurate, 2-3x slower), "
                        "medium, small")
    p.add_argument("-o", "--out", type=Path, help="directory for the .txt files (default: next to each recording)")
    p.add_argument("-s", "--speakers", type=int, help="exact number of speakers, if known (improves accuracy)")
    p.add_argument("--min-speakers", type=int)
    p.add_argument("--max-speakers", type=int)
    p.add_argument("--no-diarize", action="store_true", help="skip speaker labels (no Hugging Face token needed)")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"],
                   help="device for Whisper and alignment: auto = cuda if an NVIDIA GPU is available, else cpu")
    p.add_argument("--diarize-device", default="auto", choices=["auto", "cuda", "mps", "cpu"],
                   help="device for speaker diarization: auto = cuda, then Apple GPU (mps), then cpu")
    p.add_argument("--compute-type", choices=["int8", "int8_float16", "float16", "float32"],
                   help="Whisper precision (default: float16 on cuda, int8 on cpu)")
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--threads", type=int, default=os.cpu_count() or 4, help="CPU threads for Whisper")
    p.add_argument("--check", action="store_true", help="check the setup (ffmpeg, token, devices) and exit")
    p.add_argument("-v", "--verbose", action="store_true", help="show library logs and warnings")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    if not args.files and not args.check:
        p.error("no input files (or use --check to verify the setup)")
    for opt in ("speakers", "min_speakers", "max_speakers"):
        if (v := getattr(args, opt)) is not None and v < 1:
            p.error(f"--{opt.replace('_', '-')} must be >= 1")
    if not args.speakers and args.min_speakers and args.max_speakers and args.min_speakers > args.max_speakers:
        p.error("--min-speakers can't be greater than --max-speakers")
    if args.out:
        args.out = args.out.expanduser()
    return args


def load_env() -> None:
    """HF_TOKEN lookup: env var → .env in the git checkout → ~/.config/meeting-transcriber/.env → `hf auth login`."""
    from dotenv import load_dotenv

    for env in (REPO_ENV, CONFIG_ENV):
        if env.is_file():
            load_dotenv(env)  # never overrides variables that are already set


def pick_devices(args: argparse.Namespace) -> tuple[str, str, str]:
    """(Whisper/alignment device, Whisper compute type, diarization device)."""
    import torch

    cuda = torch.cuda.is_available()
    asr = args.device if args.device != "auto" else ("cuda" if cuda else "cpu")
    compute = args.compute_type or ("float16" if asr == "cuda" else "int8")
    diarize = args.diarize_device
    if diarize == "auto":
        diarize = "cuda" if cuda else "mps" if torch.backends.mps.is_available() else "cpu"
    return asr, compute, diarize


def check_setup(args: argparse.Namespace) -> bool:
    """--check: report what's ready and what's missing. Never prints the token itself."""
    import platform

    from huggingface_hub import auth_check, get_token

    ok = True

    def report(status: str, text: str) -> None:
        icon = {"ok": "[green]✓[/]", "warn": "[yellow]![/]", "fail": "[red]✗[/]"}[status]
        console.print(f"  {icon} {text}")

    console.print(f"[bold]meeting-transcriber {__version__}[/] · Python {platform.python_version()} · "
                  f"{platform.system()} {platform.machine()}")
    if ffmpeg := shutil.which("ffmpeg"):
        report("ok", f"ffmpeg: {ffmpeg}")
    else:
        ok = False
        report("fail", f"ffmpeg not found — {FFMPEG_HINT}")

    asr, compute, diarize = pick_devices(args)
    report("ok", f"Whisper on {asr} ({compute}), speaker diarization on {diarize}")

    if not get_token():
        report("warn", "no Hugging Face token: speaker labels need one (see README), --no-diarize works without")
    else:
        try:
            auth_check(DIARIZE_MODEL)
            report("ok", f"Hugging Face token found, access to {DIARIZE_MODEL} confirmed")
        except Exception as e:  # noqa: BLE001 — gated (terms not accepted), invalid token or offline
            name = e.__class__.__name__
            hint = f"accept the terms at https://huggingface.co/{DIARIZE_MODEL}" if "Gated" in name or "401" in str(e) \
                else "couldn't verify (offline?)"
            report("warn", f"Hugging Face token found, but no access to {DIARIZE_MODEL}: {name} — {hint}")
    console.print("  [dim]The first run downloads the models (~2–4 GB) into ~/.cache/huggingface.[/]")
    return ok


def load_diarizer(device: str):
    from whisperx.diarize import DiarizationPipeline

    try:
        return DiarizationPipeline(model_name=DIARIZE_MODEL, token=os.getenv("HF_TOKEN") or None, device=device)
    except Exception as e:  # noqa: BLE001 — almost always missing access to the gated model
        sys.exit(
            f"\nCould not load the speaker diarization model: {e.__class__.__name__}: {e}\n\n"
            "Most likely there's no access to the gated model on Hugging Face:\n"
            f"  1) accept the terms at https://huggingface.co/{DIARIZE_MODEL}\n"
            "  2) create a token (type: Read) at https://huggingface.co/settings/tokens\n"
            "  3) run `uvx --from huggingface_hub hf auth login`,\n"
            "     or put HF_TOKEN=hf_... into ~/.config/meeting-transcriber/.env\n"
            "Or run without speaker labels: --no-diarize"
        )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    load_env()
    if args.check:
        sys.exit(0 if check_setup(args) else 1)
    if not shutil.which("ffmpeg"):
        sys.exit(f"ffmpeg not found. Install it — {FFMPEG_HINT}")

    files = [f.expanduser().resolve() for f in args.files]
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        sys.exit("Files not found:\n  " + "\n  ".join(missing))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    if not args.verbose:
        warnings.filterwarnings("ignore")
    import whisperx
    from rich.logging import RichHandler
    from whisperx.alignment import DEFAULT_ALIGN_MODELS_HF, DEFAULT_ALIGN_MODELS_TORCH
    from whisperx.audio import SAMPLE_RATE
    from whisperx.diarize import assign_word_speakers
    from whisperx.log_utils import setup_logging
    from whisperx.utils import LANGUAGES

    if args.lang:
        args.lang = args.lang.strip().lower()
        if args.lang not in LANGUAGES:
            sys.exit(f"Unknown language '{args.lang}': use a Whisper language code such as en, ru, de")

    setup_logging("info" if args.verbose else "error")
    # whisperx logs straight to sys.stdout, bypassing rich and tearing the live display; route it through rich
    logging.getLogger("whisperx").handlers[:] = [RichHandler(console=console, show_path=False)]
    if not args.verbose:
        # lightning sets its own level on import, so silence it after whisperx is imported
        logging.getLogger("lightning.pytorch").setLevel(logging.ERROR)

    asr_device, compute_type, diarize_device = pick_devices(args)

    console.print("[bold]Loading models[/]")
    # Diarization first: without access to the gated model, fail now rather than after an hour of transcription.
    diarizer = None
    if not args.no_diarize:
        with loading(f"speaker diarization (pyannote, {diarize_device})"):
            diarizer = load_diarizer(diarize_device)
    with loading(f"whisper {args.model} ({asr_device}, {compute_type})"):
        asr = whisperx.load_model(
            args.model, asr_device, compute_type=compute_type, language=args.lang, threads=args.threads,
        )

    align_models: dict[str, tuple | None] = {}

    def get_align_model(language: str) -> tuple | None:
        """Word-level alignment model; without it everything still works, but speakers are assigned per phrase."""
        if language in align_models:
            return align_models[language]
        align_models[language] = None
        fallback = "speakers per phrase" if diarizer else "timestamps per phrase"
        if language not in DEFAULT_ALIGN_MODELS_TORCH and language not in DEFAULT_ALIGN_MODELS_HF:
            console.print(f"  [yellow]![/] no alignment model for '{language}' — {fallback}")
            return None
        try:
            with loading(f"alignment ({language})"):
                align_models[language] = whisperx.load_align_model(language_code=language, device=asr_device)
        except Exception as e:  # noqa: BLE001 — network/download; alignment is optional, don't abort the run
            reason = escape(str(e) or e.__class__.__name__)
            console.print(f"  [yellow]![/] alignment model for '{language}' failed to load: {reason} — {fallback}")
        return align_models[language]

    if args.lang:  # language known upfront: load its alignment model with the others, not mid-way through a file
        get_align_model(args.lang)

    written: set[Path] = set()

    def process(path: Path) -> None:
        t0 = time.monotonic()
        with console.status("  reading audio…"):
            try:
                audio = whisperx.load_audio(str(path))
            except RuntimeError as e:  # carries ffmpeg's whole stderr; the gist is usually the last line
                msg = str(e)
                reason = "no audio track" if "does not contain any stream" in msg else msg.strip().splitlines()[-1]
                raise RuntimeError(f"ffmpeg couldn't read the file: {reason}") from None
        duration = len(audio) / SAMPLE_RATE
        language = args.lang or asr.preset_language  # *.en models are fixed to English and can't detect language
        auto = not language
        if auto:
            with console.status("  detecting language…"):
                language = asr.detect_language(audio)
        console.print(f"  [dim]{fmt_dur(duration)} · language {language}{' (auto)' if auto else ''}[/]")

        align = get_align_model(language)
        stages = [("asr", "Transcribe")]
        if align:
            stages.append(("align", "Align words"))
        if diarizer:
            stages.append(("diarize", "Speakers"))

        with Stages(stages) as st:
            with st.run("asr") as cb:
                result = asr.transcribe(audio, batch_size=args.batch_size, language=language, progress_callback=cb)
            if align:
                with st.run("align") as cb:
                    result = whisperx.align(result["segments"], *align, audio, asr_device, progress_callback=cb)
            if diarizer:
                with st.run("diarize") as cb:
                    diarize_df = diarizer(
                        audio,
                        num_speakers=args.speakers,
                        min_speakers=args.min_speakers,
                        max_speakers=args.max_speakers,
                        progress_callback=cb,
                    )
                    result = assign_word_speakers(diarize_df, result, fill_nearest=True)

        turns = build_turns(result["segments"])
        base, n = args.out or path.parent, 2
        out_path = base / f"{path.stem}.txt"
        while out_path in written:  # meeting.m4a + meeting.mp4, or same-named files with -o: don't overwrite
            out_path, n = base / f"{path.stem} ({n}).txt", n + 1
        written.add(out_path)
        out_path.write_text(render(turns, source=path.name, duration=duration, language=language), encoding="utf-8")

        elapsed = time.monotonic() - t0
        n_speakers = len({t.speaker for t in turns if t.speaker})
        summary = [f"{n_speakers} speaker{'' if n_speakers == 1 else 's'}"] if diarizer else []
        summary.append(f"{fmt_dur(elapsed)} ({duration / elapsed:.1f}x realtime)")
        # soft_wrap: otherwise rich hard-wraps a long path and it can't be copied
        console.print(f"  [green]✓[/] {' · '.join(summary)} → [bold]{escape(short_path(out_path))}[/]", soft_wrap=True)
        print(out_path.resolve(), flush=True)  # stdout carries only result paths, for scripts and agents

    t_start, failed = time.monotonic(), 0
    for i, path in enumerate(files, 1):
        console.print(f"\n[bold][{i}/{len(files)}] {escape(path.name)}[/]", soft_wrap=True)
        try:
            process(path)
        except Exception as e:  # noqa: BLE001 — one broken file must not abort the whole batch
            failed += 1
            console.print(f"  [red]✗ {escape(str(e) or e.__class__.__name__)}[/]", soft_wrap=True)
            if args.verbose:
                console.print_exception()

    if len(files) > 1:
        done = len(files) - failed
        console.print(f"\n[bold]Done:[/] {done} of {len(files)} · {fmt_dur(time.monotonic() - t_start)}")
    if failed:
        sys.exit(1)


def run() -> None:
    """Console-script entry point."""
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/]")
        sys.exit(130)


if __name__ == "__main__":
    run()
