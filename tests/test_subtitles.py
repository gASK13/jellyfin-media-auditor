from pathlib import Path
from app.subtitles.files import find_local_subtitle
from app.subtitles.search import SubtitleCandidate, choose_candidate
from app.media.ffprobe import SubtitleStream
from app.media.language import normalize_language

def test_finds_czech_alias_sidecar(tmp_path: Path):
    media=tmp_path / "Film.mkv"; media.touch(); (tmp_path / "Film.cze.srt").write_text("1")
    assert find_local_subtitle(media, "cs") == tmp_path / "Film.cze.srt"

def test_ranking_prefers_identity_over_rating():
    exact=SubtitleCandidate(1, "cs", imdb_match=True, rating=1)
    popular=SubtitleCandidate(2, "cs", rating=10, downloads=10000)
    assert choose_candidate([popular, exact]) == exact

def test_embedded_subtitle_language_normalizes_like_sidecars():
    stream = SubtitleStream(index=4, codec="subrip", language="ces", title=None, is_default=False, is_forced=False)
    assert normalize_language(stream.language) == "cs"
