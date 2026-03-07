"""Tests for dial_memory.provider."""

import json

from strawpot.memory.protocol import MemoryKind, MemoryProvider, RememberResult

from dial.provider import DialMemoryProvider
from dial.storage import knowledge_path, read_jsonl, role_knowledge_path


def _make_provider(tmp_path):
    return DialMemoryProvider(
        {
            "storage_dir": str(tmp_path / "project"),
            "global_storage_dir": str(tmp_path / "global"),
        }
    )


# -- Protocol compliance ------------------------------------------------------


def test_satisfies_protocol():
    p = DialMemoryProvider()
    assert isinstance(p, MemoryProvider)
    assert p.name == "dial"


# -- remember -----------------------------------------------------------------


def test_remember_accepted(tmp_path):
    p = _make_provider(tmp_path)
    r = p.remember(
        session_id="s1", agent_id="a1", role="impl",
        content="Uses pytest", scope="project",
    )
    assert r.status == "accepted"
    assert r.entry_id.startswith("k_")


def test_remember_duplicate(tmp_path):
    p = _make_provider(tmp_path)
    p.remember(
        session_id="s1", agent_id="a1", role="impl",
        content="Uses pytest", scope="project",
    )
    r = p.remember(
        session_id="s1", agent_id="a1", role="impl",
        content="Uses pytest", scope="project",
    )
    assert r.status == "duplicate"


def test_remember_global_scope(tmp_path):
    p = _make_provider(tmp_path)
    p.remember(
        session_id="s1", agent_id="a1", role="impl",
        content="Always lint", scope="global",
    )
    entries = read_jsonl(knowledge_path(tmp_path / "global"))
    assert len(entries) == 1
    assert entries[0]["content"] == "Always lint"


def test_remember_role_scope(tmp_path):
    p = _make_provider(tmp_path)
    p.remember(
        session_id="s1", agent_id="a1", role="impl",
        content="Check migrations", scope="role",
    )
    entries = read_jsonl(role_knowledge_path(tmp_path / "project", "impl"))
    assert len(entries) == 1
    assert entries[0]["content"] == "Check migrations"


def test_remember_with_keywords(tmp_path):
    p = _make_provider(tmp_path)
    p.remember(
        session_id="s1", agent_id="a1", role="impl",
        content="Stripe needs keys", keywords=["stripe", "payment"],
        scope="project",
    )
    entries = read_jsonl(knowledge_path(tmp_path / "project"))
    assert entries[0]["keywords"] == ["stripe", "payment"]


# -- dump ---------------------------------------------------------------------


def test_dump_appends_em(tmp_path):
    p = _make_provider(tmp_path)
    receipt = p.dump(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="Build login",
        status="success", output="Done building login form",
    )
    assert len(receipt.em_event_ids) == 1
    assert receipt.em_event_ids[0].startswith("evt_")

    em_file = tmp_path / "project" / "em" / "s1.jsonl"
    events = read_jsonl(em_file)
    assert len(events) == 1
    assert events[0]["event_type"] == "AGENT_RESULT"
    assert events[0]["data"]["status"] == "success"


def test_dump_truncates_long_output(tmp_path):
    p = _make_provider(tmp_path)
    long_output = "x" * 1000
    p.dump(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="task",
        status="success", output=long_output,
    )
    em_file = tmp_path / "project" / "em" / "s1.jsonl"
    events = read_jsonl(em_file)
    assert len(events[0]["data"]["summary"]) == 500


# -- get ----------------------------------------------------------------------


def test_get_empty(tmp_path):
    p = _make_provider(tmp_path)
    result = p.get(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="do something",
    )
    assert result.context_cards == []
    assert result.sources_used == []


def test_get_returns_sm_cards(tmp_path):
    p = _make_provider(tmp_path)
    p.remember(
        session_id="s1", agent_id="a1", role="impl",
        content="Uses pytest", scope="project",
    )
    result = p.get(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="anything",
    )
    sm_cards = [c for c in result.context_cards if c.kind == MemoryKind.SM]
    assert len(sm_cards) == 1
    assert "Uses pytest" in sm_cards[0].content
    assert "sm" in result.sources_used


def test_get_returns_rm_cards_when_matching(tmp_path):
    p = _make_provider(tmp_path)
    p.remember(
        session_id="s1", agent_id="a1", role="impl",
        content="Stripe needs keys",
        keywords=["stripe", "payment"],
        scope="project",
    )
    result = p.get(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="Fix payment stripe integration",
    )
    rm_cards = [c for c in result.context_cards if c.kind == MemoryKind.RM]
    assert len(rm_cards) == 1
    assert "rm" in result.sources_used


def test_get_excludes_rm_when_not_matching(tmp_path):
    p = _make_provider(tmp_path)
    p.remember(
        session_id="s1", agent_id="a1", role="impl",
        content="Stripe needs keys",
        keywords=["stripe", "payment"],
        scope="project",
    )
    result = p.get(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="Write documentation for auth module",
    )
    rm_cards = [c for c in result.context_cards if c.kind == MemoryKind.RM]
    assert len(rm_cards) == 0


def test_get_returns_em_cards(tmp_path):
    p = _make_provider(tmp_path)
    p.dump(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="Build login",
        status="success", output="Done",
    )
    result = p.get(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="Next task",
    )
    em_cards = [c for c in result.context_cards if c.kind == MemoryKind.EM]
    assert len(em_cards) == 1
    assert "em" in result.sources_used


def test_get_merges_all_scopes(tmp_path):
    p = _make_provider(tmp_path)
    p.remember(session_id="s1", agent_id="a1", role="impl",
               content="Global fact", scope="global")
    p.remember(session_id="s1", agent_id="a1", role="impl",
               content="Project fact", scope="project")
    p.remember(session_id="s1", agent_id="a1", role="impl",
               content="Role fact", scope="role")
    result = p.get(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="anything",
    )
    sm_cards = [c for c in result.context_cards if c.kind == MemoryKind.SM]
    assert len(sm_cards) == 1
    content = sm_cards[0].content
    assert "Global fact" in content
    assert "Project fact" in content
    assert "Role fact" in content


def test_get_deduplicates_across_scopes(tmp_path):
    p = _make_provider(tmp_path)
    p.remember(session_id="s1", agent_id="a1", role="impl",
               content="Same fact", scope="global")
    p.remember(session_id="s1", agent_id="a1", role="impl",
               content="Same fact", scope="project")
    result = p.get(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="anything",
    )
    sm_cards = [c for c in result.context_cards if c.kind == MemoryKind.SM]
    assert sm_cards[0].content.count("Same fact") == 1


def test_get_card_order_sm_rm_em(tmp_path):
    p = _make_provider(tmp_path)
    p.remember(session_id="s1", agent_id="a1", role="impl",
               content="Always fact", scope="project")
    p.remember(session_id="s1", agent_id="a1", role="impl",
               content="Payment info", keywords=["payment"], scope="project")
    p.dump(session_id="s1", agent_id="a1", role="impl",
           behavior_ref="text", task="prev", status="success", output="done")
    result = p.get(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="Fix payment bug",
    )
    kinds = [c.kind for c in result.context_cards]
    assert kinds == [MemoryKind.SM, MemoryKind.RM, MemoryKind.EM]


def test_get_budget_trimming(tmp_path):
    p = _make_provider(tmp_path)
    p.remember(session_id="s1", agent_id="a1", role="impl",
               content="Short fact", scope="project")
    p.dump(session_id="s1", agent_id="a1", role="impl",
           behavior_ref="text", task="task", status="success",
           output="A very long output " * 100)
    result = p.get(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="next",
        budget=50,
    )
    total = sum(len(c.content) for c in result.context_cards)
    assert total <= 50
