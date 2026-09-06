"""Strands graph (ROADMAP DD1, DD2).

The governing rule: every node is a real thing. The reference mockup is a design
with invented readings, and a HUD that renders plausible fiction is worse than an
empty one. These tests exist mostly to hold that line.
"""

from unittest.mock import MagicMock

from strands import build_strands


def _memory(entries):
    store = MagicMock()
    store.get_important.return_value = entries
    return store


def _team(agents):
    team = MagicMock()
    team.snapshot.return_value = {"agents": agents}
    return team


# --- nothing in, nothing out --------------------------------------------------------

def test_no_sources_produces_an_empty_graph():
    graph = build_strands()
    assert graph["empty"] is True
    assert graph["nodes"] == []
    assert graph["links"] == []


def test_empty_sources_produce_no_invented_nodes():
    graph = build_strands(memory=_memory([]), team=_team([]), chat_ids=[])
    assert graph["empty"] is True
    assert graph["counts"]["nodes"] == 0


# --- real state becomes real nodes ---------------------------------------------------

def test_memories_become_nodes():
    graph = build_strands(memory=_memory([
        {"topic": "search freshness", "content": "recency beats parametric knowledge"},
    ]))
    assert graph["counts"]["nodes"] == 1
    node = graph["nodes"][0]
    assert node["kind"] == "memory"
    assert node["label"] == "search freshness"


def test_agents_become_nodes_carrying_their_goal():
    graph = build_strands(team=_team([
        {"agent_id": "a1", "name": "research", "goal": "find current sources"},
    ]))
    node = graph["nodes"][0]
    assert node["kind"] == "agent"
    assert "current sources" in node["detail"]


def test_every_node_has_somewhere_to_go():
    """A node the user cannot open is a decoration, not information."""
    graph = build_strands(
        memory=_memory([{"topic": "t", "content": "some real content here"}]),
        team=_team([{"agent_id": "a1", "name": "n", "goal": "a genuine goal"}]),
        chat_ids=["default"],
    )
    assert all(n["target"] for n in graph["nodes"])


def test_an_agent_with_no_goal_says_so_rather_than_showing_blank():
    graph = build_strands(team=_team([{"agent_id": "a1", "name": "idle", "goal": ""}]))
    assert graph["nodes"][0]["detail"] == "no goal set"


# --- links must mean something --------------------------------------------------------

def test_shared_vocabulary_creates_a_strand():
    graph = build_strands(
        memory=_memory([{"topic": "recency ranking", "content": "search freshness matters"}]),
        team=_team([{"agent_id": "a1", "name": "worker",
                     "goal": "improve recency ranking for search freshness"}]),
    )
    assert graph["counts"]["links"] == 1
    assert len(graph["links"][0]["shared"]) >= 2


def test_unrelated_items_are_not_linked():
    """A graph where everything connects to everything conveys nothing."""
    graph = build_strands(
        memory=_memory([{"topic": "guitar tuning", "content": "standard tuning is EADGBE"}]),
        team=_team([{"agent_id": "a1", "name": "worker",
                     "goal": "migrate the payment database schema"}]),
    )
    assert graph["counts"]["links"] == 0


def test_a_single_shared_word_is_not_enough():
    graph = build_strands(
        memory=_memory([{"topic": "database", "content": "postgres tuning notes"}]),
        team=_team([{"agent_id": "a1", "name": "w", "goal": "write database docs"}]),
    )
    # "database" alone should not imply a real connection.
    assert graph["counts"]["links"] == 0


def test_common_words_do_not_create_links():
    """Stopwords must not manufacture connections between unrelated ideas."""
    graph = build_strands(
        memory=_memory([{"topic": "a", "content": "this is the thing that we have to do"}]),
        team=_team([{"agent_id": "a1", "name": "w", "goal": "we have to do the other thing"}]),
    )
    assert graph["counts"]["links"] == 0


def test_link_weight_reflects_how_much_is_shared():
    graph = build_strands(
        memory=_memory([{"topic": "recency ranking freshness",
                         "content": "search recency ranking freshness"}]),
        team=_team([{"agent_id": "a1", "name": "w",
                     "goal": "recency ranking freshness search"}]),
    )
    assert graph["links"][0]["weight"] >= 3


# --- a broken subsystem must not take the HUD down --------------------------------------

def test_a_broken_memory_store_does_not_break_the_graph():
    store = MagicMock()
    store.get_important.side_effect = RuntimeError("disk gone")
    graph = build_strands(memory=store, chat_ids=["default"])
    assert graph["counts"]["nodes"] == 1  # the chat still appears


def test_a_broken_team_does_not_break_the_graph():
    team = MagicMock()
    team.snapshot.side_effect = RuntimeError("boom")
    graph = build_strands(team=team, chat_ids=["default"])
    assert graph["counts"]["nodes"] == 1


def test_counts_report_what_each_source_contributed():
    graph = build_strands(
        memory=_memory([{"topic": "t", "content": "c"}]),
        chat_ids=["default", "second"],
    )
    assert graph["counts"]["by_source"]["memory"] == 1
    assert graph["counts"]["by_source"]["chats"] == 2
