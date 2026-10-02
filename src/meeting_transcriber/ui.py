"""Terminal output: per-stage progress bars, model loading lines, result lines. Everything goes to stderr."""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, Progress, ProgressColumn, SpinnerColumn, Task, TaskID, TextColumn
from rich.table import Column
from rich.text import Text

console = Console(stderr=True, highlight=False)


def fmt_dur(sec: float) -> str:
    s = int(sec)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_secs(sec: float) -> str:
    return f"{sec:.1f}s" if sec < 60 else fmt_dur(sec)


def short_path(path: Path) -> str:
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)


@contextmanager
def loading(label: str):
    """Model loading: prints "✓ label · time" once it's ready.

    Deliberately no live spinner: on the first run Hugging Face draws its own download bars and they must stay visible.
    """
    t0 = time.monotonic()
    yield
    console.print(f"  [green]✓[/] {escape(label)} [dim]· {fmt_secs(time.monotonic() - t0)}[/]")


class StageIcon(SpinnerColumn):
    """Spinner for the running stage, ✓ done, ✗ failed, · pending."""

    def render(self, task: Task) -> Text:
        if task.fields.get("failed"):
            return Text("✗", style="red")
        if task.finished:
            return Text("✓", style="green")
        if not task.started:
            return Text("·", style="dim")
        return super().render(task)


class StageBar(BarColumn):
    """Pending stages get an empty bar: rich pulses them by default, which looks like they're already running."""

    def render(self, task: Task):
        bar = super().render(task)
        # a stage that failed before reporting any percentage would otherwise keep pulsing
        if not task.started or (task.fields.get("failed") and task.total is None):
            bar.pulse, bar.total, bar.completed = False, 100, 0
        return bar


class StageStats(ProgressColumn):
    """Percentage, elapsed time and a rough ETA."""

    def render(self, task: Task) -> Text:
        if not task.started:
            return Text("")
        elapsed = (task.finished_time if task.finished else task.elapsed) or 0
        pct = f"{task.percentage:3.0f}%" if task.total is not None else "    "
        out = Text.assemble(pct, ("  " + fmt_dur(elapsed), "dim"))
        if task.finished or task.fields.get("failed"):
            return out
        # Not task.time_remaining: rich estimates speed over a 30 s window, but whisperx reports progress in bursts
        # (one per batch, often minutes apart), so the window holds a single instantaneous burst and the ETA sticks
        # at "~0:01". Use the average rate from stage start to the last update instead, minus the time since then.
        updated_at, p = task.fields.get("updated_at"), task.percentage
        if updated_at is not None and task.start_time is not None and p >= 3 and elapsed >= 5:
            t_upd = updated_at - task.start_time
            eta = t_upd * (100 - p) / p - (elapsed - t_upd)
            if eta >= 1:
                out.append(f"  ~{fmt_dur(eta)} left", style="dim")
        return out


class Stages:
    """All processing stages of one file, visible at once; the running one has a spinner and an ETA."""

    def __init__(self, labels: list[tuple[str, str]]):
        self.progress = Progress(
            TextColumn(" "),
            StageIcon(),
            TextColumn("{task.description}"),
            StageBar(bar_width=30),
            # in a narrow terminal shrink the bar rather than wrapping the stats onto a new line
            StageStats(table_column=Column(no_wrap=True)),
            console=console,
        )
        self._ids: dict[str, TaskID] = {
            key: self.progress.add_task(label, total=None, start=False) for key, label in labels
        }

    def __enter__(self) -> Stages:
        self.progress.start()
        return self

    def __exit__(self, *exc) -> None:
        self.progress.stop()

    @contextmanager
    def run(self, key: str):
        """Yields a progress callback (0–100). Until it's first called the bar pulses: running, % unknown."""
        task_id = self._ids[key]
        self.progress.start_task(task_id)

        def on_progress(pct: float) -> None:
            # StageStats needs the update time for its ETA; same clock as rich (time.monotonic)
            self.progress.update(task_id, total=100, completed=pct, updated_at=time.monotonic())

        try:
            yield on_progress
        except BaseException:
            self.progress.update(task_id, failed=True)
            raise
        self.progress.update(task_id, total=100, completed=100)
