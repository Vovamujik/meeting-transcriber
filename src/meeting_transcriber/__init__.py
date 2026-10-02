"""Transcribe meeting recordings locally into a timestamped, speaker-labelled .txt (WhisperX + pyannote)."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("meeting-transcriber")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0+local"
