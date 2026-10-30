"""Tool renames: old names still work (in TOOLS, in history), and past counts and firsts carry over to the new name."""
ALIASES = {"browse_library": "browse"}


def canonical(name):
    return ALIASES.get(name, name)
