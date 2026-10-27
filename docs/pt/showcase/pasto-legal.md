# Pasto Legal — a primeira semente

O [Pasto Legal](https://github.com/lapig-ufg/pasto-legal) é a aplicação da qual
o Semente foi extraído. Ele entrega diagnósticos de pastagem baseados em
satélite a pecuaristas brasileiros pelo WhatsApp.

## O que ele faz

- 🛰️ **Monitoramento da saúde da pastagem** — biomassa, vigor da vegetação,
  idade da pastagem e mapas de uso/cobertura da terra a partir de imagens de
  satélite (Sentinel-2, MapBiomas).
- 🐄 **Capacidade de suporte** — taxas de lotação e capacidade de suporte ideal
  (UA/ha) usando a metodologia do LAPIG.
- 📋 **Cadastro de propriedades** — por código CAR/SICAR, coordenadas GPS ou
  link do Google Maps.
- 🌾 **Consultoria agronômica** — orientações validadas pela EMBRAPA sobre
  manejo de forrageiras e recuperação de pastagens.
- 🔊 **Respostas em voz** — relatórios em áudio narrados de volta pelo WhatsApp.

## Como se encaixa no Semente

O Pasto Legal é um app Semente. Seu pacote `domain/` fornece:

| Conceito do Semente | Implementação no Pasto Legal |
|---|---|
| `DomainSpec.tools` | `get_tools` — seleção dinâmica por estado de cadastro (pendente/final/padrão) |
| `DomainSpec.instructions` | `get_instructions` — máquina de estados do cadastro + persona + cadastros |
| `DomainSpec.knowledge` | `pasto_legal_kb` — documentos da EMBRAPA/pastagens indexados em um banco vetorial |
| `DomainSpec.skills` | `ua-calculator` — a skill de capacidade de suporte |
| `prompts_dir` | `domain/prompts` — textos de agentes/ferramentas/hooks em pt-BR |

O motor neutro quanto ao domínio (pipeline de agentes, canais
WhatsApp/Streamlit, guardrails de PII, ciclo de feedback/persona, TTS, carregador
de prompts com i18n) é exatamente o que virou o Semente.

## Arquitetura

```
Usuário (WhatsApp)
   │
   ▼
Harness
├── Pré-processamento da entrada (áudio/imagem → texto)
├── Guardrail de PII (ocultação de CPF/CNPJ/cartão/e-mail)
├── Verificação de onboarding (aceite dos termos)
├── Sumarização + ciclo de feedback + agente Pasto Legal
├── Mescla da remediação
└── Finalização da saída (TTS)
   │
   ▼
Domínio Pasto Legal
├── GEE / MapBiomas (análises de satélite)
├── SICAR (cadastro de propriedades)
├── Clima (Open-Meteo)
└── Base de conhecimento da EMBRAPA
```

## Licença

O Pasto Legal é GPL-3.0. O Semente, como seu derivado, é GPL-3.0-or-later. A
marca e a identidade visual "Pasto Legal" pertencem à UFG/LAPIG.
