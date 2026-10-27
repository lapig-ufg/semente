---
layout: home

hero:
  name: Semente
  text: Uma orquestração multiagente declarativa para monitoramento do uso da terra e dados ambientais.
  tagline: Cultive um assistente de IA especializado a partir de uma única semente — ferramentas, conhecimento e prompts.
  image:
    src: /logo.svg
    alt: Semente
  actions:
    - theme: brand
      text: Começar
      link: /pt/guide/getting-started
    - theme: alt
      text: Implantar o App de Exemplo
      link: /pt/deployment/toy-app

features:
  - icon: 🌱
    title: Um domínio, um app
    details: Forneça um DomainSpec (ferramentas + conhecimento + skills) e um manifesto semente.yaml. O framework monta o agente e os canais.
  - icon: 🧠
    title: Pipeline multiagente
    details: Onboarding em etapas, ciclo de feedback/persona com captura de DPO, sumarização e guardrails de entrada plugáveis — tudo neutro quanto ao domínio e guiado por configuração.
  - icon: 💬
    title: WhatsApp e Streamlit
    details: Entregue no celular do produtor pelo WhatsApp ou depure em uma interface Streamlit. Os canais são plugáveis.
  - icon: 🌍
    title: Prompts com i18n
    details: Instruções dos agentes e descrições das ferramentas ficam em YAML, com sobrescritas por idioma e um fallback neutro em inglês.
---

## O que é o Semente?

**Semente** — construa pipelines de IA multiagente e
canais conversacionais a partir de puro conhecimento de domínio — sem
dependência de framework.

O Semente mantém o motor neutro quanto ao domínio e permite cultivar um novo
assistente fornecendo um **domínio**: as ferramentas, a base de conhecimento, as
skills e os prompts que tornam o seu app específico.

> *O Pasto Legal foi a primeira semente.*

## Como funciona

```
Usuário (WhatsApp / Streamlit)
        │
        ▼
   Harness (pipeline de objeto único)
    ├── Pré-processamento da entrada (mídia → texto, geo → GeoJSON)
    ├── Cadeia de guardrails (plugável: oculta ou bloqueia)
    ├── Portão de onboarding (persona; termos opcionais)
    ├── Sumarização, ciclo de feedback e então o seu agente
    ├── Remediação (pedido de desculpas no lugar de uma resposta frustrante)
    └── Finalização da saída (TTS)
        │
        ▼
   Seu domínio (ferramentas, conhecimento, skills, prompts)
```

## Início rápido

```bash
pip install semente-agents
```

```python
from semente.build import build_app

app = build_app("semente.yaml")  # app FastAPI (webhook do WhatsApp)
```

Veja [Primeiros Passos](/pt/guide/getting-started) para o passo a passo
completo, ou [Implantar o App de Exemplo](/pt/deployment/toy-app) para um
exemplo executável.
