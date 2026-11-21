#!/usr/bin/env python3
"""Unit tests for the name normaliser. No data files required."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import normalize
from engine import multilingual_relation, names_agree, parts_match


def parts(value):
    return normalize.normalize_parts(value)


def test_fold_strips_accents_and_case():
    assert normalize.fold_name("Müller") == "muller"
    assert normalize.fold_name("JOSÉ") == "jose"
    assert "ﬁ" not in normalize.fold_name("ﬁ")  # NFKC splits the ligature


def test_cyrillic_transliterates_and_ignores_order():
    left = parts("Алексей Иванов")
    right = parts("Ivanov Aleksei")
    assert "aleksei" in left and "ivanov" in left
    assert names_agree(left, right)


def test_greek_transliterates():
    assert "alexandros" in parts("Αλέξανδρος") or names_agree(parts("Αλέξανδρος"), parts("Alexandros"))


def test_arabic_skeleton_matches_muhammad():
    assert parts_match("mhmd", "muhammad") or names_agree(parts("محمد"), parts("Muhammad"))
    assert names_agree(parts("محمد"), parts("Mohammed"))


def test_spelling_variants():
    assert names_agree(parts("Mohammed Ali"), parts("Muhammad Ali"))
    assert names_agree(parts("Mohamad"), parts("Muhammad"))
    assert names_agree(parts("Youssef"), parts("Yusuf"))
    assert names_agree(parts("Aleksandr"), parts("Alexander"))
    assert names_agree(parts("Alexei"), parts("Aleksei"))


def test_particles_honorifics_and_patronymic():
    assert "al" not in parts("al-Hassan")
    assert "sheikh" not in parts("Sheikh Mohammed")
    assert "van" not in parts("van der Berg") or "der" not in parts("van der Berg")
    assert "bin" not in parts("Abdul Aziz bin Rahman")
    assert "ivanovich" not in parts("Aleksei Ivanovich Petrov")
    assert names_agree(parts("Mr Yusuf al-Hassan"), parts("Youssef Hassan"))


def test_cjk_is_exact_and_not_guessed():
    assert names_agree(parts("梅林"), parts("梅林"))
    assert not names_agree(parts("梅林"), parts("Lin Mei"))
    assert not names_agree(parts("林梅"), parts("梅林"))
    assert names_agree(parts("Lin Mei 梅林"), parts("Mei Lin"))


def test_relation_blocks_a_clear_and_does_not_invent_one():
    agree, uncertain, note = multilingual_relation("Aleksei Ivanov", ["Алексей Иванов"], False)
    assert agree
    assert not uncertain
    assert "Cyrillic" in note and "Алексей" in note
    agree, uncertain, note = multilingual_relation("Amelia Hassan", ["Ahmed Mohamed", "محمد"], False)
    assert not agree
    # A different Arabic name is not turned into a clearance by this helper.
    assert agree is False


def main():
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print("ok", test.__name__)
    print(f"{len(tests)} normaliser tests passed")


if __name__ == "__main__":
    main()
