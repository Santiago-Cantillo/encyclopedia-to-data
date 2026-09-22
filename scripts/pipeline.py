"""Run the scanned-PDF-to-data pipeline, one stage at a time or end to end.  [GENERIC]

    sample     cut a page range from a scanned PDF and write its provenance manifest
    ocr        add a text layer with OCRmyPDF, correcting rotation and skew
    extract    split the OCR text into entries (extract_biographies.py)
    structure  one API request per entry, saved as it completes; reruns reuse saved results
    export     nested JSON, wide CSV and token usage
    validate   structural checks and review flags
    run        all of the above

Nothing in this file depends on the book or on the fields being extracted: defaults come
from book_settings.py; the prompt, schema, request text and review rule come from
biography_schema.py. book_settings.py explains the [GENERIC] / [ENCYCLOPEDIA] /
[THIS PROJECT] tiers. All paths default to the repository layout.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.metadata
import json
import os
import ssl
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

import book_settings as book  # [THIS PROJECT] command-line defaults only

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data/raw/sample_pages_004_006.pdf"
SOURCE = ROOT / "data/raw/source.json"
OUTPUT = ROOT / "outputs"


def read_json(path):
    """Load a UTF-8 JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    """Write JSON through a temporary file, so an interrupted run never leaves a half-written result."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_csv(path, rows):
    """Write rows as UTF-8 CSV with a byte-order mark for Excel; nested values become JSON strings."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})


def digest(value):
    """SHA-256 of a JSON-serialisable value, with sorted keys so equal content gives equal hashes."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    """SHA-256 of a file's bytes."""
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


# ------------------------------------------------------------------ sample and ocr
def sample(args):
    """Trim without OCR or rotation, so the original challenge is preserved."""
    import pymupdf
    with pymupdf.open(args.input) as original, pymupdf.open() as selected:
        if not 1 <= args.first <= args.last <= len(original):
            raise ValueError("Page range must be within the input PDF (one-based, inclusive).")
        args.pdf.parent.mkdir(parents=True, exist_ok=True)
        if args.pdf.exists():
            raise ValueError(f"Sample already exists: {args.pdf}")
        selected.insert_pdf(original, from_page=args.first - 1, to_page=args.last - 1)
        selected.save(args.pdf, garbage=4, deflate=True)
    write_json(args.source, {
        "source_id": args.source_id,
        "title": book.SOURCE_TITLE,
        "note": book.SOURCE_NOTE,
        "original_file": args.input.name,
        "original_sha256": file_hash(args.input),
        "sample_sha256": file_hash(args.pdf),
        "pdf_viewer_pages": list(range(args.first, args.last + 1)),
        "printed_pages": list(range(args.printed_first, args.printed_first + args.last - args.first + 1)),
        "last_entry_incomplete": True,
        "boundary_note": "Set last_entry_incomplete to whether the final entry continues beyond the selected pages.",
    })
    print(f"Saved {args.last - args.first + 1} original scan pages to {args.pdf}. Edit {args.source} if needed.")


def ocr(args):
    """Add a text layer with OCRmyPDF, correcting rotation and skew; never overwrites an existing result."""
    import pymupdf
    metadata = read_json(args.source)
    if file_hash(args.pdf) != metadata["sample_sha256"]:
        raise ValueError("Sample PDF does not match its source manifest.")
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / "searchable.pdf"
    if target.exists():
        raise ValueError("OCR output exists. Use a new --output directory for a fresh run.")
    command = [sys.executable, "-m", "ocrmypdf", "--rotate-pages", "--deskew", "--output-type", "pdf",
               "--optimize", "0", "--jobs", str(args.jobs), "--language", args.languages]
    if args.skip_text:
        command.append("--skip-text")  # keep pages that already carry a text layer
    subprocess.run(command + [str(args.pdf), str(target)], check=True)
    with pymupdf.open(target) as document:
        lengths = [len(page.get_text().strip()) for page in document]
    if len(lengths) != len(metadata["pdf_viewer_pages"]) or not all(lengths):
        raise ValueError("OCR did not produce text on every source page.")
    write_json(args.output / "ocr_run.json", {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": metadata["sample_sha256"],
        "searchable_sha256": file_hash(target),
        "languages": args.languages,
        "text_characters_per_page": lengths,
        "python": sys.version.split()[0],
        "packages": {p: importlib.metadata.version(p) for p in ("PyMuPDF", "ocrmypdf", "openai")},
    })
    print(f"OCR complete: {lengths} text characters per page.")


# ------------------------------------------------------------------------ extract
def extract(args):
    """Split the OCR text into entries: entries.json, entries.csv, lines.txt and skipped.json."""
    from extract_biographies import extract_records
    metadata = read_json(args.source)
    ocr_metadata = read_json(args.output / "ocr_run.json")
    if (ocr_metadata["source_sha256"] != metadata["sample_sha256"]
            or file_hash(args.output / "searchable.pdf") != ocr_metadata["searchable_sha256"]):
        raise ValueError("OCR output or source manifest has changed. Use the matching run files.")
    records, lines, skipped = extract_records(args.output / "searchable.pdf", metadata)
    if not records:
        raise ValueError("No entries found. Inspect OCR and layout before calling the API.")
    write_json(args.output / "entries.json", records)
    write_csv(args.output / "entries.csv", records)
    write_json(args.output / "skipped.json", skipped)
    (args.output / "lines.txt").write_text("\n".join(f"[PDF p.{p}] {t}" for t, p in lines) + "\n", encoding="utf-8")
    empty = sum(1 for r in records if not r["body"])
    print(f"Extracted {len(records)} entries: {empty} with an empty body, {len(skipped)} set aside in skipped.json. "
          "Inspect entries.csv before paid processing.")


# ---------------------------------------------------------------------- structure
def evidence_issues(data, text):
    """Convention shared with the schema: every item of a list field quotes the input in `evidence`."""
    problems = []
    for field, items in data.items():
        if isinstance(items, list):
            for index, item in enumerate(items, 1):
                evidence = item.get("evidence", "")
                if not evidence or evidence not in text:
                    problems.append(f"{field}[{index}]: evidence is not an exact source substring")
                elif len(evidence.split()) > 25:
                    problems.append(f"{field}[{index}]: evidence exceeds 25 words")
    return problems


def structure(args):
    """Synchronous requests, saved per entry; rerunning reuses matching successes."""
    from dotenv import load_dotenv
    from openai import OpenAI, APIError, DefaultHttpxClient
    from jsonschema import validate as validate_schema, ValidationError
    from biography_schema import SYSTEM_PROMPT, RESPONSE_FORMAT, model_input
    entries = read_json(args.output / "entries.json")
    if args.limit:
        entries = entries[:args.limit]
    if not entries:
        raise ValueError("No entries to process.")
    config = {"model": args.model, "reasoning": args.reasoning, "max_output_tokens": args.max_output_tokens,
              "prompt": SYSTEM_PROMPT, "format": RESPONSE_FORMAT}
    pending = []
    for record in entries:
        fingerprint = digest({"config": config, "record": record})
        cached = args.output / "responses" / f"{record['id']}.json"
        if cached.exists():
            saved = read_json(cached)
            if saved.get("fingerprint") != fingerprint:
                raise ValueError("Saved response uses different input/settings. Use a new --output directory.")
            if saved.get("status") == "complete":
                validate_schema(saved["data"], RESPONSE_FORMAT["schema"])
                continue
        pending.append((record, fingerprint, cached))
    print(f"Selected {len(entries)} entries; {len(pending)} API requests needed.", flush=True)
    if args.dry_run or not pending:
        return
    load_dotenv(args.env_file, override=False)
    key = os.getenv("OPENAI_API_KEY", "")
    if not key or "INSERT" in key or key == "your_api_key_here":
        raise ValueError("Set OPENAI_API_KEY in your environment or private .env file.")
    # Explicit endpoint keeps this credential scoped to OpenAI. The SDK retries connection errors,
    # rate limits and server errors with exponential backoff up to --max-retries times.
    client = OpenAI(api_key=key, base_url="https://api.openai.com/v1", timeout=1800.0,
                    max_retries=args.max_retries, http_client=DefaultHttpxClient(verify=ssl.create_default_context()))

    def process_one(position, task):
        record, fingerprint, cached = task
        print(f"[{position}/{len(pending)}] {record['id']} - {record['header']}", flush=True)
        saved = {"id": record["id"], "fingerprint": fingerprint, "status": "failed",
                 "input_sha256": digest(record),
                 "model": args.model, "reasoning": args.reasoning,
                 "max_output_tokens": args.max_output_tokens,
                 "created_at_utc": datetime.now(timezone.utc).isoformat()}
        request = {"model": args.model, "instructions": SYSTEM_PROMPT, "input": model_input(record),
                   "text": {"format": RESPONSE_FORMAT}, "max_output_tokens": args.max_output_tokens, "store": False}
        if args.reasoning == "none":
            request["temperature"] = 0            # models without reasoning: deterministic settings instead
        else:
            request["reasoning"] = {"effort": args.reasoning}
        try:
            response = client.responses.create(**request)
            saved["usage"] = response.usage.model_dump() if response.usage else {}
            saved["returned_model"] = response.model
            saved["response_status"] = response.status
            if response.status != "completed" or not response.output_text:
                saved["error"] = f"Response was {response.status} or had no JSON text; inspect before retrying."
                saved["raw_output"] = response.model_dump()
            else:
                data = json.loads(response.output_text)
                validate_schema(data, RESPONSE_FORMAT["schema"])
                saved.update(status="complete", data=data)
        except APIError as error:
            # Do not print exception bodies: authentication errors may contain key fragments.
            saved["error"] = f"{type(error).__name__}; HTTP status {getattr(error, 'status_code', None)}"
            write_json(cached, saved)
            raise ValueError(f"API request failed: {saved['error']}. Progress was saved; rerun to resume.") from None
        except (ValueError, ValidationError) as error:
            saved["error"] = f"Invalid structured result: {type(error).__name__}"
        write_json(cached, saved)
        print(f"  {record['id']}: {saved['status']}", flush=True)
        return saved["status"]

    failures = 0
    executor = ThreadPoolExecutor(max_workers=args.workers)
    futures = [executor.submit(process_one, position, task) for position, task in enumerate(pending, 1)]
    try:
        for future in as_completed(futures):
            failures += future.result() != "complete"
    finally:
        # On an API error, finish requests already sent and cancel queued requests.
        executor.shutdown(wait=True, cancel_futures=True)
        client.close()
    if failures:
        raise ValueError(f"{failures} requests need review; results were saved without repairing or hiding failures.")


# ------------------------------------------------------------- export and validate
def flatten(record, prefix=""):
    """Nested dicts and lists -> one flat row: data_education_1_degree, data_jobs_2_organization, ..."""
    result = {}
    for key, value in record.items():
        name = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten(value, name))
        elif isinstance(value, list):
            for i, item in enumerate(value, 1):
                if isinstance(item, dict):
                    result.update(flatten(item, f"{name}_{i}"))
                else:
                    result[f"{name}_{i}"] = item
        else:
            result[name] = value
    return result


def export(args):
    """Combine saved responses into biographies.json, biographies.csv, failures.json and usage.json."""
    from jsonschema import validate as validate_schema
    from biography_schema import RESPONSE_FORMAT, model_input, needs_review
    entries = read_json(args.output / "entries.json")
    records, failures = [], []
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cached_input_tokens": 0, "reasoning_tokens": 0}
    for entry in entries:
        path = args.output / "responses" / f"{entry['id']}.json"
        saved = read_json(path) if path.exists() else {}
        status = saved.get("status", "missing")
        if status != "complete":
            failures.append({"id": entry["id"], "status": status, "error": saved.get("error")})
            continue
        if saved.get("input_sha256") != digest(entry):
            raise ValueError(f"Saved response input has changed: {entry['id']}. Use a new output directory.")
        validate_schema(saved["data"], RESPONSE_FORMAT["schema"])
        data = saved["data"]
        problems = evidence_issues(data, model_input(entry))
        records.append({**entry, "model": saved.get("returned_model", saved["model"]),
                        "reasoning": saved["reasoning"], "max_output_tokens": saved.get("max_output_tokens"),
                        "data": data,
                        "validation": {"evidence_issues": problems, "needs_review": needs_review(entry, data, problems)}})
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            usage[key] += saved.get("usage", {}).get(key, 0)
        usage["cached_input_tokens"] += saved.get("usage", {}).get("input_tokens_details", {}).get("cached_tokens", 0)
        usage["reasoning_tokens"] += saved.get("usage", {}).get("output_tokens_details", {}).get("reasoning_tokens", 0)
    write_json(args.output / "biographies.json", records)
    write_csv(args.output / "biographies.csv", [flatten(record) for record in records])
    write_json(args.output / "failures.json", failures)
    write_json(args.output / "usage.json", {"successful_entries": len(records), "successful_response_tokens": usage,
                                           "note": "Excludes failed attempts and retries; use billing records for charges."})
    print(f"Exported {len(records)} structured records; {len(failures)} missing or failed.")
    if failures:
        raise ValueError("Incomplete run. See failures.json and resume the structure stage.")


def validate(args):
    """Check ids, schema, evidence quotes and review flags across the exported files; write validation.json."""
    from jsonschema import validate as validate_schema
    from biography_schema import RESPONSE_FORMAT, model_input, needs_review
    entries = read_json(args.output / "entries.json")
    records = read_json(args.output / "biographies.json")
    entry_ids = [e["id"] for e in entries]
    result_ids = [r["id"] for r in records]
    if len(set(entry_ids)) != len(entry_ids) or len(set(result_ids)) != len(result_ids):
        raise ValueError("Duplicate entry or result IDs.")
    if set(entry_ids) != set(result_ids):
        raise ValueError("Input and result IDs do not match.")
    sources = {entry["id"]: entry for entry in entries}
    for record in records:
        validate_schema(record["data"], RESPONSE_FORMAT["schema"])
        source = sources[record["id"]]
        if any(record.get(key) != value for key, value in source.items()):
            raise ValueError(f"Exported source fields changed for {record['id']}.")
        problems = evidence_issues(record["data"], model_input(source))
        expected = {"evidence_issues": problems, "needs_review": needs_review(source, record["data"], problems)}
        if record["validation"] != expected:
            raise ValueError(f"Review flags are inconsistent for {record['id']}.")
    with (args.output / "biographies.csv").open(encoding="utf-8-sig", newline="") as handle:
        csv_ids = [r["id"] for r in csv.DictReader(handle)]
    if csv_ids != result_ids:
        raise ValueError("CSV and JSON records do not match.")
    report = {"entries": len(entries), "structured_records": len(records), "csv_rows": len(csv_ids),
              "source_incomplete": [r["id"] for r in records if r["source_incomplete"]],
              "needs_review": [r["id"] for r in records if r["validation"]["needs_review"]],
              "evidence_issue_count": sum(len(r["validation"]["evidence_issues"]) for r in records),
              "structural_checks_passed": True,
              "note": "Structural checks and evidence matching do not establish factual accuracy. Compare with scans."}
    write_json(args.output / "validation.json", report)
    print(json.dumps(report, indent=2))


def run(args):
    """Run ocr, extract, structure, export and validate in sequence."""
    ocr(args)
    extract(args)
    structure(args)
    export(args)
    validate(args)


# -------------------------------------------------------------------- command line
def parser():
    """Command-line interface: one sub-command per stage, with defaults from book_settings.py."""
    main = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = main.add_subparsers(dest="command", required=True)
    for name, function in [("sample", sample), ("ocr", ocr), ("extract", extract),
                           ("structure", structure), ("export", export), ("validate", validate), ("run", run)]:
        sub = commands.add_parser(name, help=(function.__doc__ or f"Run the {name} stage.").split("\n")[0])
        sub.set_defaults(function=function)
        sub.add_argument("--output", type=Path, default=OUTPUT, help="Working output directory.")
        if name in {"sample", "ocr", "extract", "run"}:
            sub.add_argument("--pdf", type=Path, default=SAMPLE, help="Scanned sample PDF.")
            sub.add_argument("--source", type=Path, default=SOURCE, help="Source manifest JSON.")
        if name == "sample":
            sub.add_argument("--input", type=Path, required=True, help="Full scanned PDF to cut pages from.")
            sub.add_argument("--first", type=int, default=4, help="First PDF page to keep (one-based).")
            sub.add_argument("--last", type=int, default=6, help="Last PDF page to keep (inclusive).")
            sub.add_argument("--printed-first", type=int, default=19, help="Page number printed on the first kept page.")
            sub.add_argument("--source-id", default=book.SOURCE_ID)
        if name in {"ocr", "run"}:
            sub.add_argument("--languages", default=book.OCR_LANGUAGES, help="Tesseract languages, e.g. eng+fra.")
            sub.add_argument("--jobs", type=int, default=2, help="OCR worker processes; 0 uses every core.")
            sub.add_argument("--skip-text", action="store_true", help="Keep pages that already have a text layer.")
        if name in {"structure", "run"}:
            sub.add_argument("--model", default=book.MODEL)
            sub.add_argument("--reasoning", choices=["none", "minimal", "low", "medium", "high"], default=book.REASONING,
                             help='Reasoning effort; "none" for models without reasoning.')
            sub.add_argument("--max-output-tokens", type=int, default=book.MAX_OUTPUT_TOKENS)
            sub.add_argument("--workers", type=int, default=1, help="Concurrent API requests (default: 1).")
            sub.add_argument("--max-retries", type=int, default=3, help="SDK retries per request on transient errors.")
            sub.add_argument("--env-file", type=Path, default=ROOT / ".env")
            sub.set_defaults(limit=None, dry_run=False)
        if name == "structure":
            sub.add_argument("--limit", type=int, help="Process only the first N entries (smoke test).")
            sub.add_argument("--dry-run", action="store_true",
                             help="Show pending requests without loading a key or calling the API.")
    return main


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    try:
        if getattr(args, "limit", None) is not None and args.limit < 1:
            raise ValueError("--limit must be positive.")
        if getattr(args, "workers", 1) < 1 or getattr(args, "max_output_tokens", 1) < 1:
            raise ValueError("--workers and --max-output-tokens must be positive.")
        if getattr(args, "max_retries", 0) < 0 or getattr(args, "jobs", 0) < 0:
            raise ValueError("--max-retries and --jobs cannot be negative.")
        args.function(args)
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
