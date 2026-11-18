"""The benchmark harness itself (bench/), exercised with the Fake provider: no server, no model."""
import json

import pytest

from bench.run_benchmark import main, summarize
from bench.scenarios import build_scenarios


def test_there_are_the_seven_planned_scenarios():
    ids = [s.id for s in build_scenarios()]
    assert len(ids) == 7 and len(set(ids)) == 7


def test_fake_run_writes_metrics_without_prompts_or_answers(tmp_path):
    code = main(["--provider", "fake", "--scenarios", "S1_short_pt", "S7_think_false", "--out", str(tmp_path)])
    assert code == 0
    run_dir = next(tmp_path.iterdir())
    raw = (run_dir / "results.json").read_text(encoding="utf-8")
    report = json.loads(raw)
    runs = report["models"][0]["runs"]
    assert [r["scenario"] for r in runs] == ["S1_short_pt", "S7_think_false"]
    assert all(r["ok"] and r["completion_tokens"] == 5 for r in runs)
    assert "Resposta simulada" not in raw and "content" not in runs[0]  # no content unless asked
    assert "ttft" not in raw.lower()  # TTFT is never reported: nothing is streamed
    assert "não é tempo até o primeiro token" in (run_dir / "summary.md").read_text(encoding="utf-8")


def test_failed_functional_check_gives_nonzero_exit(tmp_path):
    # the dry-run fake answers plain text, so the JSON-schema scenario must fail its check
    assert main(["--provider", "fake", "--scenarios", "S3_json_schema", "--out", str(tmp_path)]) == 1


def test_repeat_is_capped():
    with pytest.raises(SystemExit):
        main(["--provider", "fake", "--repeat", "50"])


def test_summary_handles_a_skipped_model():
    md = summarize({"provider": "ollama", "repeat": 1, "started": "t",
                    "models": [{"model": "m:1", "runs": [], "skipped": "server unavailable"}]})
    assert "Ignorado" in md and "server unavailable" in md
