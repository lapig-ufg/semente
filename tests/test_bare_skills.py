"""Skills on MyAgent — the pre-built engine-neutral skills module, natively.

Covers: ``load_skills`` accepting a list of paths (later wins, missing
tolerated), MyAgent taking a ``Skills`` object or a callable
``(run_context) -> Skills | None`` (the same pattern as instructions and
tools), ``_execute`` injecting the ``<skills_system>`` snippet + access
tools into every run, an end-to-end skill-tool call through the loop, and
``from_spec`` NOT re-injecting the framework's pre-baked skills.
"""

import json
import tempfile
from pathlib import Path

from semente.backends.base import AgentSpec
from semente.backends.bare import MyAgent
from semente.backends.bare.providers import Provider
from semente.backends.bare.providers.base import GenerateResult, ToolCall
from semente.skills import Skills, load_skills


class _FakeProvider(Provider):
    name = "fake"

    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def generate(self, system, message=None, model_id=None, tools=None, history=None):
        self.calls.append({"system": system, "tools": tools or [], "history": list(history or [])})
        return next(self.results)

    def user_turn(self, message):
        return {"role": "user", "content": message}

    def tool_results_turn(self, outputs):
        return [{"role": "tool", "outputs": outputs}]


def _skill_md(name, description, body):
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}"


def _make_skills(names=("ua-calculator",)) -> Skills:
    """Build a real ``Skills`` from a temp dir (the caller-side pattern)."""
    root = Path(tempfile.mkdtemp())
    for name in names:
        d = root / name
        d.mkdir()
        (d / "SKILL.md").write_text(_skill_md(name, f"{name} skill", f"# {name} instructions"), encoding="utf-8")
    skills = load_skills(str(root))
    assert skills is not None
    return skills


# ---- load_skills: list-of-paths support ---------------------------------------


def test_load_skills_single_dir_still_works():
    root = Path(tempfile.mkdtemp())
    d = root / "alpha"
    d.mkdir()
    (d / "SKILL.md").write_text(_skill_md("alpha", "a", "# body"), encoding="utf-8")
    skills = load_skills(str(root))
    assert skills is not None
    assert "alpha" in skills.get_system_prompt_snippet()


def test_load_skills_list_of_dirs_merges():
    root_a = Path(tempfile.mkdtemp())
    root_b = Path(tempfile.mkdtemp())
    for root, name in ((root_a, "alpha"), (root_b, "beta")):
        d = root / name
        d.mkdir()
        (d / "SKILL.md").write_text(_skill_md(name, f"{name} skill", f"# {name}"), encoding="utf-8")
    skills = load_skills([str(root_a), str(root_b)])
    assert skills is not None
    snippet = skills.get_system_prompt_snippet()
    assert "alpha" in snippet and "beta" in snippet


def test_load_skills_list_later_path_wins_on_collision():
    root_a = Path(tempfile.mkdtemp())
    root_b = Path(tempfile.mkdtemp())
    for root, body in ((root_a, "# first"), (root_b, "# from the later path")):
        d = root / "shared"
        d.mkdir()
        (d / "SKILL.md").write_text(_skill_md("shared", "s", body), encoding="utf-8")
    skills = load_skills([str(root_a), str(root_b)])
    snippet = skills.get_system_prompt_snippet()
    assert snippet.count("<name>shared</name>") == 1
    content = skills.get_tools()[0].func("shared")
    assert "from the later path" in content


def test_load_skills_missing_and_empty_paths_return_none():
    assert load_skills("/does/not/exist") is None
    assert load_skills(["/does/not/exist", "/also/missing"]) is None


# ---- MyAgent: Skills | Callable -----------------------------------------------


def test_agent_with_static_skills_object_injects_snippet_and_tools():
    skills = _make_skills(("ua-calculator",))
    provider = _FakeProvider([GenerateResult(text="hi")])
    agent = MyAgent(instructions="be nice", provider=provider, skills=skills)

    assert agent.skills is skills  # held, not re-loaded
    agent.chat("hello")

    system = provider.calls[0]["system"]
    assert "<skills_system>" in system
    assert "be nice" in system  # base instructions still first
    tool_names = [t.name for t in provider.calls[0]["tools"]]
    assert set(tool_names) >= {"get_skill_instructions", "get_skill_reference", "get_skill_script"}


def test_agent_without_skills_leaves_instructions_and_tools_alone():
    provider = _FakeProvider([GenerateResult(text="hi")])
    agent = MyAgent(instructions="be nice", provider=provider)

    agent.chat("hello")

    assert "<skills_system>" not in provider.calls[0]["system"]
    assert provider.calls[0]["tools"] == []


def test_skill_tool_call_round_trips_through_the_loop():
    skills = _make_skills(("ua-calculator",))
    provider = _FakeProvider([
        GenerateResult(
            tool_calls=[ToolCall(id="c1", name="get_skill_instructions", args={"skill_name": "ua-calculator"})],
            turn="model-turn",
        ),
        GenerateResult(text="Here is how to compute UA."),
    ])
    agent = MyAgent(instructions="s", provider=provider, skills=skills)

    text = agent.chat("how do I compute UA?")

    assert text == "Here is how to compute UA."
    outputs = provider.calls[1]["history"][2]["outputs"]
    payload = json.loads(outputs[0][1])
    assert payload["skill_name"] == "ua-calculator"
    assert "ua-calculator instructions" in payload["instructions"]


def test_agent_skills_callable_resolves_against_run_state():
    """A skills factory sees the run's session_state — skills picked per
    run, the same pattern as dynamic tools/instructions."""
    loaded = _make_skills(("alpha",))
    calls = []
    provider = _FakeProvider([GenerateResult(text="no"), GenerateResult(text="yes")])
    agent = MyAgent(
        instructions="s",
        provider=provider,
        skills=lambda ctx: (calls.append(ctx.session_state), loaded if ctx.session_state.get("use_skills") else None)[1],
    )

    agent.chat("hi", session_state={"use_skills": False})
    assert "<skills_system>" not in provider.calls[0]["system"]  # None -> skipped

    agent.chat("hi", session_state={"use_skills": True})
    system = provider.calls[1]["system"]
    assert "<skills_system>" in system and "alpha" in system
    assert calls[0] == {"use_skills": False} and calls[1] == {"use_skills": True}


def test_agent_skills_callable_returning_non_skills_is_ignored():
    provider = _FakeProvider([GenerateResult(text="ok")])
    agent = MyAgent(instructions="s", provider=provider, skills=lambda ctx: "not skills")

    agent.chat("hi")

    assert "<skills_system>" not in provider.calls[0]["system"]


def test_agent_skills_callable_failure_degrades_to_no_skills():
    def boom(ctx):
        raise ValueError("factory bug")

    provider = _FakeProvider([GenerateResult(text="still works")])
    agent = MyAgent(instructions="s", provider=provider, skills=boom)

    text = agent.chat("hi")

    assert text == "still works"
    assert "<skills_system>" not in provider.calls[0]["system"]


def test_from_spec_does_not_double_inject_framework_skills():
    """The framework's _with_skills bakes snippet + tools into the spec
    before the backend builds; from_spec must not re-inject spec.skills."""
    skills = _make_skills(("ua-calculator",))
    snippet = skills.get_system_prompt_snippet()
    skill_tools = skills.get_tools()

    spec = AgentSpec(
        name="t",
        instructions="base instructions" + "\n\n" + snippet,  # pre-baked by _with_skills
        tools=list(skill_tools),
        skills=skills,  # still on the spec — must be ignored by from_spec
    )
    provider = _FakeProvider([GenerateResult(text="ok")])
    agent = MyAgent.from_spec(spec)
    agent.provider = provider  # swap in the fake after construction

    agent.chat("hi")

    system = provider.calls[0]["system"]
    assert system.count("<skills_system>") == 1  # no double injection
    assert [t.name for t in provider.calls[0]["tools"]] == [
        "get_skill_instructions", "get_skill_reference", "get_skill_script",
    ]


if __name__ == "__main__":
    test_load_skills_single_dir_still_works()
    test_load_skills_list_later_path_wins_on_collision()
    test_load_skills_missing_and_empty_paths_return_none()
    test_agent_with_static_skills_object_injects_snippet_and_tools()
    test_agent_without_skills_leaves_instructions_and_tools_alone()
    test_skill_tool_call_round_trips_through_the_loop()
    test_agent_skills_callable_resolves_against_run_state()
    test_agent_skills_callable_returning_non_skills_is_ignored()
    test_agent_skills_callable_failure_degrades_to_no_skills()
    test_from_spec_does_not_double_inject_framework_skills()
    print("Skills on MyAgent tests OK")