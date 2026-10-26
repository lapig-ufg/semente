# Prompts & i18n

All LLM-facing text — agent instructions, tool descriptions, and hook messages —
lives in YAML files, not in code. This lets you localize an app to another
language (or re-skin its persona) without touching Python.

## How it works

The loader merges two sources:

1. **Neutral English defaults** — bundled with Semente
   (`semente/configs/prompts/defaults/`). These are domain-free and always
   present.
2. **Your app's prompts** — the directory set by the manifest `prompts_dir`
   (or `language`), defaulting to `<cwd>/prompts`.

Any key missing from your app's files is filled from the neutral default, with a
warning. Keys you add that aren't in the default (e.g. domain tools) are
included as-is.

## File structure

```
prompts/
├── agents.yml     # {agent_tag: {name, role, instructions, ...}}
├── tools.yml      # {component: {tool_name: {description: ...}}}
└── hooks.yml      # {group: {key: text}}
```

## `agents.yml`

One top-level tag per agent. The `single_agent` tag drives your main assistant:

```yaml
single_agent:
  name: "Support Assistant"
  instructions_default: |
    You are a helpful support assistant.
    Answer concisely, in the user's language.
  persona_fallback: |
    General profile: a new user. Adopt a warm, helpful tone.
```

The framework also formats a few onboarding placeholders: `{app_name}` and
`{terms_closed_note}` in `welcoming_agent.instructions_persona`, and
`{terms_link_instruction}` / `{terms_text}` in `welcoming_agent.instructions`
(the terms content comes from `features.terms-acceptance` — see
[Manifest](manifest.md)).

Dynamic agents keep runtime values in code (context blocks, persona text,
candidate properties); the YAML holds the static template blocks, and Python
formats them in with `{placeholders}`.

## `tools.yml`

Tool descriptions passed to the Semente `@tool(description=...)` decorator
(referenced from the domain with
`from semente.configs.prompts import get_tool_description`). The framework's
own groups (`onboarding_tools`, `persona_tools`, `tts_tools`, …) live in the
bundled defaults; your domain adds its own groups:

```yaml
my_domain_tools:
  lookup_order:
    description: |
      Looks up an order by its id.
      params:
          order_id (str): Identifier of the order.
```

The `component` is the tool file name, the key is the function name.

## `hooks.yml`

Messages returned or injected by validation hooks:

```yaml
tool_hooks:
  missing_required_state: "The required information is not available yet."
  media_already_delivered: "That media was already delivered in this session."
```

## Localization

To localize an app, provide a `prompts/<language>/` directory (or set
`prompts_dir` explicitly) with the same structure. Missing keys fall back to the
neutral English defaults.

```yaml
# semente.yaml
language: pt-BR
```

The loader then reads `prompts/pt-BR/agents.yml` (etc.) and merges it over the
defaults.

## API

```python
from semente.configs.prompts import (
    get_agent_config,      # full mapping for one agent tag
    get_agent_field,       # one field of one agent
    get_tool_description,  # one tool's description
    get_hook_texts,        # all texts of one hook group
    set_prompts_dir,       # point the loader at a directory (clears cache)
)
```
