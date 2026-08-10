from app.media.language import aggregate_detections, audio_tags, normalize_language, required_subtitle_languages

def test_normalizes_language_aliases_and_rejects_unknowns():
    assert normalize_language("eng") == "en"
    assert normalize_language("cze") == "cs"
    assert normalize_language("und") is None
    assert normalize_language("") is None

def test_aggregates_confident_consistent_samples():
    result=aggregate_detections([("eng", .98), ("en", .93), ("eng", .95)], .75)
    assert result.language == "en"
    assert result.confidence > .9

def test_conflicting_samples_are_unsure():
    assert aggregate_detections([("en", .99), ("cs", .99)], .75).language is None

def test_low_confidence_samples_are_unsure():
    assert aggregate_detections([("en", .45), ("en", .50)], .75).language is None

def test_tag_and_subtitle_rules():
    assert audio_tags(["eng", "ces", "deu"]) == {"CZ Audio", "EN Audio", "OTHER Audio"}
    assert required_subtitle_languages(["cs"]) == {"cs"}
    assert required_subtitle_languages(["en", "de"]) == {"cs", "en"}
    assert audio_tags(["cs", "en", "sk"]) == {"CZ Audio", "EN Audio", "OTHER Audio"}
