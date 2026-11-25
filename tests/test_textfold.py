"""Accent- and case-insensitive folding used for search."""

from __future__ import annotations

import pytest

from explorer.textfold import fold


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Halász", "halasz"),
        ("HALÁSZ", "halasz"),
        ("Candès", "candes"),
        ("Mendes Júnior", "mendes junior"),
        ("Sünderhauf", "sunderhauf"),
        ("Günther", "gunther"),
        ("Gonçalves", "goncalves"),
        ("Ångström", "angstrom"),
        ("Łukasz Øster", "lukasz oster"),
        ("Đorđe", "dorde"),
        ("Straße", "strasse"),
        ("Œuvre Æther", "oeuvre aether"),
        ("Plain ASCII", "plain ascii"),
        ("", ""),
    ],
)
def test_fold_removes_accents_and_case(raw: str, expected: str) -> None:
    assert fold(raw) == expected


def test_fold_treats_dashes_and_separators_as_spaces() -> None:
    assert fold("Time–Frequency") == fold("time-frequency") == "time frequency"
    assert fold("a—b") == fold("a−b") == fold("a-b") == "a b"
    assert fold("Bendale, Boult") == "bendale boult"
    assert fold("prototype-guided (OSR + NCD)") == "prototype guided osr + ncd"
    assert fold("k_means/knn;lof:x") == "k means knn lof x"


def test_fold_keeps_apostrophes_and_dots_inside_words() -> None:
    assert fold("Don’t") == "don't"
    assert fold("et al. v2.0") == "et al. v2.0"


def test_fold_collapses_whitespace() -> None:
    assert fold("  Open \t Set\nRecognition  ") == "open set recognition"


def test_fold_maps_micro_sign_and_greek_mu_together() -> None:
    assert fold("µ") == fold("μ")


def test_fold_is_idempotent() -> None:
    sample = "Halász – Łukasz’s Æther  Straße"
    assert fold(fold(sample)) == fold(sample)


def test_fold_rejects_non_text() -> None:
    with pytest.raises(TypeError):
        fold(None)  # type: ignore[arg-type]
