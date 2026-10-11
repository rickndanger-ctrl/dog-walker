import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/model-start.py"
SPEC = importlib.util.spec_from_file_location("dog_walk_model_start", SCRIPT)
model_start = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model_start)


def launch_plan():
    return {
        "model": "ornith",
        "label": "Ornith",
        "unit": "ornith15-server",
        "url": "http://127.0.0.1:18081",
        "model_path": "/models/Ornith.gguf",
        "release": "/opt/runtime/releases/current",
        "environment": {"LD_LIBRARY_PATH": "/opt/runtime/lib"},
        "server_argv": ["/opt/runtime/bin/llama-server", "-m", "/models/Ornith.gguf", "--ctx-size", "32768"],
        "start_argv": ["systemd-run", "--user", "--quiet", "--unit=ornith15-server",
                       "--setenv=LD_LIBRARY_PATH=/opt/runtime/lib", "--", "/opt/runtime/bin/llama-server",
                       "-m", "/models/Ornith.gguf", "--ctx-size", "32768"],
    }


def test_no_swap_plan_preserves_plan_and_inference_arguments():
    original = launch_plan()
    original_before = {**original, "environment": dict(original["environment"]),
                       "server_argv": list(original["server_argv"]), "start_argv": list(original["start_argv"])}

    result = model_start.no_swap_plan(original)

    assert original == original_before
    assert result is not original
    for key, value in original.items():
        if key != "start_argv":
            assert result[key] == value
    assert result["start_argv"] is not original["start_argv"]
    assert result["start_argv"].count("--property=MemorySwapMax=0") == 1
    separator = result["start_argv"].index("--")
    original_separator = original["start_argv"].index("--")
    assert result["start_argv"][separator - 1] == "--property=MemorySwapMax=0"
    assert result["start_argv"][separator + 1:] == original["start_argv"][original_separator + 1:]


def test_no_swap_plan_rejects_malformed_command_without_separator():
    plan = launch_plan()
    plan["start_argv"].remove("--")
    before = list(plan["start_argv"])
    with pytest.raises(ValueError):
        model_start.no_swap_plan(plan)
    assert plan["start_argv"] == before


def test_vision_budget_bounds_cpu_images_without_replacing_authored_limit():
    original = launch_plan()
    tuned = model_start.vision_plan(original)
    assert tuned['server_argv'][-4:] == ['--image-max-tokens', '512', '--image-min-tokens', '64']
    assert tuned['start_argv'][-4:] == tuned['server_argv'][-4:]
    assert original['server_argv'][-2:] == ['--ctx-size', '32768']
    authored = launch_plan()
    authored['server_argv'] += ['--image-max-tokens=1024']
    assert model_start.vision_plan(authored) is authored


def test_main_model_selection_preserves_legacy_default_and_rejects_unknown():
    assert model_start.arguments([]).model == 'ornith'
    for ident in ('gemma', 'qwen'):
        selected = model_start.arguments(['--model', ident, '--dry-run'])
        assert selected.model == ident and selected.dry_run
    with pytest.raises(SystemExit):
        model_start.arguments(['--model', 'unknown'])
