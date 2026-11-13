# Fontes de Propriedade

Uma **fonte de propriedade** responde de onde vêm os candidatos a limite de
propriedade: quais polígonos estão ao redor de uma coordenada e qual polígono
pertence a um identificador da fonte (um número de cadastro, por exemplo). O
contrato é **sem engine** e agnóstico a país: vive em
`semente.property_sources` e importa sem o extra `geo`.

```python
from semente.property_sources import (
    PropertySource, PropertySourceError, PropertyCandidate, CandidateAttribute,
    GeometryOrigin, BufferSource,
    register_source, get_source, enabled_keys, enabled_sources,
)
```

## O contrato

```python
class PropertySource(Protocol):          # runtime_checkable
    key: str

    def find_by_point(self, latitude, longitude, search_radius_m=2000) -> list[PropertyCandidate]: ...
    def find_by_id(self, identifier) -> PropertyCandidate | None: ...
```

- `find_by_point` devolve candidatos ordenados por relevância (possivelmente vazio).
- `find_by_id` devolve o candidato de um identificador da fonte, ou `None`.
- Ambos levantam `PropertySourceError` quando a fonte não consegue responder.
- `search_radius_m` é o **raio de busca em metros** ao redor do ponto. Não tem
  relação com o raio do buffer do `BufferSource` (o padrão do protocolo é
  2000 m; o círculo do buffer tem 500 m).

### `PropertyCandidate`

| Campo | Descrição |
|---|---|
| `candidate_id` | Identificador estável dentro da fonte. |
| `name` | Nome dado pela fonte, se houver. |
| `origin` | `GeometryOrigin`: `registered_boundary`, `osm_landuse` (polígono genérico de uso do solo; o nome é histórico), `user_polygon` ou `approximate_circle`. |
| `source` | Chave da fonte. |
| `source_date` | Data dos dados da fonte (ISO), se conhecida. |
| `geometry` | GeoJSON `Polygon` ou `MultiPolygon` (lon, lat). O modelo não valida o formato. |
| `area_ha` | Área em hectares. |
| `distance_m` | Distância do ponto buscado (0 quando está dentro). |
| `attributes` | `list[CandidateAttribute(key, value, unit)]`. |
| `license` | Licença e atribuição dos dados. |
| `warnings` | Chaves neutras de aviso (veja abaixo). |

`type_key` é `origin.value` e `to_session()` devolve JSON puro (para o
`session_state`). O candidato não tem conversão para nenhum modelo do app:
transformar um candidato confirmado na sua própria área ou feature é tarefa do app.

### Erros

Existem dois tipos de falha:

- **Erros do chamador** levantam `ValueError`: coordenada inválida (o intervalo
  suportado é `|latitude| <= 85` e `|longitude| <= 180`) ou raio inválido.
- **Falhas da fonte** levantam `PropertySourceError(kind, message)`, com um
  `kind` de `PropertySourceError.KINDS`:

| Kind | Significado |
|---|---|
| `unavailable` | Serviço fora do ar ou resposta de erro. |
| `timeout` | O serviço não respondeu a tempo. |
| `not_found` | Identificador desconhecido. |
| `urban_area` | O ponto está em um uso do solo em que nenhum candidato de propriedade é oferecido. |

Devolva `[]` (ou `None`) quando nada for encontrado; levante o erro apenas
quando a fonte não conseguiu responder.

### Avisos

`warnings` são chaves neutras, nunca texto para o usuário. O app as converte
para o seu próprio texto (e idioma). A fonte embutida emite `approximate_area`.

## A fonte embutida `buffer`

`BufferSource` (chave `buffer`, raio padrão 500 m) devolve um candidato: um
círculo geodésico de 64 vértices ao redor do ponto, como `MultiPolygon`, com
`origin=approximate_circle`, `distance_m=0`, um atributo `radius` (em `m`) e o
aviso `approximate_area`. `find_by_id` sempre devolve `None` e
`search_radius_m` é ignorado. O construtor exige `radius_m` finito e `> 0` e
coordenada inválida levanta `ValueError`. Perto do antimeridiano o anel não é
dividido: as longitudes são apenas normalizadas para [-180, 180).

> O círculo **não** é o limite de uma propriedade. É uma aproximação ao redor
> do ponto, oferecida quando não há limite real disponível. Os apps devem
> apresentá-lo como tal.

## Adaptando a um país

Um país conecta o seu próprio cadastro implementando o protocolo e
registrando-o. Exemplo sobre um cadastro nacional hipotético:

```python
from semente.property_sources import (
    GeometryOrigin, PropertyCandidate, PropertySourceError, register_source,
)

# query_registry() and get_registry_row() are YOUR country's registry client
# (an HTTP API, a database, a file export). They are not part of Semente.


class NationalRegistrySource:
    key = "registry"

    def find_by_point(self, latitude, longitude, search_radius_m=2000):
        try:
            rows = query_registry(lat=latitude, lon=longitude, radius=search_radius_m, timeout=10)
        except TimeoutError as exc:
            raise PropertySourceError("timeout", str(exc)) from exc
        except OSError as exc:
            raise PropertySourceError("unavailable", str(exc)) from exc
        return [self._to_candidate(row) for row in rows]

    def find_by_id(self, identifier):
        try:
            row = get_registry_row(identifier, timeout=10)
        except TimeoutError as exc:
            raise PropertySourceError("timeout", str(exc)) from exc
        except OSError as exc:
            raise PropertySourceError("unavailable", str(exc)) from exc
        return None if row is None else self._to_candidate(row)

    def _to_candidate(self, row):
        return PropertyCandidate(
            candidate_id=row["registry_number"], name=row["owner_label"],
            origin=GeometryOrigin.REGISTERED_BOUNDARY, source=self.key,
            source_date=row["updated_at"], geometry=row["geojson"],
            area_ha=row["area_ha"], distance_m=row["distance_m"],
            license="national open data licence",
        )


register_source("registry", NationalRegistrySource)
```

Regras práticas:

- `geometry` é GeoJSON em lon/lat (WGS84); `area_ha` vem da fonte.
- `distance_m` é 0 quando o ponto está dentro do polígono.
- Ordene os candidatos por relevância, o melhor primeiro.
- Levante `PropertySourceError` apenas quando a fonte não conseguiu responder;
  devolva `[]` ou `None` quando ela respondeu sem resultado.
- Defina seus próprios timeouts nas chamadas de rede e mapeie-os para `timeout`.
- Use `registered_boundary` apenas para polígonos oficiais, nunca para aproximações.

## Registro e configuração

| Função | Descrição |
|---|---|
| `register_source(key, factory)` | Registra (ou substitui) uma fonte; `factory` é uma classe ou callable, chamada uma vez, sob demanda. Registrar de novo descarta a instância em cache. |
| `get_source(key)` | Devolve a instância compartilhada; levanta `KeyError` para chave desconhecida. |
| `enabled_keys(manifest=None)` | Chaves das fontes habilitadas, por ordem de prioridade. |
| `enabled_sources(manifest=None)` | Instâncias das fontes habilitadas; chaves desconhecidas são ignoradas com aviso no log. |

As chaves habilitadas vêm de, por ordem de precedência:

1. a variável de ambiente `SEMENTE_PROPERTY_SOURCES` (separada por vírgulas;
   ignorada se só tiver separadores);
2. a lista `property_sources` do [manifesto](manifest.md);
3. o padrão `["buffer"]`.

Sem o argumento `manifest`, o manifesto é carregado do caminho usual
(`SEMENTE_MANIFEST` ou `./semente.yaml`). Arquivo ausente é silencioso; arquivo
que falha ao carregar gera um aviso no log e vale o padrão. Registre suas
fontes na importação do seu domínio, antes de chamar `enabled_sources()`.

```yaml
property_sources: [registry, buffer]
```
