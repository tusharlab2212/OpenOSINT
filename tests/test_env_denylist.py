"""Files can never set dangerous variables; the real environment is never filtered.

openosint.env._load_file filters what config.env and a legacy .env may set: process
and loader control, traffic interception, Anthropic client redirection,
network-exposure switches and storage locations, matched case-insensitively.
OPENOSINT_ALLOW_ACTIVE is accepted from config.env only (the web UI switch writes it
there). All values here are dummies; nothing touches the network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import openosint.env as env_module

APPROVED_DENIED = {
    "PATH", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "BASH_ENV", "ENV",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE", "SSLKEYLOGFILE",
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_CUSTOM_HEADERS",
    "OPENOSINT_TRUSTED_PROXY", "TRUSTED_PROXY", "OPENOSINT_ALLOW_CLIENT_BACKEND",
    "OPENOSINT_ALLOWED_BASE_URLS", "OPENOSINT_ALLOW_REMOTE", "OPENOSINT_ALLOWED_HOSTS",
    "OPENOSINT_ALLOWED_ORIGINS", "DEMO_ALLOWED_ORIGINS", "OPENOSINT_PUBLISHED_BIND",
    "OPENOSINT_HOME", "OPENOSINT_ENV_FILE", "OPENOSINT_GRAPH_DB",
}  # fmt: skip

EVIL = "dummy-attacker-value.invalid"


def _watched(name: str) -> bool:
    upper = name.upper()
    return (
        upper in env_module._DENIED_FROM_FILES
        or upper.startswith(env_module._DENIED_PREFIXES_FROM_FILES)
        or upper in env_module._CONFIG_ONLY
        or upper in env_module._HOST_NOTICE_NAMES
        or upper.startswith("MARKER_")
        or upper in {"SHODAN_API_KEY", "OPENOSINT_SETUP_TOKEN", "OPENOSINT_MAX_TOOL_CALLS"}
    )


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Snapshot/restore the whole environment (load_env writes os.environ directly),
    clear every name these tests look at, and keep config.env inside tmp_path."""
    saved = dict(os.environ)
    for name in list(os.environ):
        if _watched(name):
            del os.environ[name]
    monkeypatch.setattr(env_module, "_loaded_path", None)
    monkeypatch.setattr(env_module, "_load_attempted", False)
    monkeypatch.setattr(env_module, "_origins", {})
    fake_env_py = tmp_path / "no-repo-root" / "openosint" / "env.py"
    monkeypatch.setattr(env_module, "__file__", str(fake_env_py))
    config_file = tmp_path / "data" / "config.env"
    config_file.parent.mkdir()
    monkeypatch.setattr(env_module, "config_path", lambda: config_file)
    monkeypatch.chdir(tmp_path)
    yield config_file
    os.environ.clear()
    os.environ.update(saved)


def _legacy(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "legacy.env"
    path.write_text(text)
    os.environ["OPENOSINT_ENV_FILE"] = str(path)
    return path


class TestTheList:
    def test_denied_list_is_exactly_the_approved_list(self):
        assert set(env_module._DENIED_FROM_FILES) == APPROVED_DENIED
        assert env_module._DENIED_PREFIXES_FROM_FILES == ("LD_", "DYLD_")
        assert env_module._CONFIG_ONLY == {"OPENOSINT_ALLOW_ACTIVE"}

    @pytest.mark.parametrize(
        ("name", "origin", "denied"),
        [
            ("PATH", "legacy", True),
            ("PATH", "config", True),
            ("path", "legacy", True),
            ("Https_Proxy", "config", True),
            ("ld_preload", "legacy", True),
            ("DYLD_INSERT_LIBRARIES", "config", True),
            ("OPENOSINT_ENV_FILE", "legacy", True),
            ("OPENOSINT_ALLOW_ACTIVE", "config", False),
            ("openosint_allow_active", "config", False),
            ("OPENOSINT_ALLOW_ACTIVE", "legacy", True),
            ("SHODAN_API_KEY", "legacy", False),
            ("OPENOSINT_PROXY_URL", "legacy", False),
            ("OPENAI_BASE_URL", "config", False),
            ("OPENOSINT_SETUP_TOKEN", "legacy", False),
            ("LDAP_SERVER", "legacy", False),  # "LD_" prefix only, not "LD"
        ],
    )
    def test_rules(self, name, origin, denied):
        assert env_module._denied_from_file(name, origin) is denied


class TestLegacyEnvFile:
    # OPENOSINT_ENV_FILE is necessarily set to load the file, so a file can never
    # override it anyway; it is covered by the rule test above.
    @pytest.mark.parametrize(
        "name",
        sorted(APPROVED_DENIED - {"OPENOSINT_ENV_FILE"})
        + ["LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "OPENOSINT_ALLOW_ACTIVE"],
    )
    def test_denied_name_is_not_set_and_is_named_without_its_value(self, tmp_path, name, capsys):
        legacy = _legacy(tmp_path, f"{name}={EVIL}\nMARKER_OK=loaded\n")

        env_module.load_env()

        assert name not in os.environ
        assert os.environ["MARKER_OK"] == "loaded"  # the rest of the file still loads
        err = capsys.readouterr().err
        assert f"Ignored in {legacy}" in err and name in err
        assert EVIL not in err

    @pytest.mark.parametrize(
        "name", ["https_proxy", "Https_Proxy", "path", "ld_preload", "openosint_home",
                 "anthropic_base_url", "Anthropic_Custom_Headers", "openosint_allow_active"]
    )  # fmt: skip
    def test_matching_ignores_letter_case(self, tmp_path, name):
        _legacy(tmp_path, f"{name}={EVIL}\n")

        env_module.load_env()

        assert name not in os.environ

    def test_allowed_names_still_load_with_no_ignored_line(self, tmp_path, capsys):
        _legacy(
            tmp_path,
            "SHODAN_API_KEY=dummy-key\nOPENOSINT_SETUP_TOKEN=dummy-token\n"
            "OPENOSINT_MAX_TOOL_CALLS=7\nMARKER_PLAIN=x\n",
        )

        env_module.load_env()

        assert os.environ["SHODAN_API_KEY"] == "dummy-key"
        assert os.environ["OPENOSINT_SETUP_TOKEN"] == "dummy-token"
        assert os.environ["OPENOSINT_MAX_TOOL_CALLS"] == "7"
        assert env_module.value_source("SHODAN_API_KEY") == "legacy"
        assert "Ignored" not in capsys.readouterr().err


class TestConfigEnv:
    def test_denied_names_are_ignored_from_config_env_too(self, isolated, capsys):
        isolated.write_text(
            f"HTTPS_PROXY={EVIL}\nANTHROPIC_BASE_URL={EVIL}\nOPENOSINT_HOME={EVIL}\n"
        )

        env_module.load_env()

        for name in ("HTTPS_PROXY", "ANTHROPIC_BASE_URL", "OPENOSINT_HOME"):
            assert name not in os.environ
        err = capsys.readouterr().err
        assert f"Ignored in {isolated}" in err and EVIL not in err

    def test_allow_active_from_config_env_is_honoured(self, isolated, capsys):
        isolated.write_text("OPENOSINT_ALLOW_ACTIVE=1\n")

        env_module.load_env()

        assert os.environ["OPENOSINT_ALLOW_ACTIVE"] == "1"
        assert env_module.value_source("OPENOSINT_ALLOW_ACTIVE") == "config"
        assert "Ignored" not in capsys.readouterr().err

    def test_allow_active_from_legacy_env_is_ignored_even_without_config(self, tmp_path, capsys):
        _legacy(tmp_path, "OPENOSINT_ALLOW_ACTIVE=1\n")

        env_module.load_env()

        assert "OPENOSINT_ALLOW_ACTIVE" not in os.environ
        assert "OPENOSINT_ALLOW_ACTIVE" in capsys.readouterr().err


class TestRealEnvironmentIsNeverFiltered:
    def test_real_values_win_silently(self, tmp_path, capsys):
        os.environ["HTTPS_PROXY"] = "http://real-proxy.invalid:3128"
        os.environ["OPENOSINT_ALLOW_ACTIVE"] = "1"
        _legacy(tmp_path, f"HTTPS_PROXY={EVIL}\nOPENOSINT_ALLOW_ACTIVE=0\n")

        env_module.load_env()

        assert os.environ["HTTPS_PROXY"] == "http://real-proxy.invalid:3128"
        assert os.environ["OPENOSINT_ALLOW_ACTIVE"] == "1"
        assert env_module.value_source("HTTPS_PROXY") == "environment"
        assert "Ignored" not in capsys.readouterr().err  # precedence, not filtering


class TestHostOnlyNotices:
    def test_notice_shows_host_only(self, tmp_path, capsys):
        legacy = _legacy(
            tmp_path,
            "OPENOSINT_PROXY_URL=http://someuser:s3cret@proxy.invalid:3128/some/path\n"
            "OPENAI_BASE_URL=https://gateway.invalid/v1?key=abc123\n",
        )

        env_module.load_env()

        assert os.environ["OPENOSINT_PROXY_URL"].startswith("http://someuser:")  # value intact
        err = capsys.readouterr().err
        assert f"[*] OPENOSINT_PROXY_URL set from {legacy} (host: proxy.invalid:3128)" in err
        assert f"[*] OPENAI_BASE_URL set from {legacy} (host: gateway.invalid)" in err
        for secret in ("someuser", "s3cret", "/some/path", "abc123", "/v1"):
            assert secret not in err

    def test_unparseable_value_is_still_loaded_and_reported_as_unrecognised(self, isolated, capsys):
        isolated.write_text("OPENAI_BASE_URL=not a url\n")

        env_module.load_env()

        assert os.environ["OPENAI_BASE_URL"] == "not a url"
        assert "(host: unrecognised)" in capsys.readouterr().err

    def test_no_notice_when_the_real_environment_decides(self, tmp_path, capsys):
        os.environ["OPENOSINT_PROXY_URL"] = "http://real.invalid:1"
        _legacy(tmp_path, "OPENOSINT_PROXY_URL=http://file.invalid:2\n")

        env_module.load_env()

        assert os.environ["OPENOSINT_PROXY_URL"] == "http://real.invalid:1"
        assert "OPENOSINT_PROXY_URL set from" not in capsys.readouterr().err


def test_a_real_cli_process_ignores_denied_names_from_its_env_file(tmp_path):
    """End to end: a fresh process importing the CLI never receives denied names."""
    env_file = tmp_path / "explicit.env"
    env_file.write_text(
        f"HTTPS_PROXY=http://{EVIL}:8080\nANTHROPIC_BASE_URL=https://{EVIL}\n"
        "OPENOSINT_ALLOW_ACTIVE=1\nMARKER_OK=loaded\n"
    )
    names = ("HTTPS_PROXY", "ANTHROPIC_BASE_URL", "OPENOSINT_ALLOW_ACTIVE", "MARKER_OK")
    probe = (
        "import json, os\nimport openosint.cli\n"
        f"print(json.dumps({{k: os.environ.get(k) for k in {names!r}}}))\n"
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin") or "/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "OPENOSINT_HOME": str(tmp_path / "openosint-home"),
        "OPENOSINT_ENV_FILE": str(env_file),
        "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
    }

    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=str(tmp_path), env=env,
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip

    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout.strip().splitlines()[-1])
    assert values == {
        "HTTPS_PROXY": None, "ANTHROPIC_BASE_URL": None,
        "OPENOSINT_ALLOW_ACTIVE": None, "MARKER_OK": "loaded",
    }  # fmt: skip
    assert f"Ignored in {env_file}" in result.stderr
    assert EVIL not in result.stderr
