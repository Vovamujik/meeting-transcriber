"""meeting-transcriber: transcribe meeting recordings locally into an LLM-ready .txt.

Pipeline: Whisper (speech → text) → wav2vec2 (word-level timestamps) → pyannote (who speaks when) →
words grouped into speaker turns → "[00:01:23] Speaker 1: text".
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from rich.markup import escape

from . import __version__, media
from .ui import Stages, busy, console, fmt_dur, loading, short_path

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
SENTENCE_END = (".", "?", "!", "…", "。", "？", "！")
MAX_TURN_SECONDS = 45  # split long monologues at a sentence end so timestamps stay frequent
LANGS_WITHOUT_SPACES = {"ja", "zh"}
CONFIG_ENV = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "meeting-transcriber" / ".env"
REPO_ENV = Path(__file__).resolve().parents[2] / ".env"  # .env in the root of a git checkout (src/ layout)
LOGIN_HINT = "uvx --from huggingface_hub hf auth login"
# Browser logins give OAuth tokens that expire, and the huggingface_hub version whisperx pins can't refresh them.
LOGIN_ADVICE = f"`{LOGIN_HINT} --force` and choose \"Paste an access token\" (browser-login tokens expire)"
SLOW_FIRST_RUN = "(the first run after installing or updating can take a few minutes)"
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


def hf_token_file() -> Path:
    """Where `hf auth login` keeps the token: same resolution as huggingface_hub.constants.HF_TOKEN_PATH.

    Computed by hand because importing huggingface_hub before use_cache_if_offline() would freeze its offline flag.
    Call it after the .env files are loaded: they may set HF_HOME or HF_TOKEN_PATH.
    """

    def norm(path: str) -> str:
        return os.path.expandvars(os.path.expanduser(path))

    home = norm(os.environ.get("HF_HOME") or os.path.join(norm(os.environ.get("XDG_CACHE_HOME") or "~/.cache"),
                                                          "huggingface"))
    return Path(norm(os.environ.get("HF_TOKEN_PATH") or os.path.join(home, "token")))


def clean_token(value: str | None) -> str:
    """Same cleaning as huggingface_hub's get_token(): no line breaks, no surrounding spaces."""
    return (value or "").replace("\r", "").replace("\n", "").strip()


def http_status(e: BaseException) -> int | None:
    return getattr(getattr(e, "response", None), "status_code", None)


@dataclass
class TokenSource:
    label: str  # where the active token comes from, for messages
    removal: str  # how to get rid of it


def env_var_source(name: str) -> TokenSource:
    if sys.platform == "win32":
        removal = (f"remove the {name} environment variable (Settings → \"Edit environment variables for your "
                   "account\", also check $PROFILE) and open a new terminal")
    else:
        removal = f"remove `export {name}=...` from your shell profile (~/.zshrc, ~/.bashrc) and open a new terminal"
    return TokenSource(f"the {name} environment variable", removal)


def load_env() -> TokenSource | None:
    """Loads the .env files and says where the active Hugging Face token comes from (None: no token at all).

    Same precedence as huggingface_hub: HF_TOKEN (environment, then .env in the git checkout, then
    ~/.config/meeting-transcriber/.env) → HUGGING_FACE_HUB_TOKEN → the token saved by `hf auth login`.
    The token value itself is never printed.
    """
    from dotenv import load_dotenv

    source = env_var_source("HF_TOKEN") if clean_token(os.environ.get("HF_TOKEN")) else None
    for env in (REPO_ENV, CONFIG_ENV):
        if env.is_file():
            load_dotenv(env)  # never overrides variables that are already set
            if source is None and clean_token(os.environ.get("HF_TOKEN")):
                where = short_path(env)
                source = TokenSource(f"HF_TOKEN in {where}", f"delete the HF_TOKEN line from {where}")
    if source is None and clean_token(os.environ.get("HUGGING_FACE_HUB_TOKEN")):
        source = env_var_source("HUGGING_FACE_HUB_TOKEN")
    if source is None and hf_token_file().is_file():
        source = TokenSource("`hf auth login`", f"log in again: {LOGIN_ADVICE}")
    return source


@dataclass
class Diagnosis:
    kind: str  # "ok", "no-token", "invalid", "no-access" or "unknown" (couldn't check, e.g. offline)
    message: str


def diagnose_token(source: TokenSource | None) -> Diagnosis:
    """Can the active token use the diarization model, and if not, why and what to do."""
    from huggingface_hub import auth_check, get_token, whoami
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError

    token = get_token()
    if not token or source is None:
        return Diagnosis("no-token", "no Hugging Face token: speaker labels need one (see README); "
                                     "--no-diarize works without")
    try:
        info = whoami(token=token)
    except Exception as e:  # noqa: BLE001 — classified below
        if http_status(e) != 401:
            return Diagnosis("unknown", f"couldn't verify the Hugging Face token (offline?): {e.__class__.__name__}")
        msg = f"the token from {source.label} is invalid or expired (HTTP 401)"
        saved_file = hf_token_file()
        saved = clean_token(saved_file.read_text()) if saved_file.is_file() else ""
        if saved and saved != token:
            try:
                whoami(token=saved)
                return Diagnosis("invalid",
                                 f"{msg} and overrides your working `hf auth login` token — {source.removal}")
            except Exception:  # noqa: BLE001 — the saved token doesn't work either
                pass
        if source.label == "`hf auth login`":
            return Diagnosis("invalid", f"{msg} — {source.removal}")
        return Diagnosis("invalid", f"{msg} — {source.removal}, then log in with {LOGIN_ADVICE}")

    name = info.get("name", "?")
    gated_access = ("\"Read access to contents of all public gated repos you can access\" "
                    "(https://huggingface.co/settings/tokens)")
    try:
        auth_check(DIARIZE_MODEL, token=token)
    except GatedRepoError:
        msg = (f"the token from {source.label} works (account {name}) but has no access to the model — accept the "
               f"terms at https://huggingface.co/{DIARIZE_MODEL} while logged in as {name}")
        if info.get("auth", {}).get("accessToken", {}).get("role") == "fineGrained":
            msg += f", and give this fine-grained token {gated_access}"
        return Diagnosis("no-access", msg)
    except HfHubHTTPError as e:
        if http_status(e) == 403:  # a plain 403 (no GatedRepo code): typically a fine-grained token w/o gated access
            return Diagnosis("no-access", f"the token from {source.label} works (account {name}) but isn't allowed to "
                                          f"read {DIARIZE_MODEL} — give this fine-grained token {gated_access}, "
                                          "or use a token of type Read")
        return Diagnosis("unknown", f"couldn't verify access to {DIARIZE_MODEL}: {e.__class__.__name__}")
    except Exception as e:  # noqa: BLE001 — network
        return Diagnosis("unknown", f"couldn't verify access to {DIARIZE_MODEL} (offline?): {e.__class__.__name__}")
    return Diagnosis("ok", f"Hugging Face token from {source.label} (account {name}), "
                           f"access to {DIARIZE_MODEL} confirmed")


def use_cache_if_offline() -> None:
    """Offline, huggingface_hub retries every cached model file (~6 min per run); one quick probe avoids that."""
    if os.environ.get("HF_HUB_OFFLINE"):
        return
    import requests  # same proxy and CA settings as huggingface_hub

    try:
        requests.head(os.environ.get("HF_ENDPOINT") or "https://huggingface.co", timeout=5)
    except requests.RequestException:
        os.environ["HF_HUB_OFFLINE"] = "1"  # read by huggingface_hub at import time, so call this before importing it
        console.print("[dim]No connection to Hugging Face: using cached models.[/]")


def pick_devices(args: argparse.Namespace) -> tuple[str, str, str]:
    """(Whisper/alignment device, Whisper compute type, diarization device)."""
    import torch

    cuda = torch.cuda.is_available()
    asr = args.device if args.device != "auto" else ("cuda" if cuda else "cpu")
    compute = args.compute_type or ("float16" if asr == "cuda" else "int8")
    diarize = args.diarize_device
    if diarize == "auto":
        diarize = "cuda" if cuda else "mps" if torch.backends.mps.is_available() else "cpu"
    if "cuda" in (asr, diarize) and not cuda:
        sys.exit("CUDA isn't available: no NVIDIA GPU, or this PyTorch build has no CUDA support "
                 "(PyTorch from PyPI is CPU-only on Windows). Use --device cpu --diarize-device auto.")
    return asr, compute, diarize


def check_setup(args: argparse.Namespace, token_source: TokenSource | None) -> bool:
    """--check: report what's ready and what's missing. Never prints the token itself."""
    import platform

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
    if not shutil.which("ffprobe"):
        report("warn", "ffprobe not found (it normally comes with ffmpeg): from recordings with several audio tracks "
                       "only the first one is used")

    with busy(f"  checking devices… {SLOW_FIRST_RUN}"):
        asr, compute, diarize = pick_devices(args)
    report("ok", f"Whisper on {asr} ({compute}), speaker diarization on {diarize}")

    with busy("  checking Hugging Face access…"):
        diagnosis = diagnose_token(token_source)
    report("ok" if diagnosis.kind == "ok" else "warn", diagnosis.message)
    console.print("  [dim]The first run downloads the models (~2–4 GB) into ~/.cache/huggingface.[/]")
    return ok


def load_diarizer(device: str, token_source: TokenSource | None, verbose: bool):
    import contextlib
    import io
    import re

    from huggingface_hub import get_token
    from whisperx.diarize import DiarizationPipeline

    # On a failed download pyannote print()s its own hints, with Python code; ours below fit a CLI better.
    chatter = sys.stdout if verbose else io.StringIO()
    try:
        with contextlib.redirect_stdout(chatter):
            # the same cleaned token --check validates (a stray line break in a .env would break the HTTP header)
            return DiarizationPipeline(model_name=DIARIZE_MODEL, token=get_token(), device=device)
    except Exception as e:  # noqa: BLE001 — reported to the user below
        from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

        first_line = (str(e).strip().splitlines() or [""])[0]
        details = "[details: " + re.sub(r"hf_\w+", "hf_***", f"{e.__class__.__name__}: {first_line}") + "]"
        # hf_hub_download turns a plain 403 (e.g. a fine-grained token) into LocalEntryNotFoundError
        forbidden = isinstance(e.__cause__, HfHubHTTPError) and http_status(e.__cause__) == 403
        if not (isinstance(e, RepositoryNotFoundError) or forbidden):
            sys.exit(f"\nCould not load the speaker diarization model. Check the network connection (the first run "
                     f"downloads it), or run without speaker labels: --no-diarize\n{details}")
        diagnosis = diagnose_token(token_source)
        steps = "" if diagnosis.kind in ("invalid", "no-access") else (
            "Access takes three steps:\n"
            f"  1) accept the terms at https://huggingface.co/{DIARIZE_MODEL}\n"
            "  2) create a token (type: Read) at https://huggingface.co/settings/tokens\n"
            f"  3) run {LOGIN_ADVICE},\n"
            "     or put HF_TOKEN=hf_... into ~/.config/meeting-transcriber/.env\n"
        )
        sys.exit(f"\nNo access to the speaker diarization model: {diagnosis.message}.\n\n{steps}"
                 f"Or run without speaker labels: --no-diarize\n{details}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)  # --help and --version still go to stdout
    # pyannote and torch.hub print() diagnostics; keep the real stdout for result paths only
    result_out, sys.stdout = sys.stdout, sys.stderr
    token_source = load_env()
    if args.check:
        sys.exit(0 if check_setup(args, token_source) else 1)
    if not shutil.which("ffmpeg"):
        sys.exit(f"ffmpeg not found. Install it — {FFMPEG_HINT}")
    if not shutil.which("ffprobe"):
        console.print("[yellow]![/] ffprobe not found (it normally comes with ffmpeg): from recordings with several "
                      "audio tracks only one is used")

    files = [f.expanduser().resolve() for f in args.files]
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        sys.exit("Files not found:\n  " + "\n  ".join(missing))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    if not args.verbose:
        warnings.filterwarnings("ignore")
    # Importing torch/whisperx takes seconds, and minutes on the first run after an install (Python compiles the
    # packages): show that something is happening instead of an empty terminal.
    with busy(f"Starting… {SLOW_FIRST_RUN}"):
        use_cache_if_offline()
        import whisperx
        from rich.logging import RichHandler
        from whisperx.alignment import DEFAULT_ALIGN_MODELS_HF, DEFAULT_ALIGN_MODELS_TORCH
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
            diarizer = load_diarizer(diarize_device, token_source, args.verbose)
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
            if language in DEFAULT_ALIGN_MODELS_TORCH:  # torch.hub never re-checks a cached (possibly partial) file
                console.print("    [dim]Interrupted download? Delete it from ~/.cache/torch/hub/checkpoints[/]")
        return align_models[language]

    if args.lang:  # language known upfront: load its alignment model with the others, not mid-way through a file
        get_align_model(args.lang)

    written: set[Path] = set()

    def process(path: Path) -> None:
        t0 = time.monotonic()
        info = media.probe(path)  # None without ffprobe: then just the first audio track, no progress
        if info and not info.audio_tracks:
            if info.undecodable_audio:
                raise RuntimeError("no audio track ffmpeg can decode")
            raise RuntimeError(f"no audio track in {'the video' if info.has_video else 'the file'}")
        with Stages([("extract", "Extract audio")]) as st, st.run("extract") as cb:
            audio = media.load_audio(path, info, cb)
        duration = len(audio) / media.SAMPLE_RATE
        language = args.lang or asr.preset_language  # *.en models are fixed to English and can't detect language
        auto = not language
        if auto:
            with console.status("  detecting language…"):
                language = asr.detect_language(audio)
        kind = ["video"] if info and info.has_video else []
        if info and info.audio_tracks > 1:
            kind.append(f"{info.audio_tracks} audio tracks mixed")
        if info and info.undecodable_audio:
            kind.append(f"{info.undecodable_audio} undecodable audio track(s) skipped")
        parts = [fmt_dur(duration), f"language {language}{' (auto)' if auto else ''}"]
        if kind:
            parts.append(", ".join(kind))
        console.print(f"  [dim]{' · '.join(parts)}[/]")

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
        while out_path in written or out_path.exists():  # never overwrite: same-named inputs or an existing file
            out_path, n = base / f"{path.stem} ({n}).txt", n + 1
        written.add(out_path)
        out_path.write_text(render(turns, source=path.name, duration=duration, language=language), encoding="utf-8")

        elapsed = time.monotonic() - t0
        n_speakers = len({t.speaker for t in turns if t.speaker})
        summary = [f"{n_speakers} speaker{'' if n_speakers == 1 else 's'}"] if diarizer else []
        summary.append(f"{fmt_dur(elapsed)} ({duration / elapsed:.1f}x realtime)")
        # soft_wrap: otherwise rich hard-wraps a long path and it can't be copied
        console.print(f"  [green]✓[/] {' · '.join(summary)} → [bold]{escape(short_path(out_path))}[/]", soft_wrap=True)
        print(out_path.resolve(), file=result_out, flush=True)  # stdout carries only result paths

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


def exit_cleanly_on_termination() -> None:
    """SIGTERM/SIGHUP (terminal closed, agent stopped) → a normal exit, so ffmpeg and temp files get cleaned up."""
    for name in ("SIGTERM", "SIGHUP"):  # no SIGHUP on Windows
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda signum, _frame: sys.exit(128 + signum))


def run() -> None:
    """Console-script entry point."""
    exit_cleanly_on_termination()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # result paths must survive non-UTF-8 pipes (Windows code pages)
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/]")
        sys.exit(130)


if __name__ == "__main__":
    run()
