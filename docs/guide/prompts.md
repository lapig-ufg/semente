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
  name: "Pasto Legal"
  instructions_default: |
    You are the official assistant of Pasto Legal.
    Answer concisely, in the user's language.
  persona_fallback: |
    General profile: rural producer. Adopt a warm tone.
  registrations_empty: |
    *No property registered at the moment.*
```

Dynamic agents keep runtime values in code (context blocks, persona text,
candidate properties); the YAML holds the static template blocks, and Python
formats them in with `{placeholders}`.

## `tools.yml`

Tool descriptions passed to the Semente `@tool(description=...)` decorator
(referenced from the domain with
`from semente.configs.prompts import get_tool_description`):

```yaml
analysis_tools:
  generate_biomass_image:
    description: |
      Generates a thematic map of biomass over the property boundaries.
      params:
          feature_id (str): Identifier of the registered feature.
```

The `component` is the tool file name, the key is the function name.

## `hooks.yml`

Messages returned or injected by validation hooks:

```yaml
pre_hooks:
  unauthorized_production: "The user is not authorized to use the system."
tool_hooks:
  no_property_selected: "No property selected. Ask the user to provide one."
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
