"""T25: the MCA PDF converter's layout rules, on synthetic layout-mode lines."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "convert_mca_standard", Path(__file__).resolve().parents[1] / "scripts" / "convert_mca_standard.py")
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)


def test_footnotes_are_the_bottom_run_of_column_zero_lines():
    lines = [
        "5       1When another Standard deals with a specific type of provision,",
        "        contingent liability or contingent asset.",
        "6       3Omitted",
        "1Substituted vide Notification No. G.S.R. 365(E)",
        "thereafter, substituted vide Notification No. G.S.R. 310(E).",
        "* Refer Appendix 1",
        "3Refer Appendix 1.",
    ]
    assert cm._footnote_start(lines) == 3
    assert cm._footnote_start(lines[:3]) == 3  # no footnotes on the page


def test_paragraph_numbers_with_glued_footnote_markers():
    marks = {"7", "10", "11", "13"}
    assert cm._paragraph("75       7A management or board decision", marks) == ("75", "A management or board decision")
    assert cm._paragraph("10110  Omitted*", marks) == ("101", "Omitted*")
    assert cm._paragraph("103    11[Refer Appendix 1]", marks) == ("103", "[Refer Appendix 1]")
    assert cm._paragraph("105 13Onerous Contracts, added paragraphs 68A", marks) == ("105", "Onerous Contracts, added paragraphs 68A")
    assert cm._paragraph("68A     The cost of fulfilling a contract", set()) == ("68A", "The cost of fulfilling a contract")
    assert cm._paragraph("        continuation line", marks) is None


def test_inline_markers_are_removed_but_paragraph_references_kept():
    marks = {"1", "2", "4", "8", "*"}
    assert cm._strip_markers("(c) 2leases (see Ind AS 116)", marks) == "(c) leases (see Ind AS 116)"
    assert cm._strip_markers("of this Standard,4 an outflow", marks) == "of this Standard, an outflow"
    assert cm._strip_markers("(a) Omitted*;", marks) == "(a) Omitted;"
    assert cm._strip_markers("added paragraph 68A and amended paragraph 69", marks) == "added paragraph 68A and amended paragraph 69"
