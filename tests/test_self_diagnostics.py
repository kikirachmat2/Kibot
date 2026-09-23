import os
import tempfile
from intelligence.self_diagnostics import SelfDiagnostics


def test_self_diagnostics_disk_usage():
    diag = SelfDiagnostics()
    res = diag.check_disk_usage()
    assert res["status"] in ["HEALTHY", "WARNING_HIGH_DISK_USAGE"]
    assert res["total_gb"] > 0


def test_self_diagnostics_clock_sync():
    diag = SelfDiagnostics()
    res = diag.check_clock_synchronization()
    assert res["status"] == "HEALTHY"
    assert res["skew_seconds"] < 1.0


def test_self_diagnostics_credentials():
    diag_no_keys = SelfDiagnostics(api_key="", api_secret="")
    assert diag_no_keys.check_api_credentials()["status"] == "MISSING_OR_INVALID_KEYS"

    diag_with_keys = SelfDiagnostics(api_key="123456789012", api_secret="abcdef1234567890")
    assert diag_with_keys.check_api_credentials()["status"] == "HEALTHY"


def test_self_diagnostics_log_scan():
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("2026-09-20 INFO Starting KiBot\n")
        f.write("2026-09-20 ERROR Test error 1\n")
        f.write("2026-09-20 CRITICAL Test critical 2\n")
        temp_log = f.name

    try:
        diag = SelfDiagnostics(log_path=temp_log)
        res = diag.check_log_errors_24h()
        assert res["error_count"] == 2
        assert res["status"] == "HEALTHY"

        all_res = diag.run_all_checks()
        assert "overall_status" in all_res
    finally:
        if os.path.exists(temp_log):
            os.remove(temp_log)
