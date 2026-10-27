# Prompts e i18n

Todo texto voltado ao LLM — instruções dos agentes, descrições das ferramentas e
mensagens dos hooks — fica em arquivos YAML, não no código. Isso permite
localizar um app para outro idioma (ou trocar a persona) sem tocar no Python.

## Como funciona

O carregador mescla duas fontes:

1. **Padrões neutros em inglês** — embutidos no Semente
   (`semente/configs/prompts/defaults/`). São livres de domínio e sempre estão
   presentes.
2. **Os prompts do seu app** — o diretório definido pelo `prompts_dir` do
   manifesto (ou `language`), com padrão `<cwd>/prompts`.

Qualquer chave ausente nos arquivos do seu app é preenchida pelo padrão neutro,
com um aviso. Chaves que você adiciona e que não existem no padrão (ex.:
ferramentas do domínio) são incluídas como estão.

## Estrutura de arquivos

```
prompts/
├── agents.yml     # {agent_tag: {name, role, instructions, ...}}
├── tools.yml      # {component: {tool_name: {description: ...}}}
└── hooks.yml      # {group: {key: text}}
```

## `agents.yml`

Uma tag de nível superior por agente. A tag `single_agent` conduz o seu
assistente principal:

```yaml
single_agent:
  name: "Assistente de Suporte"
  instructions_default: |
    Você é um assistente de suporte prestativo.
    Responda de forma concisa, no idioma do usuário.
  persona_fallback: |
    Perfil geral: um novo usuário. Adote um tom acolhedor e prestativo.
```

O framework também formata alguns placeholders de onboarding: `{app_name}` e
`{terms_closed_note}` em `welcoming_agent.instructions_persona`, e
`{terms_link_instruction}` / `{terms_text}` em `welcoming_agent.instructions`
(o conteúdo dos termos vem de `features.terms-acceptance` — veja
[Manifesto](manifest.md)).

Agentes dinâmicos mantêm valores de tempo de execução no código (blocos de
contexto, texto da persona, propriedades candidatas); o YAML guarda os blocos de
template estáticos, e o Python os formata com `{placeholders}`.

## `tools.yml`

Descrições de ferramentas passadas ao decorador `@tool(description=...)` do
Semente (referenciadas no domínio com
`from semente.configs.prompts import get_tool_description`). Os grupos do próprio
framework (`onboarding_tools`, `persona_tools`, `tts_tools`, …) ficam nos padrões
embutidos; seu domínio adiciona os dele:

```yaml
my_domain_tools:
  lookup_order:
    description: |
      Busca um pedido pelo seu id.
      params:
          order_id (str): Identificador do pedido.
```

O `component` é o nome do arquivo da ferramenta, a chave é o nome da função.

## `hooks.yml`

Mensagens retornadas ou injetadas pelos hooks de validação:

```yaml
tool_hooks:
  missing_required_state: "A informação necessária ainda não está disponível."
  media_already_delivered: "Essa mídia já foi entregue nesta sessão."
```

## Localização

Para localizar um app, forneça um diretório `prompts/<language>/` (ou defina
`prompts_dir` explicitamente) com a mesma estrutura. Chaves ausentes recorrem aos
padrões neutros em inglês.

```yaml
# semente.yaml
language: pt-BR
```

O carregador então lê `prompts/pt-BR/agents.yml` (etc.) e o mescla sobre os
padrões.

## API

```python
from semente.configs.prompts import (
    get_agent_config,      # mapeamento completo de uma tag de agente
    get_agent_field,       # um campo de um agente
    get_tool_description,  # a descrição de uma ferramenta
    get_hook_texts,        # todos os textos de um grupo de hooks
    set_prompts_dir,       # aponta o carregador para um diretório (limpa o cache)
)
```
