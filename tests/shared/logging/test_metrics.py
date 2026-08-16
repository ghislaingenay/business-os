import json

from shared.logging.config import LoggingSettings, configure_logging
from shared.logging.metrics import log_dedup_check, log_upload_complete, log_variant_generated


def _configure(capsys) -> None:
    configure_logging(LoggingSettings(level="DEBUG", format="json"))
    capsys.readouterr()  # discard anything logged during configure_logging itself


def test_log_dedup_check_hit_emits_info_with_expected_fields(capsys) -> None:
    _configure(capsys)

    log_dedup_check(
        result="hit",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        latency_ms=12.345,
        source="cache",
        file_size=1024,
    )

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["level"] == "INFO"
    assert payload["event"] == "dedup_check"
    assert payload["result"] == "hit"
    assert payload["hash"] == "e3b0c44298fc1c14"  # truncated to 16 chars
    assert payload["latency_ms"] == 12.35  # rounded to 2 decimals
    assert payload["source"] == "cache"
    assert payload["file_size"] == 1024


def test_log_dedup_check_error_result_logs_at_error_level(capsys) -> None:
    _configure(capsys)

    log_dedup_check(result="error", sha256_hash="a" * 64, latency_ms=5.0, source="database")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["level"] == "ERROR"
    assert payload["event"] == "dedup_check"
    assert payload["result"] == "error"


def test_log_upload_complete_emits_expected_fields(capsys) -> None:
    _configure(capsys)

    log_upload_complete(file_id="file-1", size=2048, strategy="mediated", duration_ms=100.0)

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["event"] == "upload_complete"
    assert payload["file_id"] == "file-1"
    assert payload["size"] == 2048
    assert payload["strategy"] == "mediated"
    assert payload["duration_ms"] == 100.0
    assert payload["outcome"] == "success"


def test_log_variant_generated_defaults_outcome_to_success(capsys) -> None:
    _configure(capsys)

    log_variant_generated(file_id="file-1", variant_type="thumbnail", duration_ms=50.0)

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["event"] == "variant_generated"
    assert payload["variant_type"] == "thumbnail"
    assert payload["outcome"] == "success"


def test_log_variant_generated_can_report_failure_outcome(capsys) -> None:
    _configure(capsys)

    log_variant_generated(
        file_id="file-1", variant_type="unknown", duration_ms=10.0, outcome="failure"
    )

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["outcome"] == "failure"
