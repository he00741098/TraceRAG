"""
Source-code verifier for TraceRAG reports.

After the pipeline generates APK_Report.txt, this module greps the
original JSONL source for every class path and API call claimed in the
report.  It produces a verification.txt file that flags any claim that
cannot be matched in the source code — these are either hallucinations
or cross-contamination from another APK.

Usage (standalone):
    python -m src.verify_report output/MyApp  path/to/source.jsonl

Usage (integrated):
    from src.verify_report import verify_report
    verify_report(report_path, jsonl_path, output_dir)
"""
import os
import re
import json
from pathlib import Path


def _extract_claims(report_text: str) -> dict:
    """Extract class paths and API calls from a TraceRAG report."""
    claims = {"classes": [], "apis": []}

    # Fully-qualified class paths: com.googleapi.cover.MessageReceiver
    # Matches patterns like `com.xxx.yyy.Zzz` including when backtick-quoted
    class_pattern = re.compile(
        r'`?([a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,}(\.[A-Z][a-zA-Z0-9_]*)+)`?'
    )
    seen = set()
    for m in class_pattern.finditer(report_text):
        fqcn = m.group(1)
        if fqcn not in seen and not fqcn.startswith(("android.", "java.", "javax.")):
            seen.add(fqcn)
            claims["classes"].append(fqcn)

    # Android API calls: TelephonyManager.getDeviceId, SmsManager.sendTextMessage
    api_pattern = re.compile(
        r'\b([A-Z][a-zA-Z0-9_]*\.[a-z][a-zA-Z0-9_]*\(\))'
    )
    for m in api_pattern.finditer(report_text):
        api = m.group(1)
        if api not in seen:
            seen.add(api)
            claims["apis"].append(api)

    return claims


def _class_to_path(fqcn: str) -> str:
    """com.googleapi.cover.MessageReceiver → com/googleapi/cover/MessageReceiver"""
    return fqcn.replace(".", "/")


def verify_report(report_path: str, jsonl_path: str, output_dir: str) -> dict:
    """Verify claims in a TraceRAG report against source JSONL.

    Args:
        report_path: Path to APK_Report.txt
        jsonl_path: Path to the source .jsonl file
        output_dir: Directory for verification.txt

    Returns:
        dict with 'verified', 'unverified', 'hallucinated' counts
    """
    with open(report_path, "r", encoding="utf-8") as f:
        report_text = f.read()

    claims = _extract_claims(report_text)

    # Build an index of the JSONL source (class paths → line count)
    # so we only read the file once
    source_index = {}          # path → count
    source_fulltext = ""
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                rel = entry.get("rel_path", "")
                code = entry.get("code", "")
                source_fulltext += code
                # Normalize: strip SHA prefix if present
                parts = rel.split("/sources/", 1)
                path = parts[1] if len(parts) == 2 else rel
                # Store just the class directory path (strip method name)
                class_dir = "/".join(path.split("/")[:-1]) if "/" in path else path
                source_index[class_dir] = source_index.get(class_dir, 0) + 1
            except (json.JSONDecodeError, KeyError):
                continue

    lines = []
    stats = {"verified": 0, "unverified": 0, "total": 0}

    lines.append("=" * 60)
    lines.append(f"TraceRAG Report Verification")
    lines.append(f"Report: {report_path}")
    lines.append(f"Source: {jsonl_path}")
    lines.append("=" * 60)
    lines.append("")

    # Check class paths
    lines.append("── Class Path Verification ──")
    for fqcn in claims["classes"]:
        stats["total"] += 1
        path = _class_to_path(fqcn)
        # Check if this path appears in the source index
        found_in = []
        for src_path, count in source_index.items():
            if path in src_path or src_path.endswith(path):
                found_in.append(f"{src_path} ({count} entries)")

        if found_in:
            lines.append(f"  ✅ {fqcn}")
            for f in found_in[:2]:  # Show at most 2 matches
                lines.append(f"      → {f}")
            stats["verified"] += 1
        else:
            lines.append(f"  ⚠️  {fqcn} — NOT FOUND in source")
            stats["unverified"] += 1

    lines.append("")

    # Check API calls
    lines.append("── API Call Verification ──")
    for api in claims["apis"]:
        stats["total"] += 1
        count = source_fulltext.count(api)
        if count > 0:
            lines.append(f"  ✅ {api} — found ({count} occurrences)")
            stats["verified"] += 1
        else:
            lines.append(f"  🚩 {api} — NOT FOUND in source")
            stats["unverified"] += 1

    lines.append("")
    lines.append("=" * 60)
    lines.append(f"Summary: {stats['verified']}/{stats['total']} claims verified "
                 f"({stats['unverified']} unverified)")
    if stats["unverified"] > 0:
        lines.append("⚠️  Unverified claims may indicate hallucination or cross-contamination")
    else:
        lines.append("✅ All claims verified against source code")
    lines.append("=" * 60)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "verification.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n[Verification] {stats['verified']}/{stats['total']} claims verified → {out_path}")
    return stats
