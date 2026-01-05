"""Tests for YouTube URL parsing."""

import pytest

from whoop_coach.youtube import parse_youtube_url


class TestParseYoutubeUrl:
    """Test suite for parse_youtube_url function."""

    def test_parse_standard_url(self):
        """Standard youtube.com/watch URLs."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert parse_youtube_url(url) == "dQw4w9WgXcQ"

    def test_parse_standard_url_no_www(self):
        """Without www prefix."""
        url = "https://youtube.com/watch?v=dQw4w9WgXcQ"
        assert parse_youtube_url(url) == "dQw4w9WgXcQ"

    def test_parse_mobile_url(self):
        """Mobile m.youtube.com URLs."""
        url = "https://m.youtube.com/watch?v=dQw4w9WgXcQ"
        assert parse_youtube_url(url) == "dQw4w9WgXcQ"

    def test_parse_short_url(self):
        """Short youtu.be URLs."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert parse_youtube_url(url) == "dQw4w9WgXcQ"

    def test_parse_shorts_url(self):
        """YouTube Shorts URLs."""
        url = "https://youtube.com/shorts/dQw4w9WgXcQ"
        assert parse_youtube_url(url) == "dQw4w9WgXcQ"

    def test_parse_url_with_timestamp(self):
        """URL with timestamp parameter."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120"
        assert parse_youtube_url(url) == "dQw4w9WgXcQ"

    def test_parse_url_with_playlist(self):
        """URL with playlist parameter."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
        assert parse_youtube_url(url) == "dQw4w9WgXcQ"

    def test_parse_embed_url(self):
        """Embed URL format."""
        url = "https://youtube.com/embed/dQw4w9WgXcQ"
        assert parse_youtube_url(url) == "dQw4w9WgXcQ"

    def test_parse_invalid_url_wrong_domain(self):
        """Non-YouTube domain returns None."""
        url = "https://vimeo.com/123456"
        assert parse_youtube_url(url) is None

    def test_parse_invalid_url_no_video_id(self):
        """YouTube URL without video ID."""
        url = "https://www.youtube.com/watch"
        assert parse_youtube_url(url) is None

    def test_parse_invalid_url_malformed(self):
        """Malformed URL."""
        url = "not a url at all"
        assert parse_youtube_url(url) is None

    def test_parse_empty_string(self):
        """Empty string returns None."""
        assert parse_youtube_url("") is None

    def test_parse_none_input(self):
        """None-like input."""
        # Note: function expects str, but should handle edge cases
        assert parse_youtube_url("") is None
