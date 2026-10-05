"""The Oracle server hunter's two decisions: is the stack free-only, and what does Oracle's answer mean."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("oracle_hunt", Path(__file__).parents[1] / "scripts" / "oracle_hunt.py")
hunt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hunt)

FREE = 'shape = "VM.Standard.A1.Flex"\n shape_config {\n ocpus = 1\n memory_in_gbs = 6\n }\n boot_volume_size_in_gbs = "100"'


def test_only_the_always_free_arm_server_is_allowed():
    assert hunt.shape_ok(FREE) is None
    assert "ARM" in hunt.shape_ok(FREE.replace("VM.Standard.A1.Flex", "VM.Standard.E5.Flex"))
    assert "ocpus" in hunt.shape_ok(FREE.replace("ocpus = 1", "ocpus = 8"))
    assert "memory" in hunt.shape_ok(FREE.replace("memory_in_gbs = 6", "memory_in_gbs = 32"))
    assert "boot" in hunt.shape_ok(FREE.replace('"100"', '"300"'))


def test_oracle_answers_mean_retry_slow_down_stop_or_done():
    assert hunt.classify("SUCCEEDED", "") == "success"
    assert hunt.classify("FAILED", "Error: 500-InternalError, Out of host capacity.") == "retry"
    assert hunt.classify("FAILED", "429 TooManyRequests") == "slow"
    assert hunt.classify("FAILED", "LimitExceeded: service limit reached") == "stop"
