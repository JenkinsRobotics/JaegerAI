"""Person index — profiles of people the agent knows (distinct from characters).

The agent builds + expands these over time; access feeds the trust model.
"""

import pathlib
import tempfile

from jaeger_os.core import people
from jaeger_os.core.instance.instance import InstanceLayout


def _layout() -> InstanceLayout:
    return InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))


def test_upsert_creates_then_merges() -> None:
    layout = _layout()
    p = people.upsert_person(layout, name="Jonathan", access="admin",
                             channel="telegram", handle="8777030623",
                             like="coffee", note="created the bots")
    assert p.id == "jonathan" and p.name == "Jonathan" and p.access == "admin"
    assert "8777030623" in p.handles["telegram"]
    assert "coffee" in p.likes and "created the bots" in p.facts

    p2 = people.upsert_person(layout, name="Jonathan", like="tea",
                              channel="discord", handle="42")
    assert set(p2.likes) == {"coffee", "tea"}                 # appended, deduped
    assert "42" in p2.handles["discord"] and "8777030623" in p2.handles["telegram"]
    assert p2.access == "admin"                               # preserved across merge


def test_find_by_name_id_and_alias() -> None:
    layout = _layout()
    people.upsert_person(layout, name="Bob Smith")
    assert people.find_by_name(layout, "Bob Smith").id == "bob_smith"
    assert people.find_by_name(layout, "bob_smith") is not None      # by id
    p = people.find_by_name(layout, "bob_smith")
    p.aliases.append("Bobby"); people.save_person(layout, p)
    assert people.find_by_name(layout, "bobby") is not None          # by alias
    assert people.find_by_name(layout, "nobody") is None


def test_find_by_handle_and_admins_for_channel() -> None:
    layout = _layout()
    people.upsert_person(layout, name="Owner", access="admin",
                         channel="telegram", handle="55")
    people.upsert_person(layout, name="Guest", access="member",
                         channel="telegram", handle="99")
    assert people.find_by_handle(layout, "telegram", "55").name == "Owner"
    assert people.find_by_handle(layout, "telegram", "99").name == "Guest"
    assert people.admins_for_channel(layout, "telegram") == {"55"}   # only the admin
    assert people.admins_for_channel(layout, "discord") == set()


def test_people_tools_registered() -> None:
    from jaeger_os.agent.schemas import tool_registry as R
    import jaeger_os.main as m
    m._register_builtins(object())
    names = {t.name for t in R.get_tools()}
    assert {"remember_person", "get_person", "list_people"} <= names
