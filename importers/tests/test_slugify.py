from iol_importers.slugify import slugify


def test_basic_lowercasing_and_spaces():
    assert slugify("Cape Town") == "cape-town"


def test_folds_extension_into_one_slug():
    assert slugify("Aberdeen Lotusville") == "aberdeen-lotusville"


def test_strips_accents_to_ascii():
    assert slugify("Kwazulu-Natál") == "kwazulu-natal"


def test_collapses_punctuation_and_trims_dashes():
    assert slugify("  St. George's / East  ") == "st-george-s-east"
