"""Keep the documented baseline and its labeled fixture IDs in sync."""
import json
import shutil
from pathlib import Path

import pytest

from evaluation_lab import seed
from evaluation_lab.evaluate import main as evaluate_main


@pytest.mark.parametrize("invalid", [None, {}, [], [None], [
    {"id": "invalid", "tenant": "demo", "relevant_ids": []},
]])
def test_invalid_cases_leave_existing_predictions_unchanged(
    tmp_path, monkeypatch, capsys, invalid,
):
    bundled = Path(seed.__file__).parent
    root = tmp_path / "evaluation_lab"
    shutil.copytree(bundled / "fixtures", root / "fixtures")
    cases_path = root / "cases.json"
    # Include a valid case first to catch partial output before a later failure.
    cases = json.loads((bundled / "cases.json").read_text(encoding="utf-8"))
    if isinstance(invalid, list) and invalid:
        invalid = [cases[0], *invalid]
    cases_path.write_text(json.dumps(invalid), encoding="utf-8")
    monkeypatch.setattr(seed, "__file__", str(root / "seed.py"))
    output = tmp_path / "predictions.jsonl"
    output.write_bytes(b"existing predictions\n")
    monkeypatch.setattr("sys.argv", ["seed", "--out", str(output)])
    with pytest.raises(SystemExit) as exc:
        seed.main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"invalid cases file {cases_path}:" in captured.err
    assert "Traceback" not in captured.err
    assert output.read_bytes() == b"existing predictions\n"


@pytest.mark.parametrize("failure", ["missing_cases", "invalid_json", "invalid_fixture_encoding"])
def test_input_failure_is_usage_error_without_changing_predictions(
    tmp_path, monkeypatch, capsys, failure,
):
    bundled = Path(seed.__file__).parent
    root = tmp_path / "evaluation_lab"
    shutil.copytree(bundled / "fixtures", root / "fixtures")
    cases = root / "cases.json"
    shutil.copyfile(bundled / "cases.json", cases)
    if failure == "missing_cases":
        cases.unlink()
        failed_path = cases
    elif failure == "invalid_json":
        cases.write_text("{", encoding="utf-8")
        failed_path = cases
    else:
        failed_path = root / "fixtures" / "oncall.md"
        failed_path.write_bytes(b"\xff")
    monkeypatch.setattr(seed, "__file__", str(root / "seed.py"))
    output = tmp_path / "predictions.jsonl"
    output.write_bytes(b"existing predictions\n")
    monkeypatch.setattr("sys.argv", ["seed", "--out", str(output)])
    with pytest.raises(SystemExit) as exc:
        seed.main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"cannot read seed input {failed_path}" in captured.err
    assert "Traceback" not in captured.err
    assert output.read_bytes() == b"existing predictions\n"


@pytest.mark.parametrize("input_name", ["cases.json", "fixtures/oncall.md"])
@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink"])
def test_seed_cannot_overwrite_its_inputs(tmp_path, monkeypatch, capsys, input_name, alias):
    bundled = Path(seed.__file__).parent
    root = tmp_path / "evaluation_lab"
    shutil.copytree(bundled / "fixtures", root / "fixtures")
    shutil.copyfile(bundled / "cases.json", root / "cases.json")
    monkeypatch.setattr(seed, "__file__", str(root / "seed.py"))
    source = root / input_name
    before = source.read_bytes()
    output = source
    if alias != "direct":
        output = tmp_path / "predictions.jsonl"
        if alias == "symlink":
            output.symlink_to(source)
        else:
            output.hardlink_to(source)
    monkeypatch.setattr("sys.argv", ["seed", "--out", str(output)])
    with pytest.raises(SystemExit) as exc:
        seed.main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "predictions file must differ from cases and fixture files" in captured.err
    assert source.read_bytes() == before


def test_bundled_baseline_passes_release_gate_and_writes_redacted_traces(
    tmp_path, monkeypatch, capsys,
):
    predictions = tmp_path / "predictions.jsonl"
    traces = tmp_path / "traces.jsonl"
    monkeypatch.setattr("sys.argv", ["seed", "--out", str(predictions)])
    seed.main()
    capsys.readouterr()
    cases = json.loads(Path(seed.__file__).with_name("cases.json").read_text())
    rows = [json.loads(line) for line in predictions.read_text().splitlines()]
    assert [row["case_id"] for row in rows] == [case["id"] for case in cases]
    for case, row in zip(cases, rows):
        if not case["relevant_ids"]:
            assert row["hits"] == []
        assert all(hit["tenant"] == case["tenant"] for hit in row["hits"])

    monkeypatch.setattr("sys.argv", ["evaluate", "--predictions", str(predictions),
                                    "--min-recall", "1", "--trace-file", str(traces)])
    evaluate_main()
    report = json.loads(capsys.readouterr().out)
    assert report["mean_hit_at_5"] == 1
    assert report["mean_recall_at_5"] == 1
    assert report["mean_reciprocal_rank"] == 1
    assert report["tenant_safe"] is True
    spans = [json.loads(line) for line in traces.read_text().splitlines()]
    assert [span["case_id"] for span in spans] == [case["id"] for case in cases]
    assert len({span["trace_id"] for span in spans}) == 1
    for row, span in zip(rows, spans):
        assert span["latency_ms"] == row["latency_ms"]
        assert set(span) == {"trace_id", "event", "case_id", "latency_ms",
                             "recall_at_5", "tenant_safe"}


@pytest.mark.parametrize("failure", ["directory", "missing_parent", "write"])
def test_output_failure_is_usage_error_without_success_message(
    tmp_path, monkeypatch, capsys, failure,
):
    path = tmp_path / "predictions.jsonl"
    if failure == "directory":
        path.mkdir()
    elif failure == "missing_parent":
        path = tmp_path / "missing" / "predictions.jsonl"
    else:
        from contextlib import contextmanager

        original_open = Path.open

        @contextmanager
        def failing_open(self, *args, **kwargs):
            if self == path:
                class FullDisk:
                    def write(self, text):
                        raise OSError("disk full")
                yield FullDisk()
            else:
                with original_open(self, *args, **kwargs) as handle:
                    yield handle

        monkeypatch.setattr(Path, "open", failing_open)
    monkeypatch.setattr("sys.argv", ["seed", "--out", str(path)])
    with pytest.raises(SystemExit) as exc:
        seed.main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"cannot write predictions file {path}" in captured.err
    assert "Traceback" not in captured.err
