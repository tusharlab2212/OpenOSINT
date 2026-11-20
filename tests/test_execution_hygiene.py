"""Batch 2 — execution and local-data hygiene (F6, F7, F8, F9, F11).

Offline: subprocess creation, HTTP and tool handlers are mocked; files go to tmp_path.
The browser key-storage change (F10) is covered by tests/test_settings_key_storage.mjs.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openosint import utils
from openosint.tools.exceptions import ToolExecutionError

POSIX = pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# ---------------------------------------------------------------------------
# F6 — external programs get a minimal environment
# ---------------------------------------------------------------------------


class TestChildEnv:
    BASE = {
        "PATH": "/usr/bin", "HOME": "/home/u", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "TMPDIR": "/tmp", "SYSTEMROOT": r"C:\Windows",
        "HTTPS_PROXY": "http://proxy.invalid:3128", "https_proxy": "http://proxy.invalid:3128",
        "NO_PROXY": "localhost", "SSL_CERT_FILE": "/etc/ssl/ca.pem",
        "ANTHROPIC_API_KEY": "sk-ant-dummy", "SHODAN_API_KEY": "dummy", "GITHUB_TOKEN": "dummy",
        "OPENOSINT_ALLOW_ACTIVE": "1", "PYTHONPATH": "/evil", "PYTHONSTARTUP": "/evil.py",
        "AWS_SECRET_ACCESS_KEY": "dummy", "MY_PRIVATE_THING": "dummy",
    }  # fmt: skip

    def test_keeps_only_what_a_process_needs(self):
        env = utils.child_env(self.BASE)

        for kept in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "HTTPS_PROXY",
                     "https_proxy", "NO_PROXY", "SSL_CERT_FILE"):  # fmt: skip
            assert env[kept] == self.BASE[kept], kept
        for dropped in ("ANTHROPIC_API_KEY", "SHODAN_API_KEY", "GITHUB_TOKEN", "OPENOSINT_ALLOW_ACTIVE",
                        "PYTHONPATH", "PYTHONSTARTUP", "AWS_SECRET_ACCESS_KEY", "MY_PRIVATE_THING"):  # fmt: skip
            assert dropped not in env, dropped

    def test_defaults_to_the_process_environment(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")

        env = utils.child_env()

        assert env["PATH"] == "/usr/bin:/bin" and "ANTHROPIC_API_KEY" not in env

    async def test_run_subprocess_passes_the_filtered_environment(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
        monkeypatch.setenv("VIRUSTOTAL_API_KEY", "dummy")
        proc = MagicMock(returncode=0)
        proc.communicate = AsyncMock(return_value=(b"out", b""))
        monkeypatch.setattr(utils, "find_binary", lambda b: f"/usr/bin/{b}")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as spawn:
            result = await utils.run_subprocess("holehe", ["a@b.c"], timeout_seconds=5)

        env = spawn.call_args.kwargs["env"]
        assert result.stdout == "out"
        assert isinstance(env, dict) and "PATH" in env
        assert "ANTHROPIC_API_KEY" not in env and "VIRUSTOTAL_API_KEY" not in env

    async def test_proxy_mode_still_reaches_the_child(self, monkeypatch):
        """get_subprocess_env() injects the proxy; the filter keeps it, drops the keys."""
        from openosint.tools.search_email import run_email_osint

        monkeypatch.setenv("OPENOSINT_PROXY_URL", "http://proxy.invalid:3128")
        monkeypatch.setenv("HIBP_API_KEY", "dummy")
        proc = MagicMock(returncode=0)
        proc.communicate = AsyncMock(return_value=(b"[+] example.invalid", b""))
        monkeypatch.setattr(utils, "find_binary", lambda b: f"/usr/bin/{b}")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as spawn:
            await run_email_osint("person@example.com", timeout_seconds=5)

        env = spawn.call_args.kwargs["env"]
        assert env["HTTPS_PROXY"] == env["https_proxy"] == "http://proxy.invalid:3128"
        assert "HIBP_API_KEY" not in env and "OPENOSINT_PROXY_URL" not in env


# ---------------------------------------------------------------------------
# F9 — targets cannot be read as program options
# ---------------------------------------------------------------------------


class TestValidateCliTarget:
    @pytest.mark.parametrize(
        "value",
        ["-v", "--output=/tmp/x", "  -x", "-", "", "   ", "a\x00b", "a\nb", "a\tb", "a\x7fb", "a" * 257],
    )
    def test_rejects(self, value):
        with pytest.raises(ToolExecutionError):
            utils.validate_cli_target(value, "username")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("johndoe", "johndoe"), (" a@b.c ", "a@b.c"), ("+14155550100", "+14155550100"),
         ("example.com", "example.com"), ("a-b", "a-b"), ("x" * 256, "x" * 256)],
    )  # fmt: skip
    def test_accepts_and_strips(self, value, expected):
        assert utils.validate_cli_target(value, "username") == expected


TOOLS = [
    ("openosint.tools.search_email", "run_email_osint", "a@b.c", ["a@b.c", "--only-used"]),
    ("openosint.tools.search_username", "run_username_osint", "johndoe", None),
    ("openosint.tools.search_domain", "run_domain_osint", "example.com", ["-d", "example.com", "-n"]),
    ("openosint.tools.search_phone", "run_phone_osint", "+14155550100", ["scan", "-n", "+14155550100"]),
]


class TestToolsValidateBeforeSpawning:
    @pytest.mark.parametrize(("module", "fn", "_ok", "_args"), TOOLS)
    @pytest.mark.parametrize("evil", ["--output=/tmp/pwned", "-h", "  -n"])
    async def test_option_like_target_never_reaches_the_program(self, monkeypatch, module, fn, _ok, _args, evil):
        import importlib

        mod = importlib.import_module(module)
        spawn = AsyncMock()
        monkeypatch.setattr(mod, "run_subprocess", spawn)

        out = await getattr(mod, fn)(evil, timeout_seconds=5)

        spawn.assert_not_called()
        assert out.startswith("Scan error: Refusing")

    @pytest.mark.parametrize(("module", "fn", "ok", "args"), TOOLS)
    async def test_valid_target_keeps_the_same_argument_list(self, monkeypatch, module, fn, ok, args):
        import importlib

        mod = importlib.import_module(module)
        spawn = AsyncMock(return_value=utils.SubprocessResult(stdout="[+] x", stderr="", return_code=0))
        monkeypatch.setattr(mod, "run_subprocess", spawn)

        await getattr(mod, fn)(ok, timeout_seconds=5)

        sent = spawn.call_args.kwargs["args"]
        if args is not None:
            assert sent == args
        else:  # sherlock: username first, then its own flags
            assert sent[0] == ok and "--print-found" in sent


# ---------------------------------------------------------------------------
# F7 — MCP logs carry no investigation targets
# ---------------------------------------------------------------------------


class TestMcpLogging:
    async def test_call_tool_logs_argument_names_not_values(self, caplog):
        from openosint import mcp_server

        handler = AsyncMock(return_value="ok")
        with patch.dict(mcp_server._HANDLERS, {"search_whois": (handler, lambda a: a["domain"])}), \
                caplog.at_level(logging.INFO, logger="openosint.mcp_server"):
            await mcp_server.call_tool("search_whois", {"domain": "secret-target.example"})

        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "Tool: search_whois | arguments: domain" in text
        assert "secret-target" not in text

    def test_filter_drops_tool_logs_below_error(self):
        from openosint.mcp_server import _DropTargetLogs

        f = _DropTargetLogs()

        def rec(name, level):
            return logging.LogRecord(name, level, __file__, 1, "Lookup for %s", ("victim@example.com",), None)

        assert not f.filter(rec("openosint.tools.search_breach", logging.INFO))
        assert not f.filter(rec("openosint.tools.search_rdap", logging.WARNING))
        assert not f.filter(rec("openosint.multi_target", logging.INFO))
        assert not f.filter(rec("openosint.pivot", logging.WARNING))
        assert f.filter(rec("openosint.tools.search_email", logging.ERROR))  # crashes are kept
        assert f.filter(rec("openosint.mcp_server", logging.INFO))  # operational lines kept
        assert f.filter(rec("mcp.server", logging.INFO))

    def test_installed_by_main_only_and_changes_no_logger_level(self, monkeypatch):
        from openosint import mcp_server

        # Compared with the level before main(), not with NOTSET: other modules
        # (cloud/main.py) set this level when they are imported earlier in a test run.
        level_before = logging.getLogger("openosint.tools").level
        root = logging.getLogger()
        handler = logging.StreamHandler()
        root.addHandler(handler)
        try:
            async def noop():
                return None

            monkeypatch.setattr(mcp_server, "_serve", noop)
            monkeypatch.setattr(mcp_server, "set_surface", lambda _s: None)
            mcp_server.main([])
            mcp_server.main([])  # idempotent: one filter, not two

            installed = [f for f in handler.filters if isinstance(f, mcp_server._DropTargetLogs)]
            assert len(installed) == 1
            assert logging.getLogger("openosint.tools").level == level_before
        finally:
            root.removeHandler(handler)
            for h in root.handlers:
                h.filters = [f for f in h.filters if not isinstance(f, mcp_server._DropTargetLogs)]


# ---------------------------------------------------------------------------
# F8 — owner-only history and graph files
# ---------------------------------------------------------------------------


@POSIX
class TestPrivatePaths:
    def test_missing_directories_are_created_owner_only(self, tmp_path):
        from openosint.paths import ensure_private_dir

        target = tmp_path / "home" / "data" / "history"
        ensure_private_dir(target)

        for d in (tmp_path / "home", tmp_path / "home" / "data", target):
            assert _mode(d) == 0o700, d

    def test_existing_directory_keeps_its_mode(self, tmp_path):
        from openosint.paths import ensure_private_dir

        shared = tmp_path / "shared"
        shared.mkdir()
        shared.chmod(0o755)
        ensure_private_dir(shared / "history")

        assert _mode(shared) == 0o755 and _mode(shared / "history") == 0o700

    def test_private_file_created_once_and_existing_left_alone(self, tmp_path):
        from openosint.paths import create_private_file

        new, old = tmp_path / "new.db", tmp_path / "old.db"
        old.write_text("data")
        old.chmod(0o644)

        assert create_private_file(new) is True and _mode(new) == 0o600
        assert create_private_file(old) is False and _mode(old) == 0o644
        assert old.read_text() == "data"  # never truncated

    def test_session_history_is_owner_only(self, tmp_path, monkeypatch):
        from openosint import session_history as sh

        monkeypatch.setattr(sh, "HISTORY_DIR", tmp_path / "home" / "history")
        record = sh.SessionRecord(timestamp="2026-11-20T10:00:00", duration_seconds=1, targets=["t"])

        path = sh.save_session(record)

        assert _mode(tmp_path / "home") == 0o700 and _mode(tmp_path / "home" / "history") == 0o700
        assert _mode(path) == 0o600
        assert sh.load_sessions()[0]["targets"] == ["t"]

    def test_rewriting_an_existing_history_file_keeps_its_mode(self, tmp_path, monkeypatch):
        from openosint import session_history as sh

        hist = tmp_path / "history"
        hist.mkdir()
        monkeypatch.setattr(sh, "HISTORY_DIR", hist)
        existing = hist / "2026-11-20T10-00-00_session.json"
        existing.write_text("{}")
        existing.chmod(0o644)

        sh.save_session(sh.SessionRecord(timestamp="2026-11-20T10:00:00", duration_seconds=1))

        assert _mode(existing) == 0o644 and '"duration_seconds": 1' in existing.read_text()

    def test_graph_db_and_its_directory_are_owner_only(self, tmp_path, monkeypatch):
        from openosint.graph.store.db_path import default_db_path
        from openosint.graph.store.graph_store import GraphStore

        monkeypatch.setenv("OPENOSINT_GRAPH_DB", str(tmp_path / "fresh" / "graph.db"))
        db = default_db_path()
        store = GraphStore(db)
        store.close()

        assert _mode(tmp_path / "fresh") == 0o700 and _mode(db) == 0o600

    def test_existing_graph_db_keeps_its_mode_and_memory_still_works(self, tmp_path):
        from openosint.graph.store.graph_store import GraphStore

        db = tmp_path / "graph.db"
        GraphStore(db).close()
        db.chmod(0o644)
        GraphStore(db).close()
        GraphStore(":memory:").close()

        assert _mode(db) == 0o644


# ---------------------------------------------------------------------------
# F11 — dead demo route removed; psbdmp URL encoded
# ---------------------------------------------------------------------------


class TestWebAndPaste:
    async def test_demo_chat_route_is_gone(self):
        import openosint.web_server as ws
        from httpx import ASGITransport, AsyncClient

        app = ws.create_app(host="127.0.0.1", port=8080)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8080") as c:
            resp = await c.post("/api/demo/chat", json={"message": "tools"})

        assert resp.status_code in (404, 405)
        assert not hasattr(ws, "_demo_chat_stream")
        assert all(getattr(r, "path", "") != "/api/demo/chat" for r in app.routes)

    @pytest.mark.parametrize(
        ("query", "suffix"),
        [
            ("person@example.com", "/api/search/person@example.com"),  # unchanged for normal input
            ("johndoe", "/api/search/johndoe"),
            ("../admin?x=1#y z", "/api/search/..%2Fadmin%3Fx%3D1%23y%20z"),
            ("50%", "/api/search/50%25"),
        ],
    )
    async def test_query_is_one_encoded_path_segment(self, query, suffix):
        from openosint.tools import search_paste

        resp = MagicMock(status_code=404)
        with patch.object(search_paste.requests, "get", return_value=resp) as get:
            await search_paste.run_paste_osint(query, timeout_seconds=5)

        url = get.call_args.args[0]
        assert url == "https://psbdmp.ws" + suffix
