"""16 kHz mono audio from anything ffmpeg can read: audio files and videos, with every audio track."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

SAMPLE_RATE = 16000  # what Whisper and pyannote expect


@dataclass
class MediaInfo:
    duration: float | None  # seconds, when the container knows it
    has_video: bool  # a real video stream, not just cover art in an audio file
    audio_streams: list[int] = field(default_factory=list)  # absolute indexes of audio streams ffmpeg can decode
    undecodable_audio: int = 0  # audio streams without a decoder (e.g. iPhone spatial audio): skipped

    @property
    def audio_tracks(self) -> int:
        return len(self.audio_streams)


def ffmpeg_error(stderr: str) -> RuntimeError:
    """ffmpeg's stderr is long; the gist is usually in the last line."""
    if "does not contain any stream" in stderr:
        reason = "no audio track"
    else:
        reason = (stderr.strip().splitlines() or ["unknown error"])[-1]
    return RuntimeError(f"ffmpeg couldn't read the file: {reason}")


def parse_probe(text: str) -> MediaInfo:
    data = json.loads(text or "{}")
    streams = data.get("streams", [])
    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    audio = [(s.get("index", pos), s) for pos, s in enumerate(streams) if s.get("codec_type") == "audio"]
    return MediaInfo(
        duration=duration,
        has_video=any(
            s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic") for s in streams
        ),
        # ffprobe leaves out codec_name when this ffmpeg has no decoder for the stream
        audio_streams=[index for index, s in audio if s.get("codec_name")],
        undecodable_audio=sum(not s.get("codec_name") for _, s in audio),
    )


def probe(path: Path) -> MediaInfo | None:
    """Streams and duration via ffprobe (ships with ffmpeg). None when ffprobe isn't installed."""
    if not shutil.which("ffprobe"):
        return None
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-of", "json",
         "-show_entries", "format=duration:stream=index,codec_type,codec_name:stream_disposition=attached_pic",
         str(path)],
        capture_output=True, encoding="utf-8", errors="replace",  # not the Windows code page: file names in errors
    )
    if out.returncode != 0:
        raise ffmpeg_error(out.stderr)
    return parse_probe(out.stdout)


def ffmpeg_args(path: Path, audio_streams: list[int] | None) -> list[str]:
    """Decode to 16 kHz mono 16-bit PCM, ignoring video and subtitles.

    Several audio tracks (e.g. OBS with the microphone and desktop audio on separate tracks) are mixed together,
    otherwise ffmpeg would take just one of them and everyone on the other track would be lost. Without ffprobe
    (audio_streams=None) ffmpeg picks one track itself.
    """
    args = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-sn", "-dn"]
    if audio_streams and len(audio_streams) > 1:
        # amix lines inputs up by sample count, not by time: first put every track on the file's timeline
        # (a late start or a gap becomes silence), or a track that starts later would be laid over the first one
        aligned = "".join(f"[0:{s}]aresample=async=1:first_pts=0[a{n}];" for n, s in enumerate(audio_streams))
        inputs = "".join(f"[a{n}]" for n in range(len(audio_streams)))
        mix = f"{aligned}{inputs}amix=inputs={len(audio_streams)}:duration=longest[mix]"
        args += ["-filter_complex", mix, "-map", "[mix]"]
    elif audio_streams:
        args += ["-map", f"0:{audio_streams[0]}"]
    return args + ["-ac", "1", "-ar", str(SAMPLE_RATE), "-acodec", "pcm_s16le", "-f", "s16le"]


def load_audio(path: Path, info: MediaInfo | None, on_progress: Callable[[float], None] | None = None):
    """The recording's audio as a float32 numpy array; reports progress (0–100) when the duration is known."""
    import numpy as np

    streams = info.audio_streams if info else None
    with tempfile.TemporaryDirectory(prefix="meeting-transcriber-") as tmp:
        raw, log = Path(tmp) / "audio.pcm", Path(tmp) / "ffmpeg.log"
        # audio goes to a temp file so stdout is free for ffmpeg's "-progress" key=value lines
        cmd = ffmpeg_args(path, streams) + ["-progress", "pipe:1", "-nostats", "-y", str(raw)]
        with open(log, "w") as err:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
            try:
                for line in proc.stdout:
                    if on_progress and info and info.duration and line.startswith("out_time_us="):
                        value = line.split("=", 1)[1].strip()
                        if value.isdigit():
                            on_progress(min(99.0, int(value) / 1e6 / info.duration * 100))
                proc.wait()
            finally:
                if proc.poll() is None:  # interrupted: don't leave ffmpeg running and writing into the temp dir
                    proc.kill()
                    proc.wait()
        if proc.returncode != 0:
            raise ffmpeg_error(log.read_text(encoding="utf-8", errors="replace"))
        audio = np.fromfile(raw, np.int16).astype(np.float32) / 32768.0

    if streams and len(streams) > 1 and audio.size:
        # amix divides every track by the number of tracks (silent ones too): bring the level back up, no clipping
        peak = float(np.abs(audio).max())
        if peak > 0:
            audio *= min(float(len(streams)), 0.9 / peak)
    return audio
