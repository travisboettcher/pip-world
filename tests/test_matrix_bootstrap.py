import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("mx_bootstrap", Path(__file__).resolve().parents[3] / "matrix" / "bootstrap.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)

ONE_TIME, CONFIGURED = "first-time-token", "configured-token"


class Server:
    """A just-enough homeserver: registration by token (the first account needs the one-time token), login, rooms."""

    def __init__(self):
        self.users, self.rooms, self.joined, self.sessions = {}, {}, [], set()
        self.admin_done = False
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(200, {"versions": ["v1.11"]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                path = self.path
                if path.endswith("/register"):
                    return self._send(*outer.register(body))
                if path.endswith("/login"):
                    u = body["identifier"]["user"]
                    if outer.users.get(u, {}).get("password") != body["password"]:
                        return self._send(403, {"errcode": "M_FORBIDDEN", "error": "bad login"})
                    return self._send(200, {"user_id": f"@{u}:srv", "access_token": f"tok-{u}-login"})
                if path.endswith("/createRoom"):
                    rid = f"!room{len(outer.rooms) + 1}:srv"
                    outer.rooms[rid] = body
                    return self._send(200, {"room_id": rid})
                if "/join/" in path:
                    outer.joined.append((path, self.headers.get("Authorization")))
                    return self._send(200, {"room_id": "x"})
                self._send(404, {"errcode": "M_UNRECOGNIZED"})

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def register(self, body):
        auth = body.get("auth")
        if not auth:
            return 401, {"flows": [{"stages": ["m.login.registration_token"]}], "params": {}, "session": "s1"}
        want = CONFIGURED if self.admin_done else ONE_TIME
        if auth.get("token") != want:
            return 401, {"errcode": "M_FORBIDDEN", "error": "bad registration token"}
        u = body["username"]
        if u in self.users:
            return 400, {"errcode": "M_USER_IN_USE", "error": "taken"}
        self.users[u] = {"password": body["password"]}
        self.admin_done = True
        return 200, {"user_id": f"@{u}:srv", "access_token": f"tok-{u}"}

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def world(tmp_path, monkeypatch):
    srv = Server()
    (tmp_path / "matrix.env").write_text(f"MATRIX_ALLOW_REGISTRATION=true\nMATRIX_REGISTRATION_TOKEN={CONFIGURED}\n# note\nMATRIX_BOT_PASSWORD=\n")
    (tmp_path / "pip.env").write_text("ANTHROPIC_API_KEY=keep-me\nLLM_MODEL=x\n")
    monkeypatch.setenv("BOOTSTRAP_OWNER_PASSWORD", "a-long-owner-password")
    monkeypatch.setattr(B, "first_account_token", lambda container="matrix": ONE_TIME)
    yield srv, tmp_path
    srv.close()


def run(srv, tmp, *extra):
    return B.main(["--homeserver", srv.url, "--server-name", "srv", "--matrix-env", str(tmp / "matrix.env"),
                   "--write-env", str(tmp / "pip.env"), *extra])


def test_creates_both_accounts_a_private_room_and_pips_settings(world, capsys):
    srv, tmp = world
    assert run(srv, tmp) == 0
    assert set(srv.users) == {"morgan", "pip"}
    (room,) = srv.rooms.values()
    assert room["preset"] == "trusted_private_chat" and room["invite"] == ["@pip:srv"] and room["visibility"] == "private"
    assert not any(s.get("type") == "m.room.encryption" for s in room.get("initial_state", []))      # unencrypted
    env = B.read_env(tmp / "pip.env")
    assert env["ANTHROPIC_API_KEY"] == "keep-me" and env["LLM_MODEL"] == "x"                           # the rest of the file is kept
    assert (env["OUTREACH_CHANNELS"], env["MATRIX_USER_ID"], env["MATRIX_ROOM_ID"], env["MATRIX_ALLOWED"]) == (
        "matrix", "@pip:srv", "!room1:srv", "@morgan:srv=Morgan")
    assert env["MATRIX_ACCESS_TOKEN"] == "tok-pip" and env["MATRIX_HOMESERVER"] == srv.url
    assert srv.joined and srv.joined[0][1] == "Bearer tok-pip"                                          # Pip joined with its own token
    menv = B.read_env(tmp / "matrix.env")
    assert menv["MATRIX_ALLOW_REGISTRATION"] == "false" and menv["MATRIX_BOT_PASSWORD"]                  # closed; password kept
    out = capsys.readouterr().out
    assert "a-long-owner-password" not in out and menv["MATRIX_BOT_PASSWORD"] not in out and "tok-pip" not in out   # no secrets printed
    assert oct((tmp / "pip.env").stat().st_mode & 0o777) == "0o600"


def test_running_again_logs_in_and_reuses_the_room(world):
    srv, tmp = world
    run(srv, tmp)
    first = B.read_env(tmp / "pip.env")
    run(srv, tmp, "--keep-registration-open")
    again = B.read_env(tmp / "pip.env")
    assert len(srv.rooms) == 1 and again["MATRIX_ROOM_ID"] == first["MATRIX_ROOM_ID"]                    # no second room
    assert again["MATRIX_ACCESS_TOKEN"] == "tok-pip-login"                                                # a fresh login token
    assert B.read_env(tmp / "matrix.env")["MATRIX_ALLOW_REGISTRATION"] == "false"                         # --keep... doesn't reopen it


def test_a_short_owner_password_and_a_missing_token_are_refused(world, monkeypatch):
    srv, tmp = world
    monkeypatch.setenv("BOOTSTRAP_OWNER_PASSWORD", "short")
    with pytest.raises(SystemExit, match="at least 12"):
        run(srv, tmp)
    monkeypatch.setenv("BOOTSTRAP_OWNER_PASSWORD", "a-long-owner-password")
    (tmp / "matrix.env").write_text("MATRIX_ALLOW_REGISTRATION=true\n")
    with pytest.raises(SystemExit, match="no MATRIX_REGISTRATION_TOKEN"):
        run(srv, tmp)


def test_the_one_time_token_is_read_from_the_servers_log(monkeypatch):
    class R:
        stdout = ("\x1b[1mWelcome\x1b[0m\nregister an account on \x1b[1;32mm.example\x1b[0m using the registration token "
                  "\x1b[1;32mFsXub4SNDyGgpAM2\x1b[0m . Pick your own\n")
        stderr = ""
    monkeypatch.setattr(B.subprocess, "run", lambda *a, **k: R())
    assert B.first_account_token() == "FsXub4SNDyGgpAM2"
    monkeypatch.setattr(B.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no docker")))
    assert B.first_account_token() is None


def test_write_env_updates_in_place_and_appends(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# top\nA=1\nB=2\n")
    B.write_env(p, {"B": "9", "C": "3"})
    assert p.read_text() == "# top\nA=1\nB=9\nC=3\n"
