# Retrieval evaluation lab

## The problem

RAG changes are hard to review without a stable dataset and a release gate. This project scores top-five retrieval recall and tenant safety with a deterministic local corpus. It also includes a citation-ID checker for generated answers. It makes regressions visible without paying for model calls.

## Architecture and how it works

`labeled cases → retriever → per-case hit/recall/latency → aggregate JSON → exit status`

`evaluate.py` accepts a retriever function and emits per-case scores, including recall and reciprocal rank. Its CLI reads JSONL predictions, so any retriever can supply results. Each row has `case_id`, `hits` (ordered objects with `id` and `tenant`), and optional `latency_ms`. `cases.json` maps questions and tenants to expected chunk IDs, including an unanswerable case. The process exits nonzero when mean recall falls below the threshold or a tenant mismatch appears. `--trace-file traces.jsonl` writes one redacted span per case with a shared trace ID, supplied latency, and score. `citation_check` verifies that a generated answer contains only retrieved chunk IDs; it does not prove that the cited text supports a claim.

## Run and example

Reports include `mean_hit_at_5`, the fraction of cases with at least one relevant hit in the
first five results. An unanswerable case passes this metric only when it returns no hits,
matching the per-case `hit_at_5` rule. This complements `mean_recall_at_5`, which measures
how many relevant chunks were found. The release gate still uses recall and tenant safety.

From this repository after `python -m pip install -e ".[dev]"`:

```bash
python -m evaluation_lab.seed --out predictions.jsonl
python -m evaluation_lab.evaluate --predictions predictions.jsonl --min-recall 0.8 --trace-file traces.jsonl
```

The seed command runs a simple lexical baseline over the included fixture documents and writes one prediction per labeled case. Replace that file with output from your own retriever to compare systems; keep the same chunk IDs and tenant fields. The evaluation output is JSON suitable for CI. Tests live in `tests/test_evaluate.py`.

The seed command writes UTF-8 predictions to a temporary file beside the destination, then replaces the destination only after the complete file closes successfully. Write or replacement failures report a CLI usage error (exit 2) naming the output, preserve existing predictions, clean up temporary files, and do not print a success message.
The seed command rejects output paths that refer to its cases file or fixture documents, including symbolic and hard links, before overwriting any input.
Seed inputs are read as UTF-8. Unreadable inputs, invalid text encoding, and malformed cases JSON produce CLI usage errors (exit 2) naming the input, before opening or changing the predictions output.
The seed command also validates case definitions with the evaluator's schema before opening the output. Invalid or empty case sets produce a usage error (exit 2) and preserve existing predictions.
Seed cases must also have unique tenant/question pairs, matching the evaluator CLI; ambiguous queries are rejected before replacing predictions.
Every labeled chunk must exist in the seed corpus under the expected tenant. Missing or renamed fixtures produce a usage error (exit 2) listing the missing labels and preserve existing predictions.

Case and prediction files use UTF-8. Missing or unreadable files and invalid JSON produce CLI usage errors (exit 2) before writing a report or traces; malformed prediction JSON and rows missing a valid case ID or hits include their line number.
Trace output uses UTF-8. If a requested trace file cannot be opened or written, the CLI reports a usage error (exit 2) identifying the path before printing a report.
The trace destination must differ from both input files, including symlink and hard-link aliases; conflicting destinations are rejected before appending any spans.
Duplicate prediction rows also produce a CLI usage error with the duplicate case ID and line number.
Missing or unexpected case IDs produce a CLI usage error (exit 2) identifying the predictions file, without writing a report or changing traces.

`hits` must be a list of objects with nonblank string `id` and `tenant` fields; use `[]` for no results. Malformed hits produce CLI usage errors (exit 2) identifying the prediction line and case, before a report or traces are written.

Cases must be a nonempty JSON list of objects with relevance labels. Malformed containers are rejected before retrieval.
Invalid case definitions produce CLI usage errors (exit 2), including the cases file path and validation reason, before reading predictions or writing traces.

Each labeled case must have a unique, nonblank string `id`; duplicate IDs are rejected so predictions and trace spans remain unambiguous.
Each case also requires nonblank string `tenant` and `question` fields; invalid inputs are rejected before any retrieval runs.
`relevant_ids` must be a list of nonblank strings; use an empty list for an unanswerable case. Malformed labels are rejected before retrieval or scoring.
Supplied `latency_ms` values must be finite, nonnegative numbers; omitted or null values remain null in reports. Invalid latencies produce a CLI usage error (exit 2) identifying the prediction line and case, before producing a report or writing traces.
The CLI also requires unique tenant/question pairs, because its retriever selects predictions by tenant and question. Ambiguous pairs produce a CLI usage error (exit 2) identifying the cases file before reading predictions, scoring, or writing traces.

## Concepts and choices

This lab keeps the judge deterministic: expected chunk IDs are human-labeled, not generated by the model being evaluated. It measures retrieval independently of answer generation. The JSONL spans provide local correlation, not distributed tracing. Its function boundary makes it possible to compare a vector retriever against the lexical baseline.

## Trade-offs, limitations, and next production steps

Six labeled queries are far too small for a real release gate. Build a representative dataset with answerable, unanswerable, adversarial, multilingual, and permission-sensitive questions. Track precision, nDCG, citation support, groundedness, cost, p95 latency, and model/provider versions. Replace local JSONL spans with OpenTelemetry across ingest, retrieve, rerank, and generation. Keep a human-reviewed holdout set separate from tuning data.

## Interview preparation

Explain why retrieval and generation need separate metrics, what recall@k misses, why model-graded answers need calibration, how to avoid test-set leakage, and how you would set a release threshold from production failures.

## Verify

Run `python -m pytest -q` and `python -m ruff check .` from this repository.
