from app.jellyfin.tags import reconcile_movie_tags

class FakeClient:
    def __init__(self, tags): self.tags=set(tags); self.added=set(); self.removed=set()
    def item_tags(self, _): return list(self.tags)
    def add_tags(self, _, tags): self.added |= tags
    def remove_tags(self, _, tags): self.removed |= tags

class FakeUpdateClient:
    def __init__(self, tags): self.tags=set(tags); self.updated_tags=None
    def item_tags(self, _): return list(self.tags)
    def update_tags(self, _, tags): self.updated_tags = set(tags); self.tags = set(tags)


def test_tags_are_projected_idempotently():
    client=FakeClient({"user tag", "CZ Audio", "OTHER Audio"})
    changes=reconcile_movie_tags(client, movie_id="one", languages=["cs", "en"])
    assert client.added == {"EN Audio"}
    assert client.removed == {"OTHER Audio"}
    assert [(change.name, change.add) for change in changes] == [("EN Audio", True), ("OTHER Audio", False)]


def test_update_tags_preserves_unrelated_tags():
    client = FakeUpdateClient({"Action", "Drama", "CZ Audio", "OTHER Audio"})
    changes = reconcile_movie_tags(client, movie_id="one", languages=["cs", "en"])
    assert client.updated_tags == {"Action", "Drama", "CZ Audio", "EN Audio"}
    assert [(change.name, change.add) for change in changes] == [("EN Audio", True), ("OTHER Audio", False)]


def test_update_tags_no_op_when_tags_match():
    client = FakeUpdateClient({"Action", "CZ Audio", "EN Audio"})
    changes = reconcile_movie_tags(client, movie_id="one", languages=["cs", "en"])
    assert client.updated_tags is None
    assert changes == []
