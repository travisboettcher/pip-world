"""Running module code (docs/DESIGN-modules.md, "The sandbox").

`check` reads a module's source before it ever runs and says, in words its author can act on, what isn't allowed. `run` executes one hook
in a fresh Python subprocess with resource limits, restricted builtins and an import allowlist, passing JSON in and taking JSON out.

The real boundary is the `pip-runner` container (no network, read-only, unprivileged). These checks make mistakes fail early and
readably; they are not what keeps the world safe.
"""
import ast
import asyncio
import json
import os
import sys

IMPORTS = ("math", "random", "itertools", "functools", "collections", "dataclasses", "json", "re", "datetime", "statistics", "heapq", "bisect")
FORBIDDEN_NAMES = frozenset({"eval", "exec", "compile", "open", "globals", "locals", "vars", "getattr", "setattr", "delattr", "input",
                             "breakpoint", "memoryview", "help", "exit", "quit", "__import__", "type", "super", "object"})
FORBIDDEN_ATTRS = frozenset({"format", "format_map"})        # str.format can reach attributes the checks below forbid
SOURCE_MAX = 64_000                                         # room for a feature as big as crafting
CPU_SECONDS, MEMORY_MB, WALL_SECONDS, OUTPUT_MAX = 1, 512, 3.0, 64_000


class Rejected(ValueError):
    """The code can't run; the message says what to change."""


def check(source: str) -> ast.Module:
    """Parse and check a module's source; raises Rejected with the first problem found."""
    if not isinstance(source, str) or not source.strip():
        raise Rejected("the code is empty")
    if len(source) > SOURCE_MAX:
        raise Rejected(f"the code is too long ({len(source)} characters; at most {SOURCE_MAX})")
    try:
        tree = ast.parse(source, "<module>")
    except SyntaxError as e:
        raise Rejected(f"line {e.lineno}: {e.msg}") from None
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in IMPORTS:
                    raise Rejected(f"line {line}: `import {a.name}` isn't allowed; you may import {', '.join(IMPORTS)}")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in IMPORTS:
                raise Rejected(f"line {line}: `from {node.module or '.'} import` isn't allowed; you may import {', '.join(IMPORTS)}")
        elif isinstance(node, ast.Name) and (node.id in FORBIDDEN_NAMES or node.id.startswith("__")):
            raise Rejected(f"line {line}: `{node.id}` isn't allowed")
        elif isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in FORBIDDEN_ATTRS):
            raise Rejected(f"line {line}: `.{node.attr}` isn't allowed" + ("; use an f-string" if node.attr in FORBIDDEN_ATTRS else ""))
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            raise Rejected(f"line {line}: `{type(node).__name__.lower()}` isn't allowed; keep what lasts in the state you return")
    return tree


# The child: restricted builtins, an import allowlist, one hook called with one JSON argument. Runs with -I -S (no site, no user paths).
CHILD = r'''
import builtins, json, resource, sys, traceback
IMPORTS = set(sys.argv[1].split(","))
CPU, MEMORY = int(sys.argv[2]), int(sys.argv[3])
resource.setrlimit(resource.RLIMIT_CPU, (CPU, CPU))          # the limits, set here before any module code runs
resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))            # no files written
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))              # no core dump when the CPU limit stops it: it would be slow and big
SAFE = ("abs all any bool dict divmod enumerate filter float frozenset hash int isinstance len list map max min next pow range repr "
        "reversed round set slice sorted str sum tuple zip iter callable chr ord bin hex oct abs property staticmethod classmethod "
        "Exception ValueError KeyError TypeError IndexError ZeroDivisionError ArithmeticError LookupError StopIteration RuntimeError "
        "AssertionError NotImplementedError True False None").split()
real_import = builtins.__import__
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name.split(".")[0] not in IMPORTS:
        raise ImportError(f"import {name} isn't allowed")
    return real_import(name, globals, locals, fromlist, level)
for m in IMPORTS:  # load the allowed modules (and what they need) before anything is locked down
    real_import(m)
box = {n: getattr(builtins, n) for n in SAFE if hasattr(builtins, n)}
box["__import__"] = guarded_import
box["__build_class__"] = builtins.__build_class__
def out(obj):
    sys.__stdout__.write(json.dumps(obj)); sys.__stdout__.flush()
try:
    req = json.loads(sys.stdin.read())
    code = compile(req["source"], "<module>", "exec")
    ns = {"__builtins__": box, "__name__": "module"}
    exec(code, ns)
    fn = ns.get(req["hook"])
    if not callable(fn):
        out({"ok": True, "missing": True})
    else:
        res = fn(req["ctx"])
        res = {} if res is None else res
        if not isinstance(res, dict):
            out({"ok": False, "error": f"{req['hook']} must return a dict (or nothing), not {type(res).__name__}"})
        else:
            out({"ok": True, "result": res})
except BaseException as e:
    tb = [f for f in traceback.extract_tb(e.__traceback__) if f.filename == "<module>"]
    where = f"line {tb[-1].lineno}: " if tb else ""
    try:
        out({"ok": False, "error": f"{where}{type(e).__name__}: {e}"[:400]})
    except BaseException:
        out({"ok": False, "error": f"{where}{type(e).__name__}"})
'''


def spawn_args() -> list[str]:
    """The child's command line: no user site or environment paths (-I), no site module (-S), the allowlist and the limits."""
    return [sys.executable, "-I", "-S", "-c", CHILD, ",".join(IMPORTS), str(CPU_SECONDS), str(MEMORY_MB * 2**20)]


async def run(source: str, hook: str, ctx: dict) -> dict:
    """Run one hook. Returns {"ok": True, "result": {...}} (or "missing": True if the module has no such hook), or {"ok": False, "error": "..."}."""
    try:
        check(source)
    except Rejected as e:
        return {"ok": False, "error": str(e)}
    payload = json.dumps({"source": source, "hook": hook, "ctx": ctx}).encode()
    proc = await asyncio.create_subprocess_exec(*spawn_args(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.DEVNULL, env={"PATH": os.environ.get("PATH", "")}, cwd="/")
    try:
        out, _ = await asyncio.wait_for(proc.communicate(payload), WALL_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"ok": False, "error": f"it took longer than {WALL_SECONDS:g} seconds"}
    if len(out) > OUTPUT_MAX:
        return {"ok": False, "error": f"it returned too much ({len(out)} bytes; at most {OUTPUT_MAX})"}
    if not out:
        return {"ok": False, "error": "it used more than its share of time" if proc.returncode in (-24, -9) else "it stopped without answering"}
    try:
        res = json.loads(out)
    except ValueError:
        return {"ok": False, "error": "what it returned isn't JSON (only plain numbers, strings, lists and dicts)"}
    return res if isinstance(res, dict) and "ok" in res else {"ok": False, "error": "it returned something unreadable"}
