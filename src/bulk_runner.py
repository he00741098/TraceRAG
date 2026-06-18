"""
Bulk runner for TraceRAG — processes multiple APKs in parallel.

Usage:
    python -m src.bulk_runner <directory_of_jsonl> [--workers N]

Each JSONL file in the directory is processed independently.  Output goes
to ``output/<sha256>/`` so runs never collide.

Requirements:
    - llama-server (or equivalent) with ``-np`` >= --workers
    - Qdrant running with enough memory for N concurrent collections
"""
import os
import sys
import argparse
import time
import subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed


def _run_single(jsonl_file: str, workers: int) -> dict:
    """Run the pipeline on a single JSONL file and return timing stats."""
    sha = Path(jsonl_file).stem.upper()
    start = time.time()

    # Each run gets its own Qdrant collection (SHA-based) so parallel
    # runs never read each other's data.
    cmd = [
        sys.executable, "-m", "src.jsonl_pipeline",
        jsonl_file,
        sha,                    # collection name = SHA256
        "--output-dir", f"output/{sha}",
        "--resume",             # bulk runs are long; allow resume
    ]

    print(f"\n{'='*60}")
    print(f"[Bulk] Starting {sha}  →  collection={sha}  output=output/{sha}/")
    print(f"{'='*60}")

    proc = subprocess.run(cmd, capture_output=False)  # stream to terminal
    elapsed = time.time() - start
    ok = proc.returncode == 0

    print(f"[Bulk] {sha}  {'DONE' if ok else 'FAILED (code=' + str(proc.returncode) + ')'}  in {elapsed:.0f}s")

    return {"sha": sha, "ok": ok, "elapsed_s": round(elapsed, 1)}


def main():
    parser = argparse.ArgumentParser(description="Run TraceRAG on multiple JSONL files in parallel.")
    parser.add_argument("directory", type=str,
                        help="Directory containing .jsonl files to process.")
    parser.add_argument("--workers", type=int, default=2,
                        help="Max parallel pipeline runs (default: 2).")
    parser.add_argument("--pattern", type=str, default="*.jsonl",
                        help="Glob pattern for files (default: *.jsonl).")
    args = parser.parse_args()

    jsonl_dir = Path(args.directory)
    if not jsonl_dir.is_dir():
        print(f"[Error] {jsonl_dir} is not a directory")
        sys.exit(1)

    files = sorted(jsonl_dir.glob(args.pattern))
    if not files:
        print(f"[Error] No files matching '{args.pattern}' in {jsonl_dir}")
        sys.exit(1)

    print(f"[Bulk] Found {len(files)} file(s). Running with {args.workers} worker(s).")
    print(f"[Bulk] Output will be in output/<sha256>/ for each file.\n")

    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_run_single, str(f), args.workers): f for f in files}
        for future in as_completed(futures):
            results.append(future.result())

    # Summary
    ok = sum(1 for r in results if r["ok"])
    fail = len(results) - ok
    total_s = time.time() - t0
    print(f"\n{'='*60}")
    print(f"[Bulk] COMPLETE  — {ok} ok, {fail} failed, {len(results)} total")
    print(f"[Bulk] Wall-clock: {total_s:.0f}s ({total_s/60:.1f} min)")
    for r in results:
        status = "OK" if r["ok"] else "FAIL"
        print(f"  {r['sha'][:16]:>16}…  {status:>4}  {r['elapsed_s']:>8.0f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
