"""Bounded Windows stability smoke used by scheduled GitHub Actions runs."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MIB = 1024 * 1024
MAX_PRIVATE_MEMORY_MIB = 150
MAX_NORMALIZED_CPU_PERCENT = 1.0
MAX_STARTUP_SECONDS = 3.0
STARTUP_PROBE_TIMEOUT_SECONDS = 30.0
READY_LOG_MARKER = "OpenCareEyes application ready"


@dataclass(frozen=True, slots=True)
class ResourceSample:
    """One aggregate sample for the packaged process tree."""

    elapsed_seconds: float
    handles: int
    private_bytes: int
    thread_count: int
    normalized_cpu_percent: float | None


@dataclass(frozen=True, slots=True)
class SmokeResult:
    """Startup timing plus steady-state samples from one packaged run."""

    startup_seconds: float
    samples: tuple[ResourceSample, ...]


@dataclass(slots=True)
class _SamplingState:
    logical_cpu_count: int
    previous_cpu_seconds: float | None = None
    previous_sampled_at: float | None = None


def normalized_cpu_percent(
    previous_cpu_seconds: float | None,
    current_cpu_seconds: float,
    elapsed_seconds: float,
    logical_cpu_count: int,
) -> float | None:
    """Normalize process-tree CPU usage to total logical CPU capacity."""

    if previous_cpu_seconds is None:
        return None
    if elapsed_seconds <= 0:
        raise ValueError("CPU sample elapsed time must be positive")
    if logical_cpu_count <= 0:
        raise ValueError("logical CPU count must be positive")
    used_seconds = max(0.0, current_cpu_seconds - previous_cpu_seconds)
    return used_seconds / elapsed_seconds / logical_cpu_count * 100.0


def assert_startup_ready(
    startup_seconds: float,
    *,
    max_startup_seconds: float = MAX_STARTUP_SECONDS,
) -> None:
    """Enforce the packaged application's hard startup target."""

    if startup_seconds < 0:
        raise ValueError("startup time cannot be negative")
    if startup_seconds > max_startup_seconds:
        raise RuntimeError(
            f"packaged startup took {startup_seconds:.3f}s, limit is {max_startup_seconds:.3f}s"
        )


def assert_resource_stable(
    samples: Iterable[ResourceSample],
    *,
    max_handle_growth: int = 32,
    max_thread_growth: int = 8,
    max_private_growth_mb: int = 64,
    max_private_memory_mb: int = MAX_PRIVATE_MEMORY_MIB,
    max_cpu_percent: float = MAX_NORMALIZED_CPU_PERCENT,
    tail_size: int = 6,
) -> None:
    """Reject sustained or excessive growth after the caller's warm-up period."""

    values = tuple(samples)
    if len(values) < 3:
        raise ValueError("at least three resource samples are required")

    first = values[0]
    last = values[-1]
    private_ceiling = max_private_memory_mb * MIB
    for sample in values:
        if sample.private_bytes > private_ceiling:
            raise RuntimeError(
                f"private memory reached {sample.private_bytes / MIB:.1f} MiB, "
                f"limit is {max_private_memory_mb} MiB"
            )

    cpu_values = [
        sample.normalized_cpu_percent
        for sample in values
        if sample.normalized_cpu_percent is not None
    ]
    if not cpu_values:
        raise RuntimeError("no normalized CPU samples were collected")
    average_cpu = sum(cpu_values) / len(cpu_values)
    if average_cpu >= max_cpu_percent:
        raise RuntimeError(
            f"average normalized CPU was {average_cpu:.3f}%, limit is <{max_cpu_percent:.3f}%"
        )

    handle_growth = last.handles - first.handles
    thread_growth = last.thread_count - first.thread_count
    private_growth = last.private_bytes - first.private_bytes
    if handle_growth > max_handle_growth:
        raise RuntimeError(f"handle count grew by {handle_growth}, limit is {max_handle_growth}")
    if thread_growth > max_thread_growth:
        raise RuntimeError(f"thread count grew by {thread_growth}, limit is {max_thread_growth}")
    private_limit = max_private_growth_mb * MIB
    if private_growth > private_limit:
        raise RuntimeError(
            f"private memory grew by {private_growth / MIB:.1f} MiB, "
            f"limit is {max_private_growth_mb} MiB"
        )

    tail = values[-min(tail_size, len(values)) :]
    tail_cpu_values = [
        sample.normalized_cpu_percent
        for sample in tail
        if sample.normalized_cpu_percent is not None
    ]
    tail_average_cpu = sum(tail_cpu_values) / len(tail_cpu_values)
    if tail_average_cpu >= max_cpu_percent:
        raise RuntimeError(
            f"tail normalized CPU was {tail_average_cpu:.3f}%, limit is <{max_cpu_percent:.3f}%"
        )

    handle_values = [sample.handles for sample in tail]
    if _strictly_growing(handle_values) and handle_values[-1] - handle_values[0] > 3:
        raise RuntimeError("handle count is still growing in every tail sample")

    thread_values = [sample.thread_count for sample in tail]
    if _strictly_growing(thread_values) and thread_values[-1] - thread_values[0] > 2:
        raise RuntimeError("thread count is still growing in every tail sample")

    private_values = [sample.private_bytes for sample in tail]
    if _strictly_growing(private_values) and private_values[-1] - private_values[0] > 8 * MIB:
        raise RuntimeError("private memory is still growing in every tail sample")


def _strictly_growing(values: list[int]) -> bool:
    return len(values) >= 3 and all(after > before for before, after in zip(values, values[1:]))


class _DenyNetworkManager:
    """Network manager trap proving service construction is offline."""

    def __init__(self) -> None:
        self.requests = 0

    def get(self, _request):
        self.requests += 1
        raise AssertionError("weather attempted network access without consent")


def assert_weather_stays_offline() -> None:
    """Run an event-loop turn and prove disabled weather performs zero requests."""

    from PySide6.QtCore import QCoreApplication

    from opencareyes.application.weather_service import WeatherService

    app = QCoreApplication.instance() or QCoreApplication([])
    network = _DenyNetworkManager()
    service = WeatherService(network_manager=network)
    app.processEvents()
    service.cancel()
    if network.requests:
        raise RuntimeError("disabled weather performed a network request")


def _prepare_isolated_settings(settings_path: Path) -> None:
    from opencareyes.config.settings import Settings

    previous = os.environ.get("OPENCAREYES_SETTINGS_PATH")
    os.environ["OPENCAREYES_SETTINGS_PATH"] = str(settings_path)
    try:
        settings = Settings()
        settings.onboarding_completed = True
        settings.autostart = False
        settings.weather_enabled = False
        settings.sync_checked()
    finally:
        if previous is None:
            os.environ.pop("OPENCAREYES_SETTINGS_PATH", None)
        else:
            os.environ["OPENCAREYES_SETTINGS_PATH"] = previous


def _process_tree(root):
    import psutil

    try:
        processes = [root, *root.children(recursive=True)]
    except psutil.Error as exc:
        raise RuntimeError(f"unable to enumerate packaged process tree: {exc}") from exc
    return tuple({process.pid: process for process in processes}.values())


def _sample_tree(root, started_at: float, state: _SamplingState) -> ResourceSample:
    import psutil

    handles = 0
    private_bytes = 0
    thread_count = 0
    cpu_seconds = 0.0
    for process in _process_tree(root):
        try:
            handles += process.num_handles()
            thread_count += process.num_threads()
            memory = process.memory_info()
            private_bytes += int(getattr(memory, "private", memory.rss))
            cpu_times = process.cpu_times()
            cpu_seconds += float(cpu_times.user + cpu_times.system)
            for connection in process.net_connections(kind="inet"):
                if connection.raddr:
                    raise RuntimeError(
                        f"unexpected external network connection from process {process.pid}"
                    )
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied as exc:
            raise RuntimeError(f"unable to inspect process {process.pid}") from exc
    sampled_at = time.monotonic()
    elapsed = (
        sampled_at - state.previous_sampled_at if state.previous_sampled_at is not None else 0.0
    )
    cpu_percent = normalized_cpu_percent(
        state.previous_cpu_seconds,
        cpu_seconds,
        elapsed,
        state.logical_cpu_count,
    )
    state.previous_cpu_seconds = cpu_seconds
    state.previous_sampled_at = sampled_at
    return ResourceSample(
        sampled_at - started_at,
        handles,
        private_bytes,
        thread_count,
        cpu_percent,
    )


def _file_contains_ready_marker(path: Path) -> bool:
    """Return whether the application has completed startup wiring."""

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return READY_LOG_MARKER in content


def _wait_for_startup_ready(
    root,
    child: subprocess.Popen,
    executable: Path,
    ready_path: Path,
    started_at: float,
    *,
    timeout_seconds: float = STARTUP_PROBE_TIMEOUT_SECONDS,
) -> float:
    """Wait for a stable onefile pair and the application-ready marker file."""

    import psutil

    expected_executable = os.path.normcase(str(executable.resolve()))
    deadline = started_at + timeout_seconds
    consecutive_ready = 0
    last_process_count = 0
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"packaged app exited during startup: {child.returncode}")
        processes = _process_tree(root)
        last_process_count = len(processes)
        try:
            paths_match = all(
                os.path.normcase(process.exe()) == expected_executable for process in processes
            )
        except (OSError, psutil.Error):
            paths_match = False
        if len(processes) == 2 and paths_match and _file_contains_ready_marker(ready_path):
            consecutive_ready += 1
            if consecutive_ready >= 2:
                return time.monotonic() - started_at
        else:
            consecutive_ready = 0
        time.sleep(0.05)
    elapsed = time.monotonic() - started_at
    raise RuntimeError(
        f"packaged startup was not ready after {elapsed:.3f}s "
        f"(processes={last_process_count}, "
        f"marker_ready={_file_contains_ready_marker(ready_path)})"
    )


def _stop_tree(root) -> None:
    import psutil

    try:
        processes = list(reversed(_process_tree(root)))
    except RuntimeError:
        return
    for process in processes:
        try:
            process.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(processes, timeout=5)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=5)


def run_packaged_smoke(
    executable: Path,
    *,
    duration_seconds: float,
    warmup_seconds: float,
    sample_interval_seconds: float,
    max_startup_seconds: float = MAX_STARTUP_SECONDS,
) -> SmokeResult:
    """Launch the packaged app, monitor it, then always stop its process tree."""

    import psutil

    if sys.platform != "win32":
        raise RuntimeError("the packaged stability smoke requires Windows")
    if not executable.is_file():
        raise FileNotFoundError(executable)
    minimum_duration = max_startup_seconds + warmup_seconds + sample_interval_seconds * 2
    if duration_seconds <= minimum_duration:
        raise ValueError("duration must include startup, warm-up, and at least three samples")

    with tempfile.TemporaryDirectory(prefix="opencareeyes-stability-") as temp_dir:
        temp = Path(temp_dir)
        settings_path = temp / "settings.ini"
        _prepare_isolated_settings(settings_path)
        ready_path = temp / "application-ready.marker"
        env = os.environ.copy()
        env.update(
            {
                "LOCALAPPDATA": str(temp / "localappdata"),
                "OPENCAREYES_INSTANCE_KEY": f"OpenCareEyes-Stability-{uuid.uuid4().hex}",
                "OPENCAREYES_READY_FILE": str(ready_path),
                "OPENCAREYES_SETTINGS_PATH": str(settings_path),
                "QT_QPA_PLATFORM": "offscreen",
            }
        )
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        started_at = time.monotonic()
        child = subprocess.Popen(
            [str(executable.resolve())],
            env=env,
            creationflags=creation_flags,
        )
        root = psutil.Process(child.pid)
        temp / "localappdata" / "OpenCareEyes" / "logs" / "opencareeyes.log"
        samples: list[ResourceSample] = []
        try:
            deadline = started_at + duration_seconds
            startup_seconds = _wait_for_startup_ready(
                root,
                child,
                executable,
                ready_path,
                started_at,
            )
            assert_startup_ready(
                startup_seconds,
                max_startup_seconds=max_startup_seconds,
            )
            warmup_deadline = time.monotonic() + warmup_seconds
            while time.monotonic() < warmup_deadline:
                if child.poll() is not None:
                    raise RuntimeError(f"packaged app exited during warm-up: {child.returncode}")
                time.sleep(min(1.0, warmup_deadline - time.monotonic()))

            state = _SamplingState(psutil.cpu_count(logical=True) or os.cpu_count() or 1)
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError(f"packaged app exited unexpectedly: {child.returncode}")
                samples.append(_sample_tree(root, started_at, state))
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(sample_interval_seconds, remaining))
            samples.append(_sample_tree(root, started_at, state))
            assert_resource_stable(samples)
            return SmokeResult(startup_seconds, tuple(samples))
        finally:
            _stop_tree(root)
            child.wait(timeout=10)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=600)
    parser.add_argument("--warmup-seconds", type=float, default=30)
    parser.add_argument("--sample-interval-seconds", type=float, default=5)
    parser.add_argument(
        "--max-startup-seconds",
        type=float,
        default=MAX_STARTUP_SECONDS,
        help="startup limit; keep the 3-second default outside shared CI runners",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    assert_weather_stays_offline()
    result = run_packaged_smoke(
        args.executable,
        duration_seconds=args.duration_seconds,
        warmup_seconds=args.warmup_seconds,
        sample_interval_seconds=args.sample_interval_seconds,
        max_startup_seconds=args.max_startup_seconds,
    )
    samples = result.samples
    first, last = samples[0], samples[-1]
    cpu_values = [
        sample.normalized_cpu_percent
        for sample in samples
        if sample.normalized_cpu_percent is not None
    ]
    average_cpu = sum(cpu_values) / len(cpu_values)
    print(
        "stability smoke passed: "
        f"startup {result.startup_seconds:.3f}s, {len(samples)} samples, "
        f"CPU {average_cpu:.3f}%, threads {first.thread_count}->{last.thread_count}, "
        f"handles {first.handles}->{last.handles}, private memory "
        f"{first.private_bytes / MIB:.1f}->{last.private_bytes / MIB:.1f} MiB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
