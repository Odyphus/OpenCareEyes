"""Pure tests for the scheduled stability gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci_stability_smoke import (
    MIB,
    READY_LOG_MARKER,
    ResourceSample,
    _file_contains_ready_marker,
    assert_resource_stable,
    assert_startup_ready,
    normalized_cpu_percent,
)


def _samples(handles, private_megabytes, *, threads=None, cpu=None):
    count = len(handles)
    thread_values = threads or [20] * count
    cpu_values = cpu or [None, *([0.2] * (count - 1))]
    return [
        ResourceSample(
            float(index),
            handle_count,
            private_mb * MIB,
            thread_count,
            cpu_percent,
        )
        for index, (handle_count, private_mb, thread_count, cpu_percent) in enumerate(
            zip(handles, private_megabytes, thread_values, cpu_values)
        )
    ]


def test_resource_gate_accepts_stable_process():
    assert_resource_stable(
        _samples(
            [100, 101, 100, 102, 101, 101],
            [80, 82, 81, 83, 82, 82],
        )
    )


def test_resource_gate_rejects_excessive_handle_growth():
    with pytest.raises(RuntimeError, match="handle count grew"):
        assert_resource_stable(
            _samples([100, 110, 120, 130, 140], [80, 80, 80, 80, 80]),
            max_handle_growth=20,
        )


def test_resource_gate_rejects_sustained_memory_growth():
    with pytest.raises(RuntimeError, match="private memory is still growing"):
        assert_resource_stable(
            _samples(
                [100, 100, 100, 100, 100, 100],
                [80, 82, 84, 86, 88, 90],
            ),
            max_private_growth_mb=64,
        )


def test_resource_gate_requires_enough_samples():
    with pytest.raises(ValueError, match="three"):
        assert_resource_stable(_samples([100, 100], [80, 80]))


def test_cpu_normalization_uses_total_logical_capacity():
    assert normalized_cpu_percent(None, 10.0, 2.0, 4) is None
    assert normalized_cpu_percent(10.0, 10.4, 2.0, 4) == pytest.approx(5.0)


def test_resource_gate_rejects_average_cpu_at_one_percent():
    with pytest.raises(RuntimeError, match="average normalized CPU"):
        assert_resource_stable(
            _samples(
                [100, 100, 100],
                [80, 80, 80],
                cpu=[None, 1.0, 1.0],
            )
        )


def test_resource_gate_rejects_busy_tail_even_when_full_average_is_low():
    with pytest.raises(RuntimeError, match="tail normalized CPU"):
        assert_resource_stable(
            _samples(
                [100] * 8,
                [80] * 8,
                cpu=[None, 0.1, 0.1, 0.1, 0.1, 1.2, 1.2, 1.2],
            ),
            tail_size=3,
        )


def test_resource_gate_rejects_any_sample_over_150_mib():
    with pytest.raises(RuntimeError, match="private memory reached"):
        assert_resource_stable(_samples([100, 100, 100], [149, 151, 149]))


def test_resource_gate_rejects_continuously_growing_threads():
    with pytest.raises(RuntimeError, match="thread count is still growing"):
        assert_resource_stable(
            _samples(
                [100] * 6,
                [80] * 6,
                threads=[20, 21, 22, 23, 24, 25],
            )
        )


def test_startup_gate_accepts_three_seconds_and_rejects_slower_start():
    assert_startup_ready(3.0)
    with pytest.raises(RuntimeError, match="packaged startup took 3.001s"):
        assert_startup_ready(3.001)

    assert_startup_ready(16.156, max_startup_seconds=30.0)


def test_ready_marker_requires_exact_nonempty_startup_message(tmp_path):
    log_path = tmp_path / "opencareyes.log"
    assert not _file_contains_ready_marker(log_path)

    log_path.write_text("", encoding="utf-8")
    assert not _file_contains_ready_marker(log_path)

    log_path.write_text("application starting", encoding="utf-8")
    assert not _file_contains_ready_marker(log_path)

    log_path.write_text(f"2026-07-18 INFO {READY_LOG_MARKER}\n", encoding="utf-8")
    assert _file_contains_ready_marker(log_path)


def test_workflow_builds_installer_once_and_reuses_artifact_for_release():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "windows-ci.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("- name: Build Inno Setup installer") == 1
    assert "needs: [build, installer]" in workflow
    assert workflow.count("name: OpenCareEyes-installer") == 2
    assert "path: installer_output/OpenCareEyes_Setup_*.exe" in workflow


def test_workflow_keeps_old_release_download_inside_tag_upgrade_path():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "windows-ci.yml").read_text(
        encoding="utf-8"
    )

    tag_guard = workflow.index("if ($env:GITHUB_REF -like 'refs/tags/v*')")
    baseline = workflow.index("$baselineVersion = '0.4.1'")
    upload = workflow.index("name: OpenCareEyes-installer")
    assert tag_guard < baseline < upload
    assert "if: github.event_name != 'schedule'" in workflow
    assert "v0.6.1 was never published as a tag or Release" in workflow


def test_application_ready_marker_is_emitted_after_startup_wiring():
    source = (Path(__file__).parents[1] / "src" / "opencareyes" / "__main__.py").read_text(
        encoding="utf-8"
    )

    chime_started = source.index("chime_service.start()")
    ready_logged = source.index('log.info("OpenCareEyes application ready")')
    event_loop_started = source.index("exit_code = app.exec()")

    assert chime_started < ready_logged < event_loop_started
    assert 'os.environ.get("OPENCAREYES_READY_FILE")' in source


def test_installer_job_uses_a_real_v4_upgrade_seed_without_project_import():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "windows-ci.yml").read_text(
        encoding="utf-8"
    )
    installer_job = workflow[workflow.index("  installer:") : workflow.index("  stability:")]

    assert "schema_version=4" in installer_job
    assert "from opencareyes.config.settings import Settings" not in installer_job
    assert "[IO.File]::WriteAllLines" in installer_job


def test_main_push_runs_the_bounded_stability_gate():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "windows-ci.yml").read_text(
        encoding="utf-8"
    )
    stability_job = workflow[workflow.index("  stability:") : workflow.index("  release:")]

    assert "github.event_name == 'schedule'" in stability_job
    assert "github.event_name == 'workflow_dispatch'" in stability_job
    assert "github.ref == 'refs/heads/main'" in stability_job
    assert "--duration-seconds $seconds" in stability_job
    assert "--max-startup-seconds 30" in stability_job
