import os
import sqlite3
import time
import zipfile

import pytest

from app import library as lib
from app import tools as tools_mod
from app.config import Settings
from tests.test_projects import FixedRng, call, make, report

CH1 = "The bees wake at dawn. " * 20      # 460 chars
CH2 = "Honey is stored in wax cells. " * 20  # 600 chars


def tiny_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of text per page (empty string = a page with no text)."""
    n = len(pages)
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [" + " ".join(f"{4 + 2 * i} 0 R" for i in range(n)) + f"] /Count {n} >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {5 + 2 * i} 0 R >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def tiny_epub(path: str, chapters: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        items = "".join(f'<item id="c{i}" href="text/c{i}.xhtml" media-type="application/xhtml+xml"/>'
                        for i in range(len(chapters)))
        spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
        z.writestr("OEBPS/content.opf", f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
                   f'version="3.0"><manifest>{items}</manifest><spine>{spine}</spine></package>')
        for i, text in enumerate(chapters):
            z.writestr(f"OEBPS/text/c{i}.xhtml", f"<html><head><style>p{{}}</style></head><body><h1>Chapter {i + 1}"
                       f"</h1><p>{text}</p><script>ignored()</script></body></html>")


def calibre(root) -> str:
    """A small Calibre library: an EPUB, a PDF, a picture-only PDF and a MOBI."""
    root = str(root)
    os.makedirs(root)
    db = sqlite3.connect(os.path.join(root, "metadata.db"))
    db.executescript("""
      CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, path TEXT);
      CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT);
      CREATE TABLE books_authors_link (book INTEGER, author INTEGER);
      CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
      CREATE TABLE books_tags_link (book INTEGER, tag INTEGER);
      CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT);
      CREATE TABLE books_series_link (book INTEGER, series INTEGER);
      CREATE TABLE comments (book INTEGER, text TEXT);
      CREATE TABLE data (book INTEGER, format TEXT, name TEXT);
    """)
    books = [(1, "The Beekeeper's Year", "Ada Comb", "EPUB", "Nature", "<p>All about <b>bees</b>.</p>"),
             (2, "Gears and Wheels", "Otto Cog", "PDF", "Making", None),
             (3, "Pictures of Hives", "Ada Comb", "PDF", "Nature", None),
             (4, "Old Sea Tales", "Unknown", "MOBI", "", None)]
    for bid, title, author, fmt, tag, desc in books:
        path = f"{author}/{title} ({bid})"
        os.makedirs(os.path.join(root, path))
        db.execute("INSERT INTO books VALUES (?, ?, ?)", (bid, title, path))
        db.execute("INSERT OR IGNORE INTO authors (name) VALUES (?)", (author,))
        db.execute("INSERT INTO books_authors_link VALUES (?, (SELECT id FROM authors WHERE name = ?))", (bid, author))
        if tag:
            db.execute("INSERT OR IGNORE INTO tags (id, name) SELECT (SELECT COUNT(*) + 1 FROM tags), ? "
                       "WHERE NOT EXISTS (SELECT 1 FROM tags WHERE name = ?)", (tag, tag))
            db.execute("INSERT INTO books_tags_link VALUES (?, (SELECT id FROM tags WHERE name = ?))", (bid, tag))
        if desc:
            db.execute("INSERT INTO comments VALUES (?, ?)", (bid, desc))
        db.execute("INSERT INTO data VALUES (?, ?, ?)", (bid, fmt, "book"))
        file = os.path.join(root, path, f"book.{fmt.lower()}")
        if fmt == "EPUB":
            tiny_epub(file, [CH1, CH2])
        elif bid == 2:
            open(file, "wb").write(tiny_pdf(["Cut the teeth evenly.", "", "Mesh the wheels gently."]))
        elif bid == 3:
            open(file, "wb").write(tiny_pdf([""] * 6))
        else:
            open(file, "wb").write(b"not really a mobi")
    db.commit()
    return root


def reading(st, **params):
    """The shipped `reading` module, live."""
    from app import modules as M
    from tests.test_modules import live
    man, src = M.library("reading")
    man.pop("reason", None)
    return live(st, {**man, "params": {**man["params"], **params}}, src, author=M.SHIPPED)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "EMPTY_RUN_LIMIT", 4)
    path = calibre(tmp_path / "calibre")
    def build(gm_script=None, **kw):
        s, st, gm, agent = make(tmp_path, gm_script, library_path=path, work_speed=1e6, read_chars_per_minute=10, modules="on",
                                module_runner="local", **kw)
        reading(st, speed=1e6)
        return s, st, gm, agent
    return build


async def use(agent, name, **args):
    """A tool as the agent uses it (the reading module's, where it applies): what it says."""
    from app.llm.base import ToolCall
    return (await agent._run_tool(ToolCall(id="1", name=name, arguments=args), 0))["content"]


def moment(st):
    return next(e["data"] for e in st.events(20) if e["kind"] == "module" and e["data"].get("tool") == "read")


async def finish(agent):
    """The reading session's time is up."""
    agent.state.db.execute("UPDATE work_session SET ends_at = ?", (time.time() - 1,))
    agent.state.db.commit()
    return await agent.finish_work()


def mark(st, book_id):
    return (st.store("reading").get("marks") or {}).get(str(book_id))


# --- the catalogue ---------------------------------------------------------------
def test_catalogue_search_find_wander(world):
    s, st, gm, agent = world()
    L = agent.library
    assert [b["title"] for b in L.search("bees")] == ["The Beekeeper's Year"]  # via the description
    assert [b["id"] for b in L.search("ada comb")] == [1, 3]
    b = L.book(1)
    assert b["format"] == "EPUB" and b["description"] == "All about bees." and b["tags"] == "Nature"
    assert L.book(4)["format"] is None and L.find("#9")[1] == "there's no book #9 here"
    assert L.find("gears and wheels")[0]["id"] == 2 and "which one?" in L.find("ada")[1]
    shelf, books = L.wander(FixedRng())
    assert shelf in ("the shelves", "the Nature shelf", "the Making shelf") and books
    assert L.overview().startswith("about 4 books; shelves include")


def test_extract_epub_and_pdf_from_a_bookmark(world):
    s, st, gm, agent = world()
    L = agent.library
    epub = L.book(1)
    first = L.extract(epub, 0, 0, 300)
    assert first["text"].startswith("Chapter 1\nThe bees wake at dawn.") and "ignored" not in first["text"]
    assert (first["section"], first["done"]) == (0, False) and len(first["text"]) == 300
    rest = L.extract(epub, first["section"], first["offset"], 5000)
    assert "Honey is stored in wax cells." in rest["text"] and rest["done"] and rest["percent"] == 100
    pdf = L.extract(L.book(2), 0, 0, 5000)
    assert pdf["text"] == "Cut the teeth evenly.\nMesh the wheels gently." and pdf["done"]  # blank page skipped
    pics = L.extract(L.book(3), 0, 0, 5000)
    assert pics["pictures"] and pics["text"] == ""


def test_reading_is_offered_only_with_a_library(tmp_path):
    from app import modules as M
    s, st, gm, agent = make(tmp_path, library_path=str(tmp_path / "nope"), modules="on", module_runner="local")
    reading(st)
    assert agent.library is None and M.tools_offered(st) == [] and "read" not in agent.tool_names()
    s = Settings(library_path=str(tmp_path / "nope"), tools=["go_to", "browse", "read", "rest"])
    assert list(tools_mod.enabled_tools(s)) == ["go_to", "browse", "rest"]  # read is the reading module's; browse looks over the junkyard


# --- going there ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_walking_to_the_library_and_location_rules(world):
    s, st, gm, agent = world([report(text="Tall shelves, a hush, a smell of old paper.")])
    assert "you set off for the library" in (await call(agent, "go_to", place="the Library")).text
    assert st.agent()["activity"] == "walking"
    assert "on your way to the library" in (await call(agent, "go_to", place="home")).text
    assert "rest once you get there" in (await call(agent, "rest")).text
    assert "(still busy) you're on your way to the library" in (await call(agent, "set_activity", activity="strolling")).text
    time.sleep(0.01)
    assert await agent.finish_work()
    a = st.agent()
    assert a["location"] == "library" and a["description"] == "just arrived at the library"
    assert "about 4 books" in gm.calls[0]["messages"][0]["content"]  # described from the real shelves
    p = agent._perception("event", [])
    assert "You are at: the library - Tall shelves, a hush" in p and "Places you can go (go_to):\n- workshop, 10 min - your home: your workshop and garden [projects, garden, sleep]" in p
    assert "You went to the library for the first time" in p and "Here you can: browse (look for books" in p and "read (settle in and read a book for a while)" in p
    assert "go_to home first" in (await call(agent, "tend", creation="x")).text
    assert "already at the library" in (await call(agent, "go_to", place="library")).text
    await call(agent, "go_to", place="home")
    time.sleep(0.01)
    await agent.finish_work()
    await call(agent, "go_to", place="library")
    time.sleep(0.01)
    await agent.finish_work()
    assert len(gm.calls) == 1  # each place is described once
    assert "error: you don't know a place called 'moon'" in (await call(agent, "go_to", place="moon")).text


async def at_library(agent, st):
    await call(agent, "go_to", place="library")
    time.sleep(0.01)
    await agent.finish_work()


# --- reading -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_browse_and_read_with_a_bookmark(world):
    s, st, gm, agent = world([report(text="A library."),
                              report(summary="You read about bees waking.", quotes=["The bees wake at dawn."]),
                              report(summary="You read about honey and wax.")])
    assert "not at the library" in await use(agent, "browse", query="bees")
    await at_library(agent, st)
    assert await use(agent, "browse", query="bees") == "Looking for 'bees', you find:\n- #1 The Beekeeper's Year - Ada Comb [Nature]: All about bees."
    assert await use(agent, "browse", query="zebras") == "nothing on the shelves matches 'zebras'"
    assert (await use(agent, "browse")).startswith("Wandering along ")
    assert "#4 Old Sea Tales - Unknown (can't be read)" in await use(agent, "browse", query="sea tales")
    assert await use(agent, "read", book="old sea tales") == "Old Sea Tales is bound in a way you can't open (MOBI)"
    assert await use(agent, "read", book="#9") == "error: there's no book #9 here"
    assert await use(agent, "read", book="#1", minutes=30) == "you settle in with The Beekeeper's Year by Ada Comb (from the start) for 30 min"  # 300 chars
    assert st.agent()["activity"] == "reading" and st.session()["kind"] == "module"
    assert "reading The Beekeeper's Year" in (await call(agent, "go_to", place="home")).text
    await finish(agent)
    task = gm.calls[1]["messages"][0]["content"]
    assert "The bees wake at dawn." in task and "Honey" not in task
    m = mark(st, 1)
    assert m["sessions"] == 1 and not m["finished"] and m["section"] == 0 and m["offset"] == 300
    ev = moment(st)
    assert ev["text"] == 'You read The Beekeeper\'s Year (now 0% through): You read about bees waking. "The bees wake at dawn."' and ev["moment"] == "read"
    assert st.agent()["description"] == "just read some of The Beekeeper's Year" and st.abilities()["knowledge"] == 30
    p = agent._perception("event", [])
    assert '- You read The Beekeeper\'s Year (now 0% through): You read about bees waking. "The bees wake at dawn."' in p
    assert "Books you're partway through:\n- #1 The Beekeeper's Year (0% in)" in p
    assert "(you're 0% in)" in await use(agent, "browse", query="bees")
    assert "picking up where you left off, 0% in" in await use(agent, "read", book="beekeeper", minutes=90)
    await finish(agent)
    assert "Honey is stored in wax cells." in gm.calls[2]["messages"][0]["content"]
    assert mark(st, 1)["finished"] and moment(st)["moment"] == "finished_book" and moment(st)["text"].startswith("You read The Beekeeper's Year (and finished it)")
    assert "You finished reading" not in agent._perception("e", []) and "- You read The Beekeeper's Year (and finished it)" in agent._perception("e", [])
    assert await use(agent, "read", book="#1") == "you've already finished The Beekeeper's Year"
    assert "(finished)" in await use(agent, "browse", query="bees")
    assert st.recall("honey wax")[0]["text"].startswith("You read The Beekeeper's Year (and finished it): You read about honey")
    from app import firsts
    assert any(f["key"] == "book_finished" for e in st.events(40) for f in e["data"].get("firsts", []))
    assert firsts.module_firsts()["reading:finished_book"] == {"as": "book_finished", "said": "finished a book"}


@pytest.mark.asyncio
async def test_picture_books_and_putting_a_book_down(world):
    s, st, gm, agent = world([report(text="A library.")])
    await at_library(agent, st)
    await use(agent, "read", book="pictures of hives")
    await finish(agent)
    assert moment(st)["text"].startswith("You read Pictures of Hives (now 0% through): These pages are almost all pictures")
    assert mark(st, 3)["unreadable"] and await use(agent, "read", book="pictures of hives") == "Pictures of Hives is almost all pictures; there's nothing more to read"
    m = __import__("app.modules", fromlist=["x"]).live_named(st, "reading")
    st.update_module(m["id"], manifest={**m["manifest"], "params": {"speed": 1}})      # real time from here: resting right away means almost nothing was read
    await use(agent, "read", book="gears", minutes=60)
    r = await call(agent, "rest")
    assert "you stopped reading Gears and Wheels early" in r.text and not st.session()
    assert moment(st)["text"] == "You read Gears and Wheels (now 0% through): You'd barely started before you put it down."
    assert mark(st, 2)["sessions"] == 0


@pytest.mark.asyncio
async def test_a_reading_session_from_before_it_was_a_module_just_ends(world):
    s, st, gm, agent = world()
    st.start_session(1, 0, 30, time.time() - 1, kind="read", target="The Beekeeper's Year")
    assert await agent.finish_work() is False and not st.session()
    st.start_session(1, 0, 30, time.time() + 999, kind="read", target="The Beekeeper's Year")
    await call(agent, "rest")
    assert not st.session()


def test_an_older_install_keeps_its_bookmarks(tmp_path):
    from app.state import State
    path = str(tmp_path / "old.db")
    st = State(Settings(), path)
    st.db.executescript("""
        CREATE TABLE bookmarks (book_id INTEGER PRIMARY KEY, title TEXT NOT NULL, section INTEGER NOT NULL DEFAULT 0, offset INTEGER NOT NULL DEFAULT 0,
                                percent INTEGER NOT NULL DEFAULT 0, sessions INTEGER NOT NULL DEFAULT 0, finished INTEGER NOT NULL DEFAULT 0,
                                unreadable INTEGER NOT NULL DEFAULT 0, last_read REAL);
        INSERT INTO bookmarks VALUES (7, 'Tide Tables', 3, 120, 40, 2, 0, 0, 1000.0);
        INSERT INTO bookmarks VALUES (8, 'Old Maps', 0, 0, 100, 4, 1, 0, 900.0);
        INSERT INTO bookmarks VALUES (9, 'Plates', 2, 0, 10, 1, 0, 1, 800.0);
    """)
    st = State(Settings(), path)
    assert st.store("reading") == {"marks": {
        "7": {"book_id": 7, "title": "Tide Tables", "section": 3, "offset": 120, "percent": 40, "sessions": 2, "finished": False, "unreadable": False, "last_read": 1000.0},
        "8": {"book_id": 8, "title": "Old Maps", "section": 0, "offset": 0, "percent": 100, "sessions": 4, "finished": True, "unreadable": False, "last_read": 900.0},
        "9": {"book_id": 9, "title": "Plates", "section": 2, "offset": 0, "percent": 10, "sessions": 1, "finished": False, "unreadable": True, "last_read": 800.0}}}
    assert not st.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'bookmarks'").fetchone()
    assert State(Settings(), path).store("reading")["marks"]["7"]["offset"] == 120                  # once


@pytest.mark.asyncio
async def test_putting_a_book_down_late_still_takes_in_what_was_read(world):
    from app import modules as M
    s, st, gm, agent = world([report(text="A library."), report(summary="A summary from the narrator.")])
    await at_library(agent, st)
    m = M.live_named(st, "reading")
    st.update_module(m["id"], manifest={**m["manifest"], "params": {"speed": 60}})          # an hour's reading in a minute
    await use(agent, "read", book="#1", minutes=60)
    st.db.execute("UPDATE work_session SET started_at = ?", (time.time() - 60,))
    st.db.commit()
    assert "you stopped reading The Beekeeper's Year early" in (await call(agent, "rest")).text
    assert moment(st)["text"].startswith("You read The Beekeeper's Year (now ") and "A summary from the narrator." in moment(st)["text"]
    assert mark(st, 1)["sessions"] == 1 and mark(st, 1)["offset"] + 1000 * mark(st, 1)["section"] > 0 and st.abilities()["knowledge"] >= 55
