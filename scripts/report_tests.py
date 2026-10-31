"""Publish aggregate JUnit diagnostics without captured data or parameter values."""

import argparse
import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree as ET


def safe_case_name(value: str) -> str:
    """Keep test identity while hiding potentially sensitive parameter contents."""
    base, _, parameters = value.partition("[")
    safe = re.sub(r"[^A-Za-z0-9_.]", "_", base)[:200]
    if parameters:
        safe += "[case-" + hashlib.sha256(parameters.encode()).hexdigest()[:10] + "]"
    return safe


def publish_report(source: Path, sanitized: Path, summary: Path) -> None:
    """Retain counts, status and timings; keep raw failure details in CI console."""
    root = ET.parse(source).getroot()
    suites = list(root.iter("testsuite"))
    cases = list(root.iter("testcase"))
    totals = {name: 0 for name in ("passed", "failed", "errors", "skipped")}
    output = ET.Element("testsuite", name="pytest")
    timings = []
    failures = []
    for case in cases:
        name = safe_case_name(case.get("name", "unknown"))
        classname = safe_case_name(case.get("classname", "unknown"))
        seconds = max(0.0, float(case.get("time", "0")))
        clean = ET.SubElement(
            output, "testcase", name=name, classname=classname, time=str(seconds)
        )
        status = "passed"
        for tag, outcome in (
            ("failure", "failed"),
            ("error", "errors"),
            ("skipped", "skipped"),
        ):
            if case.find(tag) is not None:
                status = outcome
                ET.SubElement(
                    clean, tag, message="Details omitted from artifact; see CI console."
                )
                if tag != "skipped":
                    failures.append(f"{classname}::{name} ({outcome})")
                break
        totals[status] += 1
        timings.append((seconds, f"{classname}::{name}"))
    duration = sum(float(suite.get("time", "0")) for suite in suites)
    output.attrib.update(
        tests=str(len(cases)),
        failures=str(totals["failed"]),
        errors=str(totals["errors"]),
        skipped=str(totals["skipped"]),
        time=str(duration),
    )
    sanitized.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(output).write(sanitized, encoding="utf-8", xml_declaration=True)
    lines = [
        "### Pytest results",
        "",
        f"Tests: {len(cases)} · passed: {totals['passed']} · failed: {totals['failed']} · errors: {totals['errors']} · skipped: {totals['skipped']} · duration: {duration:.2f} s",
        "",
        "Slowest test cases (including fixture time):",
        "",
        "| Seconds | Test |",
        "|---:|---|",
    ]
    lines.extend(
        f"| {seconds:.3f} | `{name}` |"
        for seconds, name in sorted(timings, reverse=True)[:20]
    )
    if failures:
        lines += ["", "Failed cases:", ""] + [f"- `{name}`" for name in failures]
    summary.parent.mkdir(parents=True, exist_ok=True)
    with summary.open("a", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("sanitized", type=Path)
    parser.add_argument("summary", type=Path)
    args = parser.parse_args()
    publish_report(args.source, args.sanitized, args.summary)


if __name__ == "__main__":
    main()
