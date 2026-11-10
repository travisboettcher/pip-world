#!/usr/bin/env python3
"""Turn a pytest JUnit report's failures into GitHub workflow annotations (`::error`), so which test failed, and why, is visible
on the run's summary page and through the public API, without opening the log. Used by the CI workflows when the tests fail.

Usage: annotate_failures.py junit.xml
"""
import sys
import xml.etree.ElementTree as ET


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotations(path: str) -> list[str]:
    out = []
    for case in ET.parse(path).getroot().iter("testcase"):
        for bad in [*case.findall("failure"), *case.findall("error")]:
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            text = (bad.text or "").strip().splitlines()
            msg = (bad.get("message") or (text[-1] if text else ""))[:800]
            out.append(f"::error title={escape('Test failed: ' + name)}::{escape(msg)}")
    return out


if __name__ == "__main__":
    lines = annotations(sys.argv[1])
    print("\n".join(lines) if lines else "no failures in the report")
