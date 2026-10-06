"""Audio extraction: ffprobe parsing and ffmpeg arguments (pure), plus real mixes when ffmpeg is around."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from meeting_transcriber.media import ffmpeg_args, ffmpeg_error, parse_probe

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe_json(*streams, duration="12.5"):
    return json.dumps({"format": {"duration": duration}, "streams": list(streams)})


def audio(index, codec="aac"):
    return {"index": index, "codec_type": "audio", "codec_name": codec}


def test_parse_probe_video_with_two_audio_tracks():
    info = parse_probe(probe_json({"index": 0, "codec_type": "video", "codec_name": "h264"}, audio(1), audio(2)))
    assert (info.duration, info.audio_streams, info.has_video) == (12.5, [1, 2], True)


def test_undecodable_audio_track_is_skipped():
    no_decoder = {"index": 2, "codec_type": "audio"}  # ffprobe gives no codec_name, e.g. iPhone spatial audio
    info = parse_probe(probe_json({"index": 0, "codec_type": "video", "codec_name": "hevc"}, audio(1), no_decoder))
    assert info.audio_streams == [1] and info.undecodable_audio == 1


def test_cover_art_in_an_audio_file_is_not_a_video():
    cover = {"index": 1, "codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}}
    info = parse_probe(probe_json(audio(0, "mp3"), cover))
    assert info.audio_tracks == 1 and not info.has_video


def test_parse_probe_without_duration():
    assert parse_probe(probe_json(audio(0), duration="N/A")).duration is None


def test_single_track_is_mapped_explicitly():
    args = ffmpeg_args(Path("a.mp4"), [1])
    assert args[args.index("-map") + 1] == "0:1" and "-filter_complex" not in args and args[-1] == "s16le"


def test_without_ffprobe_ffmpeg_picks_the_track():
    assert "-map" not in ffmpeg_args(Path("a.mp4"), None)


def test_several_tracks_are_aligned_then_mixed():
    args = ffmpeg_args(Path("a.mkv"), [1, 2, 4])
    graph = args[args.index("-filter_complex") + 1]
    assert graph == (
        "[0:1]aresample=async=1:first_pts=0[a0];[0:2]aresample=async=1:first_pts=0[a1];"
        "[0:4]aresample=async=1:first_pts=0[a2];[a0][a1][a2]amix=inputs=3:duration=longest[mix]"
    )
    assert args[args.index("-map") + 1] == "[mix]"


def test_ffmpeg_error_keeps_the_last_line():
    assert str(ffmpeg_error("banner\nmore\nInvalid data found when processing input\n")).endswith(
        "Invalid data found when processing input")
    assert str(ffmpeg_error("Output file does not contain any stream")).endswith("no audio track")


def make_video(path, track1, track2, extra=()):
    """A tiny video with two audio tracks built from lavfi sources."""
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2",
        "-f", "lavfi", "-i", track1,
        *extra, "-f", "lavfi", "-i", track2,
        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-c:a", "flac", str(path),
    ], check=True)


def loudness(np, audio, start_s, end_s):
    return float(np.abs(audio[int(start_s * 16000):int(end_s * 16000)]).mean())


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_both_audio_tracks_of_a_video_end_up_in_the_audio(tmp_path):
    np = pytest.importorskip("numpy")
    from meeting_transcriber.media import load_audio, probe

    # track 1 sounds only in the first second, track 2 only in the second one (silence written into the track)
    video = tmp_path / "two_tracks.mkv"
    make_video(video, "sine=f=440:d=1,apad=whole_dur=2",
               "anullsrc=r=16000:cl=mono:d=1,aformat=sample_rates=16000[s];sine=f=880:d=1[t];[s][t]concat=v=0:a=1")
    info = probe(video)
    assert info.has_video and info.audio_tracks == 2
    audio = load_audio(video, info, lambda pct: None)
    assert loudness(np, audio, 0, 1) > 0.01 and loudness(np, audio, 1, 2) > 0.01  # nobody lost


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_a_track_that_starts_later_stays_at_its_time(tmp_path):
    np = pytest.importorskip("numpy")
    from meeting_transcriber.media import load_audio, probe

    # track 2 is a 1 s tone that starts at 1 s through the container timestamps, not through written silence:
    # mixed by sample count it would land at 0 s, on top of track 1
    video = tmp_path / "late_track.mkv"
    make_video(video, "sine=f=440:d=1", "sine=f=880:d=1", extra=("-itsoffset", "1"))
    audio = load_audio(video, probe(video))
    assert loudness(np, audio, 1.1, 1.9) > 0.01
    spectrum = np.abs(np.fft.rfft(audio[:16000]))  # first second: only track 1 (440 Hz), no 880 Hz from track 2
    assert spectrum[880] < spectrum[440] / 20
