"""Agent input assembly tests — the enriched-input seam.

Regression test for the "must send twice" bug: in the old workflow, sibling
parallel branches (summarization, feedback) polluted the shared step-output
registry with non-user text before the agent branch ran, so the agent's
input had to be read from the input step's output by name — never from
"the last output". In the Semente architecture the consolidated user
text is a plain value passed straight to ``_build_agent_input``, so the bug
class is structurally impossible; these tests pin that down.
"""

from semente.core.semente_agent import Semente
from semente.core.types import AgentSession
from semente.manifest import Manifest


def _agent() -> Semente:
    return Semente(
        agent=object(),
        welcoming_agent=object(),
        manifest=Manifest(name="test-app"),
    )


def _session(user_text: str) -> AgentSession:
    return AgentSession(user_id="u", session_id="s")


def test_agent_input_wraps_the_consolidated_user_text():
    agent = _agent()
    out = agent._build_agent_input(_session("s"), "qual a situação da pastagem?", {})
    assert out == "<input>\nqual a situação da pastagem?\n</input>"


def test_agent_input_is_only_user_text_no_sibling_pollution():
    agent = _agent()
    state = {}
    out = agent._build_agent_input(_session("s"), "qual a situação da pastagem?", state)
    assert "level" not in out
    # The history block stash is always written, even when empty.
    assert state["history_context"] == ""


def test_agent_input_empty_text_is_empty_string():
    agent = _agent()
    out = agent._build_agent_input(_session("s"), "", {})
    assert out == ""


def test_agent_input_stashes_history_block_in_state():
    agent = _agent()
    session = AgentSession(
        user_id="u",
        session_id="s",
        runs=[
            {"user": "olá", "assistant": "oi!"},
            {"user": "tudo bem?", "assistant": "tudo!"},
        ],
    )
    state = {"summary_state": {"runs_count": 2}}
    out = agent._build_agent_input(session, "próxima pergunta", state)
    assert "<iterações>" in state["history_context"]
    assert "[Iteração 0]" in state["history_context"]
    assert "olá" in state["history_context"]
    # The user text goes in the input; the history stays in the stash.
    assert "<input>\npróxima pergunta\n</input>" in out
    assert "olá" not in out


if __name__ == "__main__":
    test_agent_input_wraps_the_consolidated_user_text()
    test_agent_input_is_only_user_text_no_sibling_pollution()
    test_agent_input_empty_text_is_empty_string()
    test_agent_input_stashes_history_block_in_state()
    print("Agent input tests OK")