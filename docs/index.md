---
layout: home

hero:
  name: Semente
  text: Multi-agent AI chat for land use
  tagline: Grow a domain-specific AI assistant from a single seed — tools, knowledge, and prompts.
  image:
    src: /semente/logo.svg
    alt: Semente
  actions:
    - theme: brand
      text: Get Started
      link: /guide/getting-started
    - theme: alt
      text: Deploy the Toy App
      link: /deployment/toy-app

features:
  - icon: 🌱
    title: One domain, one app
    details: Supply a DomainSpec (tools + knowledge + skills) and a semente.yaml manifest. The framework assembles the agent, and channels.
  - icon: 🧠
    title: Multi-agent pipeline
    details: Onboarding, intent routing, feedback/persona loop, summarization, and PII guardrails — all domain-neutral and config-driven.
  - icon: 💬
    title: WhatsApp & Streamlit
    details: Ship to farmers' phones over WhatsApp, or debug in a Streamlit UI. Channels are pluggable.
  - icon: 🌍
    title: i18n prompts
    details: Agent instructions and tool descriptions live in YAML, with per-language overrides and a neutral English fallback.
---

## What is Semente?

**Semente** (Portuguese for *seed*) is a multi-agent AI chat framework for land
use and agriculture. It was extracted from
[Pasto Legal](https://github.com/lapig-ufg/pasto-legal) (LAPIG/UFG) — an AI
assistant that delivers satellite-based pasture diagnostics to Brazilian
ranchers over WhatsApp.

Semente keeps the domain-neutral engine and lets you grow a new assistant by
supplying a **domain**: the tools, knowledge base, skills, and prompts that make
your app specific.

> *Pasto Legal was the first seed.*

## How it works

```
User (WhatsApp / Streamlit)
        │
        ▼
    Semente (single-object pipeline)
    ├── Input pre-processing (media → text, geo → GeoJSON)
    ├── PII guardrail
    ├── Onboarding check (terms)
    ├── Summarization + feedback loop + your agent
    ├── Remediation merge
    └── Output finalization (TTS)
        │
        ▼
   Your domain (tools, knowledge, skills, prompts)
```

## Quickstart

```bash
pip install semente-agents
```

```python
from semente.build import build_app

app = build_app("semente.yaml")  # FastAPI app (WhatsApp webhook)
```

See [Getting Started](/guide/getting-started) for the full walkthrough, or
[Deploy the Toy App](/deployment/toy-app) for a runnable example.
