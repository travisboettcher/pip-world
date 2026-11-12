import pytest


@pytest.fixture(autouse=True)
def pips_world_after_each_test():
    """A test that runs another world (a pack of its own, or an Agent made with WORLD_PACK) leaves Pip's world active again, whatever
    order the tests run in (mutation testing runs them in its own)."""
    yield
    from app import world_pack
    from app.config import Settings
    world_pack.set_active(world_pack.load(Settings()))
