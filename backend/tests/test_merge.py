from dropfinder.chunker import sample_times
from dropfinder.export import fmt_time, tracklist_text
from dropfinder.identify import SampleResult
from dropfinder.merge import merge_samples, track_key
from dropfinder.recognizers import Match

IV = 45.0
LEN = 12.0


def seq(*labels, offsets=None):
    """labels: 'A', 'B', None... one per sample, IV seconds apart."""
    out = []
    for i, l in enumerate(labels):
        m = None
        if l:
            off = offsets[i] if offsets else None
            m = Match(title=f"Song {l}", artist=f"Artist {l}", isrc=f"ISRC{l}", offset_in_track=off)
        out.append(SampleResult(time=i * IV, match=m))
    return out


def names(entries):
    return [e.title or "ID" for e in entries]


def merge(samples, **kw):
    return merge_samples(samples, sample_len=LEN, duration=len(samples) * IV, **kw)


def test_consecutive_hits_collapse():
    e = merge(seq("A", "A", "A", "B", "B"))
    assert names(e) == ["Song A", "Song B"]
    assert e[0].start == 0 and e[0].end == e[1].start == 3 * IV
    assert e[0].hits == 3 and not e[0].uncertain


def test_single_missed_sample_inside_track_is_absorbed():
    assert names(merge(seq("A", None, "A", "B", "B"))) == ["Song A", "Song B"]


def test_single_misidentified_sample_inside_track_is_absorbed():
    assert names(merge(seq("A", "A", "X", "A", "B", "B"))) == ["Song A", "Song B"]


def test_long_gap_becomes_unknown():
    e = merge(seq("A", "A", None, None, None, "B", "B"))
    assert names(e) == ["Song A", "ID", "Song B"]
    assert e[1].unknown and e[1].start == 2 * IV


def test_short_gap_between_different_tracks_is_transition():
    assert names(merge(seq("A", "A", None, "B", "B"))) == ["Song A", "Song B"]


def test_isolated_single_hit_flagged_uncertain():
    e = merge(seq("A", "A", None, None, "C", None, None, "B", "B"))
    c = [x for x in e if x.title == "Song C"][0]
    assert c.uncertain


def test_offset_refines_start_but_is_clamped():
    # B first heard at 3*IV=135s, 30s into the track -> started ~105s,
    # which is after A's last sample (90s) + LEN (12s) = 102s, so 105 is allowed.
    s = seq("A", "A", "A", "B", "B", offsets=[None, None, None, 30.0, 75.0])
    e = merge(s)
    assert e[1].start == 105.0
    assert e[0].end == 105.0
    # Huge offset can't push B's start back before A's last confirmed hit.
    s = seq("A", "A", "A", "B", offsets=[None, None, None, 400.0])
    assert merge(s)[1].start == 2 * IV + LEN


def test_track_key_ignores_version_noise_but_not_remixes():
    a = Match(title="Strobe (Original Mix)", artist="deadmau5")
    b = Match(title="Strobe", artist="Deadmau5")
    c = Match(title="Strobe (Some Remix)", artist="deadmau5")
    d = Match(title="Song feat. Someone", artist="X & Y")
    e = Match(title="Song", artist="X")
    assert track_key(a) == track_key(b)
    assert track_key(a) != track_key(c)
    assert track_key(d) == track_key(e)


def test_sample_times():
    assert sample_times(10, 45, 12) == [0.0]
    assert sample_times(100, 45, 12) == [0.0, 45.0, 88.0]
    assert sample_times(0, 45, 12) == []


def test_text_export():
    e = merge(seq("A", "A", None, None, "B"))
    txt = tracklist_text(e, "My Set", "https://youtu.be/x")
    assert "01. [00:00] Artist A - Song A" in txt
    assert "02. [01:30] ID - ID" in txt
    assert "03. [03:00] Artist B - Song B (?)" in txt
    assert "Tracklist by DropFinder" in txt
    assert fmt_time(3725) == "1:02:05"
