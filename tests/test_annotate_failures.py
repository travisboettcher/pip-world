"""CI turns failing tests into annotations (scripts/annotate_failures.py), so a failure can be read without the run's log."""
import importlib.util
from pathlib import Path

SCRIPT = next(p / "scripts" / "annotate_failures.py" for p in Path(__file__).resolve().parents if (p / "scripts" / "annotate_failures.py").is_file())
spec = importlib.util.spec_from_file_location("annotate_failures", SCRIPT)
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


def test_each_failure_and_error_becomes_one_annotation(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text('<testsuites><testsuite>'
                   '<testcase classname="tests.test_a" name="test_ok"/>'
                   '<testcase classname="tests.test_a" name="test_bad"><failure message="assert 1 == 2&#10;more">trace</failure></testcase>'
                   '<testcase classname="tests.test_b" name="test_err"><error>line one\nValueError: 100%</error></testcase>'
                   '<testcase classname="tests.test_b" name="test_empty"><failure/></testcase>'
                   '</testsuite></testsuites>')
    assert A.annotations(str(xml)) == ["::error title=Test failed: tests.test_a::test_bad::assert 1 == 2%0Amore",
                                       "::error title=Test failed: tests.test_b::test_err::ValueError: 100%25",
                                       "::error title=Test failed: tests.test_b::test_empty::"]
    assert A.escape("a%b\r\nc") == "a%25b%0D%0Ac"
