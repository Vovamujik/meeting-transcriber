"""Pure-logic tests: turn building and rendering. No models, no network."""
from meeting_transcriber.cli import build_turns, fmt_ts, parse_args, render


def word(text, start=None, speaker=None):
    w = {"word": text}
    if start is not None:
        w["start"], w["end"] = start, start + 0.3
    if speaker:
        w["speaker"] = speaker
    return w


def test_fmt_ts():
    assert fmt_ts(0) == "00:00:00"
    assert fmt_ts(3725.9) == "01:02:05"


def test_speaker_change_inside_one_whisper_segment():
    segments = [{
        "start": 0.0, "end": 4.0, "text": "x", "speaker": "SPEAKER_01",
        "words": [
            word("Hi.", 0.0, "SPEAKER_01"), word("How", 0.5, "SPEAKER_01"), word("are", 0.8, "SPEAKER_01"),
            word("Fine,", 2.0, "SPEAKER_00"), word("2024", None), word("rocks.", 2.6, "SPEAKER_00"),
        ],
    }]
    turns = build_turns(segments)
    assert [t.speaker for t in turns] == ["SPEAKER_01", "SPEAKER_00"]
    # an unaligned word (no timing, no speaker) inherits from the previous word
    assert turns[1].parts == ["Fine,", "2024", "rocks."]


def test_segments_without_alignment_are_used_whole():
    turns = build_turns([{"start": 5.0, "end": 7.0, "text": " Sounds good. ", "speaker": "A"}])
    assert len(turns) == 1 and turns[0].parts == ["Sounds good."]


def test_long_monologue_splits_only_at_sentence_end():
    words = [word(f"w{i}" + ("." if i % 10 == 9 else ""), i * 2.0, "A") for i in range(50)]
    turns = build_turns([{"start": 0, "end": 100, "text": "x", "speaker": "A", "words": words}])
    assert len(turns) > 1
    assert all(t.parts[-1].endswith(".") for t in turns[:-1])


def test_render_numbers_speakers_by_first_appearance():
    turns = build_turns([
        {"start": 0, "end": 1, "text": "Hello.", "speaker": "SPEAKER_07"},
        {"start": 2, "end": 3, "text": "Hi.", "speaker": "SPEAKER_02"},
    ])
    out = render(turns, source="call.m4a", duration=65, language="en")
    assert "File: call.m4a" in out and "Duration: 00:01:05" in out and "Speakers: 2" in out
    assert "[00:00:00] Speaker 1: Hello." in out
    assert "[00:00:02] Speaker 2: Hi." in out


def test_render_uses_russian_labels_for_russian():
    turns = build_turns([{"start": 0, "end": 1, "text": "Привет.", "speaker": "A"}])
    out = render(turns, source="m.m4a", duration=1, language="ru")
    assert "Файл: m.m4a" in out and "[00:00:00] Спикер 1: Привет." in out


def test_render_without_diarization_has_no_speaker_labels():
    turns = build_turns([{"start": 1, "end": 2, "text": "Test", "words": [word("Test", 1.0)]}])
    out = render(turns, source="a.wav", duration=2, language="en")
    assert "[00:00:01] Test" in out and "Speaker" not in out


def test_parse_args_validation():
    import pytest

    with pytest.raises(SystemExit):
        parse_args(["a.m4a", "--speakers", "0"])
    with pytest.raises(SystemExit):
        parse_args(["a.m4a", "--min-speakers", "5", "--max-speakers", "2"])
    with pytest.raises(SystemExit):
        parse_args([])  # no files and no --check
    assert parse_args(["--check"]).check


def test_cjk_sentence_end_splits_long_monologue():
    words = [word("字", i * 2.0, "A") for i in range(30)] + [word("。", 60.0, "A")]
    words += [word("字", 62.0 + i, "A") for i in range(5)]
    turns = build_turns([{"start": 0, "end": 70, "text": "x", "speaker": "A", "words": words}])
    assert len(turns) == 2 and turns[0].parts[-1] == "。"
