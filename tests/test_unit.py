"""Unit tests: no Postgres or Redis needed."""

import string

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.schemas import LinkCreate, LinkOut
from app.services.shortcode import ALPHABET, CODE_LENGTH, RESERVED, generate_code


class TestShortcode:
    def test_default_length_and_alphabet(self):
        code = generate_code()
        assert len(code) == CODE_LENGTH
        assert set(code) <= set(string.ascii_letters + string.digits)

    def test_custom_length(self):
        assert len(generate_code(12)) == 12

    def test_codes_are_random(self):
        codes = {generate_code() for _ in range(500)}
        assert len(codes) == 500

    def test_alphabet_is_base62(self):
        assert len(ALPHABET) == 62

    @pytest.mark.parametrize("path", ["api", "docs", "redoc", "openapi.json"])
    def test_app_paths_are_reserved(self, path):
        assert path in RESERVED


class TestConfig:
    def make(self, **kwargs) -> Settings:
        return Settings(_env_file=None, **kwargs)

    def test_database_url_from_parts(self):
        s = self.make(
            postgres_host="db.local", postgres_port=6543, postgres_user="app",
            postgres_password="secret", postgres_db="links",
        )
        url = s.database_url
        assert url.drivername == "postgresql+asyncpg"
        assert (url.host, url.port, url.username, url.database) == ("db.local", 6543, "app", "links")
        assert url.password == "secret"

    def test_database_url_escapes_special_characters_in_password(self):
        s = self.make(postgres_user="app", postgres_password="p@ss:w/rd#1")
        rendered = s.database_url.render_as_string(hide_password=False)
        assert "p%40ss%3Aw%2Frd%231@" in rendered
        assert s.database_url.password == "p@ss:w/rd#1"

    def test_database_url_without_password(self):
        s = self.make(postgres_user="app", postgres_password="")
        assert s.database_url.password is None
        assert "app@" in s.database_url.render_as_string(hide_password=False)

    def test_redis_url_from_parts(self):
        assert self.make(redis_host="cache", redis_port=6380).redis_url == "redis://cache:6380"

    def test_cors_origins_are_split_and_trimmed(self):
        s = self.make(cors_origins=" http://a.test , http://b.test,, ")
        assert s.cors_origin_list == ["http://a.test", "http://b.test"]


class TestSchemas:
    def test_valid_payload(self):
        body = LinkCreate(url="https://example.com/x", custom_alias="my_alias-1", expires_in_days=30)
        assert str(body.url) == "https://example.com/x"

    @pytest.mark.parametrize("url", ["not a url", "example.com", "ftp//broken", ""])
    def test_rejects_invalid_urls(self, url):
        with pytest.raises(ValidationError):
            LinkCreate(url=url)

    @pytest.mark.parametrize("alias", ["ab", "x" * 33, "has space", "slash/es", "emoji🙂"])
    def test_rejects_invalid_aliases(self, alias):
        with pytest.raises(ValidationError):
            LinkCreate(url="https://example.com", custom_alias=alias)

    @pytest.mark.parametrize("days", [0, -1, 366])
    def test_rejects_out_of_range_expiry(self, days):
        with pytest.raises(ValidationError):
            LinkCreate(url="https://example.com", expires_in_days=days)

    def test_short_url_uses_base_url(self):
        out = LinkOut(
            code="abc1234", target_url="https://example.com", created_at="2026-01-01T00:00:00Z",
            expires_at=None, clicks=0, last_clicked_at=None,
        )
        expected = f"{get_settings().base_url.rstrip('/')}/abc1234"
        assert out.short_url == expected
        assert out.model_dump()["short_url"] == expected
