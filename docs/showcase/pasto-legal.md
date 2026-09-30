# Pasto Legal — the first seed

[Pasto Legal](https://github.com/lapig-ufg/pasto-legal) is the application
Semente was extracted from. It delivers satellite-based pasture diagnostics to
Brazilian ranchers over WhatsApp.

## What it does

- 🛰️ **Pasture health monitoring** — biomass, vegetation vigor, pasture age, and
  land-use/cover maps from satellite imagery (Sentinel-2, MapBiomas).
- 🐄 **Carrying capacity** — stocking rates and ideal carrying capacity (UA/ha)
  using the LAPIG methodology.
- 📋 **Property registration** — by CAR/SICAR code, GPS coordinates, or Google
  Maps link.
- 🌾 **Agronomic consultancy** — EMBRAPA-validated guidance on forage management
  and pasture recovery.
- 🔊 **Voice responses** — audio reports narrated back via WhatsApp.

## How it maps to Semente

Pasto Legal is a Semente app. Its `domain/` package supplies:

| Semente concept | Pasto Legal implementation |
|---|---|
| `DomainSpec.tools` | `get_tools` — dynamic selection by registration state (pending/final/default) |
| `DomainSpec.instructions` | `get_instructions` — registration-state machine + persona + registrations |
| `DomainSpec.knowledge` | `pasto_legal_kb` — EMBRAPA/pasture docs indexed in a vector DB |
| `DomainSpec.skills` | `ua-calculator` — the carrying-capacity skill |
| `prompts_dir` | `domain/prompts` — pt-BR agent/tool/hook texts |

The domain-neutral engine (agent pipeline, WhatsApp/Streamlit channels, PII
guardrails, feedback/persona loop, TTS, i18n prompt loader) is exactly what
became Semente.

## Architecture

```
User (WhatsApp)
   │
   ▼
SementeAgent
├── Input pre-processing (audio/image → text)
├── PII guardrail (CPF/CNPJ/card/email redaction)
├── Onboarding check (terms acceptance)
├── Summarization + feedback loop + Pasto Legal agent
├── Remediation merge
└── Output finalization (TTS)
   │
   ▼
Pasto Legal domain
├── GEE / MapBiomas (satellite analytics)
├── SICAR (property registry)
├── Weather (Open-Meteo)
└── EMBRAPA knowledge base
```

## License

Pasto Legal is GPL-3.0. Semente, as its derivative, is GPL-3.0-or-later. The
"Pasto Legal" brand and visual identity are owned by UFG/LAPIG.
