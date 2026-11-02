"""The library is a provider: Calibre is one source of books, a plain folder of books is another (DESIGN-extract.md)."""
import logging
import os
import random
import zipfile

import pytest

from app import library as lib
from app import library_calibre as calibre_provider
from app import library_folder as folder_provider
from app.config import Settings
from tests.test_library import CH1, CH2, calibre, tiny_epub, tiny_pdf
from tests.test_projects import FixedRng, make


def opf_epub(path, title, author, description, chapters):
    """An EPUB whose package file carries Dublin Core metadata."""
    tiny_epub(path, chapters)
    with zipfile.ZipFile(path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    meta = (f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title>'
            f'<dc:creator>{author}</dc:creator><dc:description>{description}</dc:description></metadata>')
    files["OEBPS/content.opf"] = files["OEBPS/content.opf"].replace(b"<manifest>", meta.encode() + b"<manifest>")
    with zipfile.ZipFile(path, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)


@pytest.fixture
def shelf(tmp_path):
    """A folder of books: two shelves (sub-folders), a loose file, and things that are not books."""
    root = tmp_path / "books"
    (root / "Nature").mkdir(parents=True)
    (root / "Making").mkdir()
    opf_epub(str(root / "Nature" / "year.epub"), "The Beekeeper's Year", "Ada Comb", "All about bees.", [CH1, CH2])
    (root / "Nature" / "wild_honey_notes.txt").write_text("Honey is stored in wax cells. " * 30)
    (root / "Making" / "gears-and-wheels.pdf").write_bytes(tiny_pdf(["Cut the teeth evenly.", "Mesh the wheels gently."]))
    (root / "readme.md").write_text("# A Note\n\nBees sleep in winter.")
    (root / "cover.jpg").write_bytes(b"\xff\xd8 not a book")
    (root / "Making" / "old.mobi").write_bytes(b"not readable here")
    return str(root)


# --- choosing a provider ---------------------------------------------------------------------------------------------
def test_the_two_providers_are_registered_by_name():
    assert lib.PROVIDERS["calibre"] is calibre_provider.Calibre and lib.PROVIDERS["folder"] is folder_provider.Folder


def test_auto_picks_calibre_when_there_is_a_calibre_library_and_a_folder_of_books_otherwise(tmp_path, shelf):
    cal = calibre(tmp_path / "cal")
    assert isinstance(lib.open_library(Settings(library_path=cal)), calibre_provider.Calibre)
    assert isinstance(lib.open_library(Settings(library_path=shelf)), folder_provider.Folder)
    assert lib.open_library(Settings(library_path=str(tmp_path / "nope"))) is None
    (tmp_path / "empty").mkdir()
    assert lib.open_library(Settings(library_path=str(tmp_path / "empty"))) is None            # nothing readable in it


def test_a_named_provider_is_used_or_nothing(tmp_path, shelf):
    cal = calibre(tmp_path / "cal")
    assert isinstance(lib.open_library(Settings(library_path=cal, library_provider="folder")), folder_provider.Folder)
    assert lib.open_library(Settings(library_path=shelf, library_provider="calibre")) is None   # no metadata.db there
    assert lib.open_library(Settings(library_path=shelf, library_provider="no-such")) is None
    assert Settings().library_provider == "auto"


def test_a_provider_is_looked_up_case_insensitively_from_the_environment(monkeypatch):
    monkeypatch.setenv("LIBRARY_PROVIDER", " Folder ")
    assert Settings.from_env().library_provider == "folder"


# --- the folder provider's catalogue ---------------------------------------------------------------------------------
def test_the_folder_catalogue_reads_what_it_can_from_the_books_themselves(shelf):
    L = folder_provider.Folder(shelf)
    assert L.available() is True
    by = {b["title"]: b for b in L.all()}
    assert set(by) == {"The Beekeeper's Year", "Wild Honey Notes", "Gears And Wheels", "Readme", "Old"}   # no cover.jpg
    year = by["The Beekeeper's Year"]
    assert (year["authors"], year["tags"], year["series"], year["description"], year["format"], year["formats"]) == \
        ("Ada Comb", "Nature", "", "All about bees.", "EPUB", ["EPUB"])
    assert by["Wild Honey Notes"]["authors"] == "Unknown" and by["Wild Honey Notes"]["format"] == "TXT"
    assert by["Wild Honey Notes"]["description"] == ""
    assert by["Gears And Wheels"]["tags"] == "Making" and by["Gears And Wheels"]["format"] == "PDF"
    assert by["Readme"]["tags"] == "" and by["Readme"]["format"] == "TXT"
    assert by["Old"]["format"] is None and by["Old"]["formats"] == ["MOBI"]                                # listed, can't be read
    assert [b["title"] for b in L.all()] == ["Gears And Wheels", "Old", "Wild Honey Notes", "The Beekeeper's Year", "Readme"]  # by path


def test_a_missing_or_empty_folder_is_not_available(tmp_path):
    assert folder_provider.Folder(str(tmp_path / "nope")).available() is False
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "notes.jpg").write_bytes(b"x")
    assert folder_provider.Folder(str(tmp_path / "empty")).available() is False


def test_book_ids_are_stable_positive_numbers_that_do_not_collide(shelf, tmp_path):
    ids = [b["id"] for b in folder_provider.Folder(shelf).all()]
    assert len(set(ids)) == len(ids) == 5 and all(0 < i <= folder_provider.ID_SPACE for i in ids)
    assert ids == [b["id"] for b in folder_provider.Folder(shelf).all()]                                  # the same every time
    root = tmp_path / "many"
    root.mkdir()
    for i in range(60):
        (root / f"b{i}.txt").write_text(f"book {i}")
    assert len({b["id"] for b in folder_provider.Folder(str(root)).all()}) == 60


def test_a_collision_is_settled_by_taking_the_next_free_number(shelf, monkeypatch):
    monkeypatch.setattr(folder_provider, "ID_SPACE", 3)                                                   # force collisions
    ids = [b["id"] for b in folder_provider.Folder(shelf).all()]
    assert len(set(ids)) == 5 and min(ids) >= 1


def test_search_ranks_by_title_then_everything_else_and_ignores_the_files_text(shelf):
    L = folder_provider.Folder(shelf)
    assert [b["title"] for b in L.search("bees")] == ["The Beekeeper's Year"]            # via its description
    assert [b["title"] for b in L.search("ada comb")] == ["The Beekeeper's Year"]         # via its author
    assert sorted(b["title"] for b in L.search("nature")) == ["The Beekeeper's Year", "Wild Honey Notes"]   # via the shelf
    assert L.search("   ") == [] and L.search("zzz") == []
    assert [b["title"] for b in L.search("honey notes", limit=1)] == ["Wild Honey Notes"]


def test_find_takes_a_number_a_title_or_asks_which_one(shelf, tmp_path):
    L = folder_provider.Folder(shelf)
    year = L.find("the beekeeper's year")[0]
    assert year["title"] == "The Beekeeper's Year" and L.find(f"#{year['id']}")[0]["id"] == year["id"]
    assert L.find(str(year["id"]))[0]["id"] == year["id"]
    assert L.find("#999999999") == (None, "there's no book #999999999 here")
    assert L.find("zzzz") == (None, "you can't find a book like 'zzzz' (try browse)")
    root = tmp_path / "bee"
    root.mkdir()
    (root / "bee_notes.txt").write_text("a")
    (root / "bee_facts.txt").write_text("b")
    b, why = folder_provider.Folder(str(root)).find("bee")
    assert b is None and why.startswith("which one? #") and "Bee Facts" in why and "Bee Notes" in why


def test_wander_and_overview(shelf):
    L = folder_provider.Folder(shelf)
    name, picked = L.wander(random.Random(1))
    assert name in ("the shelves", "the Nature shelf", "the Making shelf") and 0 < len(picked) <= 8
    assert all(b in L.all() for b in picked)
    over = L.overview()
    assert over.startswith("about 5 books; shelves include Making, Nature; some titles: ")
    assert all(t in over for t in ("The Beekeeper's Year", "Wild Honey Notes", "Gears And Wheels", "Readme", "Old"))


# --- reading from a folder -------------------------------------------------------------------------------------------
def test_text_files_epubs_and_pdfs_are_read_in_stretches_with_a_position(shelf):
    L = folder_provider.Folder(shelf)
    by = {b["title"]: b for b in L.all()}
    text = ("Honey is stored in wax cells. " * 30).strip()
    first = L.extract(by["Wild Honey Notes"], 0, 0, 100)
    assert first["text"] == text[:100] and first["done"] is False and (first["section"], first["offset"]) == (0, 100)
    rest = L.extract(by["Wild Honey Notes"], first["section"], first["offset"], 10_000)
    assert rest["text"] == text[100:] and rest["done"] is True and rest["percent"] == 100
    epub = L.extract(by["The Beekeeper's Year"], 0, 0, 10_000)
    assert "The bees wake at dawn." in epub["text"] and "Honey is stored" in epub["text"] and epub["total"] == 2
    pdf = L.extract(by["Gears And Wheels"], 0, 0, 10_000)
    assert "Cut the teeth evenly." in pdf["text"] and pdf["total"] == 2
    md = L.extract(by["Readme"], 0, 0, 10_000)
    assert md["text"] == "# A Note\n\nBees sleep in winter." and md["done"] is True


def test_a_long_text_file_is_read_in_sections_so_progress_moves(shelf, monkeypatch):
    monkeypatch.setattr(lib, "TEXT_SECTION_CHARS", 200)
    L = folder_provider.Folder(shelf)
    b = next(b for b in L.all() if b["title"] == "Wild Honey Notes")
    got = L.extract(b, 0, 0, 300)
    assert got["total"] == 5 and (got["section"], got["offset"]) == (1, 100) and got["percent"] == 20 and got["done"] is False


@pytest.mark.asyncio
async def test_pip_can_read_a_book_from_a_folder_like_any_other(tmp_path, shelf, monkeypatch):
    monkeypatch.setattr(lib, "TEXT_SECTION_CHARS", 200)
    s, st, gm, agent = make(tmp_path, library_path=shelf, work_speed=1e6, read_chars_per_minute=10)
    L = agent.library
    assert isinstance(L, folder_provider.Folder)
    book = L.find("wild honey notes")[0]
    lib.start_reading(st, s, book, 30)
    data = await lib.finish_reading(st, s, None, L)
    assert data["percent"] == 20 and data["summary"].startswith("Honey is stored") and st.bookmark(book["id"])["sessions"] == 1
    assert st.bookmark(book["id"])["section"] == 1


# --- the shared pieces the providers lean on -------------------------------------------------------------------------
def test_the_format_readers_are_shared_and_work_from_a_bare_path(shelf):
    epub = lib.extract_file(os.path.join(shelf, "Nature", "year.epub"), "EPUB", 0, 0, 10_000)
    assert epub["total"] == 2 and "The bees wake at dawn." in epub["text"]
    assert lib.epub_metadata(os.path.join(shelf, "Nature", "year.epub")) == \
        {"title": "The Beekeeper's Year", "authors": "Ada Comb", "description": "All about bees."}
    assert lib.epub_metadata(os.path.join(shelf, "readme.md")) == {}                                     # not an EPUB: nothing
    plain = os.path.join(shelf, "Nature", "wild_honey_notes.txt")
    assert lib.extract_file(plain, "TXT", 0, 0, 5)["text"] == "Honey"


def test_ranking_is_shared(shelf):
    books = [{"id": 2, "title": "Wax", "authors": "", "tags": "", "series": "", "description": "about bees"},
             {"id": 1, "title": "Bees", "authors": "", "tags": "", "series": "", "description": ""},
             {"id": 3, "title": "Bees and bees", "authors": "Ada", "tags": "", "series": "", "description": "bees"}]
    assert [b["id"] for b in lib.rank(books, "bees", 8)] == [3, 1, 2]          # title hits count 3, anything else 1, ties by id
    assert [b["id"] for b in lib.rank(books, "bees", 2)] == [3, 1] and lib.rank(books, "a", 8) == [] and lib.rank(books, "", 8) == []


# --- the details that decide what Pip sees ---------------------------------------------------------------------------
class StubRng:
    """random() answers what it is told; choice takes the first; sample takes the first k."""
    def __init__(self, r):
        self.r = r

    def random(self):
        return self.r

    def choice(self, seq):
        return seq[0]

    def sample(self, population, k):
        return list(population)[:k]


def books_folder(tmp_path, layout):
    """A folder of text files: layout maps a relative path to its text."""
    root = tmp_path / "lib"
    for rel, text in layout.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return folder_provider.Folder(str(root))


def test_registering_a_provider_stores_the_class_and_hands_it_back(monkeypatch):
    monkeypatch.setattr(lib, "PROVIDERS", {})
    assert lib.register("x")(folder_provider.Folder) is folder_provider.Folder and lib.PROVIDERS == {"x": folder_provider.Folder}


def test_hidden_folders_and_files_are_not_books(tmp_path):
    L = books_folder(tmp_path, {"a.txt": "x", ".hidden/b.txt": "x", ".c.txt": "x", "shelf/.d.txt": "x", "shelf/e.txt": "x"})
    assert [b["path"] for b in L.all()] == ["a.txt", os.path.join("shelf", "e.txt")]


def test_book_numbers_come_from_the_path_and_collisions_count_up_by_one(tmp_path, monkeypatch):
    L = books_folder(tmp_path, {"readme.md": "x"})
    assert L.all()[0]["id"] == 650027                                                 # sha1 of the relative path, in a million, plus one
    monkeypatch.setattr(folder_provider, "ID_SPACE", 1)                         # every path wants number 1
    L = books_folder(tmp_path / "x", {"a.txt": "x", "b.txt": "x", "c.txt": "x"})
    assert [b["id"] for b in L.all()] == [1, 2, 3]
    assert L.book(2)["path"] == "b.txt" and L.book(4) is None


def test_an_epub_is_only_opened_again_when_it_changed(shelf, monkeypatch):
    calls = []
    real = lib.epub_metadata
    monkeypatch.setattr(lib, "epub_metadata", lambda path: calls.append(path) or real(path))
    L = folder_provider.Folder(shelf)
    L.all(), L.all()
    assert len(calls) == 1
    full = os.path.join(shelf, "Nature", "year.epub")
    os.utime(full, (os.path.getmtime(full) + 60, os.path.getmtime(full) + 60))
    L.all()
    assert len(calls) == 2 and L._meta[os.path.join("Nature", "year.epub")][0] == os.path.getmtime(full)


def test_search_takes_a_limit_and_defaults_to_eight(tmp_path):
    L = books_folder(tmp_path, {f"bee{i}.txt": "x" for i in range(10)})
    assert len(L.search("bee")) == 8 and len(L.search("bee", limit=3)) == 3 and len(L.search("bee", 20)) == 10
    assert len(lib.rank(L.all(), "bee")) == 8


def test_ranking_details():
    book = lambda i, title="", desc="", authors="": {"id": i, "title": title, "authors": authors, "tags": "", "series": "", "description": desc}  # noqa: E731
    assert [b["id"] for b in lib.rank([book(1, "Ox")], "ox")] == [1]                    # two letters count
    assert lib.rank([book(1, "Ox")], "x") == []                                          # one letter does not
    seven = "one two three four five six seven"
    assert lib.rank([book(1, "seven")], seven) == []                                     # only the first six words are used
    assert [b["id"] for b in lib.rank([book(1, "six")], seven)] == [1]
    a, b = book(1, "alpha"), book(2, "zzz", desc="alpha beta gamma delta")               # a title hit is worth three, a blurb hit one
    assert [x["id"] for x in lib.rank([a, b], "alpha beta gamma delta")] == [2, 1]
    assert [x["id"] for x in lib.rank([b, a], "alpha")] == [1, 2]


def test_wander_picks_a_shelf_seven_times_in_ten_and_otherwise_anywhere(tmp_path):
    files = {f"Making/m{i}.txt": "x" for i in range(2)} | {"Nature/n.txt": "x"} | {"loose.txt": "x"}
    L = books_folder(tmp_path, files)
    name, picked = L.wander(StubRng(0.5))
    assert name == "the Making shelf" and sorted(b["path"] for b in picked) == [os.path.join("Making", "m0.txt"), os.path.join("Making", "m1.txt")]
    assert L.wander(StubRng(0.7))[0] == "the shelves" and L.wander(StubRng(0.9))[0] == "the shelves"
    name, picked = L.wander(StubRng(0.9))
    assert len(picked) == 4 and name == "the shelves"                                      # fewer books than the limit: all of them
    many = books_folder(tmp_path / "m", {f"b{i}.txt": "x" for i in range(12)})
    name, picked = many.wander(StubRng(0.5))                                              # nothing is shelved: anywhere, 8 at most
    assert name == "the shelves" and len(picked) == 8 and len(many.wander(StubRng(0.5), limit=3)[1]) == 3


def test_the_overview_counts_the_books_ranks_the_shelves_and_lists_up_to_eight_titles(tmp_path):
    files = {f"Zeta/z{i}.txt": "x" for i in range(3)} | {"Alpha/a.txt": "x"} | {f"Mid/m{i}.txt": "x" for i in range(2)}
    over = books_folder(tmp_path, files).overview()
    assert over.startswith("about 6 books; shelves include Zeta, Mid, Alpha; some titles: ")
    assert len(over.split("some titles: ")[1].split("; ")) == 6
    plain = books_folder(tmp_path / "p", {f"b{i}.txt": "x" for i in range(10)}).overview()
    assert plain.startswith("about 10 books; some titles: ") and "shelves" not in plain
    assert len(plain.split("some titles: ")[1].split("; ")) == 8
    seven = books_folder(tmp_path / "s", {f"S{i}/b.txt": "x" for i in range(8)}).overview()
    assert seven.split("; some titles")[0].count(",") == 5                                # six shelves at most


def test_epub_metadata_takes_the_first_title_joins_authors_and_clips(tmp_path):
    path = str(tmp_path / "b.epub")
    tiny_epub(path, [CH1])
    with zipfile.ZipFile(path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    meta = ('<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title/><dc:title>' + "T" * 400 + "</dc:title>"
            "<dc:creator>Ada</dc:creator><dc:creator>Otto</dc:creator>"
            "<dc:description>&lt;p&gt;" + "d" * 400 + "&lt;/p&gt;</dc:description></metadata>")
    files["OEBPS/content.opf"] = files["OEBPS/content.opf"].replace(b"<manifest>", meta.encode() + b"<manifest>")
    with zipfile.ZipFile(path, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    got = lib.epub_metadata(path)
    assert got["title"] == "T" * 300 + "..." and got["authors"] == "Ada & Otto" and got["description"] == "d" * 300 + "..."
    bare = str(tmp_path / "bare.epub")
    tiny_epub(bare, [CH1])
    assert lib.epub_metadata(bare) == {}                                                  # a package with no metadata


def test_calibre_books_carry_everything_pip_is_shown(tmp_path):
    L = calibre_provider.Calibre(calibre(tmp_path / "cal"))
    assert L.book(1) == {"id": 1, "title": "The Beekeeper's Year", "authors": "Ada Comb", "tags": "Nature", "series": "",
                         "description": "All about bees.", "formats": ["EPUB"], "format": "EPUB",
                         "path": "Ada Comb/The Beekeeper's Year (1)", "file": "book"}
    assert L.book(4)["format"] is None and L.book(4)["file"] is None and L.book(4)["authors"] == "Unknown"
    assert L.book(99) is None
    assert [b["id"] for b in L.search("ada comb", 1)] == [1] and len(L.search("a")) == 0 and L.search("") == []


def test_calibre_wander_and_overview(tmp_path):
    L = calibre_provider.Calibre(calibre(tmp_path / "cal"))
    name, picked = L.wander(StubRng(0.5))
    assert name == "the Nature shelf" and [b["id"] for b in picked] == [1, 3]
    assert L.wander(StubRng(0.7))[0] == "the shelves" and len(L.wander(StubRng(0.9))[1]) == 4
    assert len(L.wander(StubRng(0.9), limit=2)[1]) == 2
    over = L.overview()
    assert over.startswith("about 4 books; shelves include Nature, Making; some titles: ")
    assert sorted(over.split("some titles: ")[1].split("; ")) == ["Gears and Wheels", "Old Sea Tales", "Pictures of Hives", "The Beekeeper's Year"]


# --- reading: the odd cases --------------------------------------------------------------------------------------------
def test_text_that_is_not_valid_utf8_is_read_with_replacements_not_refused(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"abc\xffdef    ghi")
    got = lib.extract_file(str(bad), "TXT", 0, 0, 100)
    assert got["text"] == "abc�def ghi"                                       # and runs of spaces collapse to one
    epub = str(tmp_path / "bad.epub")
    tiny_epub(epub, ["x"])
    with zipfile.ZipFile(epub) as z:
        files = {n: z.read(n) for n in z.namelist()}
    files["OEBPS/text/c0.xhtml"] = b"<html><body><p>caf\xe9 au lait</p></body></html>"
    with zipfile.ZipFile(epub, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    assert lib.extract_file(epub, "EPUB", 0, 0, 100)["text"] == "caf� au lait"


def test_an_empty_text_file_is_one_finished_section_with_no_pictures(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    got = lib.extract_file(str(empty), "TXT", 0, 0, 100)
    assert got == {"text": "", "section": 1, "offset": 0, "total": 1, "percent": 100, "done": True, "pictures": False}


def test_reading_on_from_the_middle_of_a_section_moves_the_position_by_what_was_read(tmp_path):
    f = tmp_path / "long.txt"
    f.write_text("".join(f"{i % 10}" for i in range(1000)))
    got = lib.extract_file(str(f), "TXT", 0, 100, 300)
    assert got["text"] == "".join(str(i % 10) for i in range(100, 400)) and (got["section"], got["offset"]) == (0, 400)


def test_percent_is_the_share_of_sections_finished(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "TEXT_SECTION_CHARS", 100)
    f = tmp_path / "t.txt"
    f.write_text("x" * 299)                                                          # three sections
    got = lib.extract_file(str(f), "TXT", 0, 0, 200)
    assert (got["section"], got["total"], got["percent"], got["done"]) == (2, 3, 66, False)
    assert lib.extract_file(str(f), "TXT", 0, 0, 100)["percent"] == 33


def test_pages_without_text_at_the_start_are_pictures_only_after_enough_of_them(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "EMPTY_RUN_LIMIT", 4)
    book = lambda pages: (lambda p: (p.write_bytes(tiny_pdf(pages)), str(p))[1])(tmp_path / f"{len(pages)}.pdf")      # noqa: E731
    three = lib.extract_file(book(["", "", "", "Real text."]), "PDF", 0, 0, 100)
    assert "Real text." in three["text"] and three["pictures"] is False               # three blank pages are not yet "all pictures"
    four = lib.extract_file(book(["", "", "", "", "Real text."]), "PDF", 0, 0, 100)
    assert four["text"] == "" and four["pictures"] is True and four["section"] == 3   # four are: it stops looking, on the fourth
    two = lib.extract_file(book(["", "", "Real text."]), "PDF", 0, 0, 100)
    assert "Real text." in two["text"]
    logging.getLogger("pypdf").setLevel(logging.NOTSET)
    lib.extract_file(book(["x"]), "PDF", 0, 0, 100)
    assert logging.getLogger("pypdf").level == logging.ERROR                          # the PDF reader's chatter is switched off


# --- more of what the providers hand back -------------------------------------------------------------------------------
def test_epub_authors_are_clipped(tmp_path):
    path = str(tmp_path / "a.epub")
    tiny_epub(path, [CH1])
    with zipfile.ZipFile(path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    files["OEBPS/content.opf"] = files["OEBPS/content.opf"].replace(
        b"<manifest>", ('<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>' + "A" * 400 + "</dc:creator></metadata><manifest>").encode(), 1)
    with zipfile.ZipFile(path, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    assert lib.epub_metadata(path) == {"authors": "A" * 300 + "..."}


def edit_calibre(root, *statements):
    import sqlite3
    db = sqlite3.connect(os.path.join(root, "metadata.db"))
    for sql in statements:
        db.execute(sql)
    db.commit()
    db.close()


def test_calibre_books_with_several_formats_odd_names_no_author_or_a_long_blurb(tmp_path):
    root = calibre(tmp_path / "cal")
    edit_calibre(root,
                 "INSERT INTO data VALUES (1, 'PDF', 'other')",                                  # book 1 also has a PDF
                 "INSERT INTO data VALUES (3, 'TXT', 'a:b')",                                    # a file name with a colon in it
                 "INSERT INTO books VALUES (5, 'No Author', 'x/no')",
                 "INSERT INTO books VALUES (6, 'Long Blurb', 'x/long')",
                 f"INSERT INTO comments VALUES (6, '<p>{'d' * 400}</p>')")
    L = calibre_provider.Calibre(root)
    assert L.book(1)["formats"] == ["EPUB", "PDF"] and L.book(1)["format"] == "EPUB" and L.book(1)["file"] == "book"
    assert L.book(3)["formats"] == ["PDF", "TXT"] and L.book(3)["format"] == "PDF"
    no_files = L.book(5)
    assert no_files["authors"] == "Unknown" and no_files["formats"] == [] and no_files["format"] is None and no_files["tags"] == ""
    assert no_files["series"] == "" and no_files["description"] == ""
    assert L.book(6)["description"] == "d" * 300 + "..."
    edit_calibre(root, "DELETE FROM data WHERE book = 3", "INSERT INTO data VALUES (3, 'TXT', 'a:b')")
    assert L.book(3)["formats"] == ["TXT"] and L.book(3)["file"] == "a:b"                       # split once, at the first colon


def test_calibre_shelves_overview_without_tags_and_books_on_several_shelves(tmp_path):
    root = calibre(tmp_path / "cal")
    edit_calibre(root, "INSERT INTO books_tags_link VALUES (2, (SELECT id FROM tags WHERE name = 'Nature'))")     # book 2 on two shelves
    L = calibre_provider.Calibre(root)
    assert L.book(2)["tags"] in ("Making, Nature", "Nature, Making")
    name, picked = L.wander(StubRng(0.5))
    assert name == "the Nature shelf" and sorted(b["id"] for b in picked) == [1, 2, 3]            # the two-shelf book is on this one too
    edit_calibre(root, "DELETE FROM books_tags_link", "DELETE FROM tags")
    bare = calibre_provider.Calibre(root)
    assert bare.overview().startswith("about 4 books; some titles: ") and "shelves" not in bare.overview()
    assert bare.wander(StubRng(0.5))[0] == "the shelves"
    assert [b["id"] for b in bare.search("old sea", 1)] == [4]


def test_the_folder_overview_lists_titles_exactly_as_they_are(tmp_path):
    L = books_folder(tmp_path, {"Zeta/z0.txt": "x", "Zeta/z1.txt": "x", "Alpha/a.txt": "x", "c.txt": "x"})
    over = L.overview()
    assert over.startswith("about 4 books; shelves include Zeta, Alpha; some titles: ")
    assert sorted(over.split("some titles: ")[1].split("; ")) == ["A", "C", "Z0", "Z1"]


def test_calibre_search_and_wander_return_eight_books_unless_asked_for_more_or_fewer(tmp_path):
    root = calibre(tmp_path / "cal")
    edit_calibre(root, *[f"INSERT INTO books VALUES ({10 + i}, 'Bee Book {i}', 'x/b{i}')" for i in range(10)])
    L = calibre_provider.Calibre(root)
    assert len(L.search("bee")) == 8 and len(L.search("bee", 3)) == 3 and len(L.search("bee", 20)) == 11     # ten new ones and The Beekeeper's Year
    assert len(L.wander(StubRng(0.9))[1]) == 8 and len(L.wander(StubRng(0.9), 5)[1]) == 5
