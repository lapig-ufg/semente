# Fontes de Propriedade

Uma **fonte de propriedade** responde de onde vêm os candidatos a limite de
propriedade: quais polígonos estão ao redor de uma coordenada e qual pertence a
um identificador da própria fonte. O contrato em `semente.property_sources` é
sem engine, agnóstico a país e importa sem o extra `geo`.

## Contrato

```python
class PropertySource(Protocol):          # runtime_checkable
    key: str
    def find_by_point(self, latitude, longitude, search_radius_m=2000) -> list[PropertyCandidate]: ...
    def find_by_id(self, identifier) -> PropertyCandidate | None: ...
```

`find_by_point` devolve candidatos do melhor para o pior (possivelmente vazio);
`search_radius_m` é um raio de busca em metros, sem relação com o raio do buffer
abaixo. `find_by_id` devolve `None` quando o identificador não existe.

## Candidato

Campos de `PropertyCandidate`: `candidate_id`, `origin`, `source`, `geometry`
(GeoJSON Polygon/MultiPolygon, lon/lat WGS84, formato não validado), `area_ha`,
mais `name`, `source_date`, `distance_m` (0 quando o ponto está dentro),
`attributes` (dict; ponha a unidade na chave, ex.: `radius_m`), `license` e
`warnings` (chaves neutras que o app converte em texto) como opcionais.

`GeometryOrigin`: `registered_boundary` (só polígonos oficiais, nunca
aproximações), `osm_landuse` (polígono genérico de uso do solo; o nome é
histórico), `user_polygon`, `approximate_circle`. Converta o candidato
confirmado para o seu modelo no app; serialize com `model_dump(mode="json")`.

## Erros

- Entrada inválida (coordenada fora de `|lat| <= 85`, `|lon| <= 180`, ou raio
  inválido) levanta `ValueError`.
- Uma fonte que não consegue responder levanta `PropertySourceError(kind, message)`
  com `kind` em `unavailable`, `timeout`, `not_found` ou `urban_area`.
- Devolva `[]` ou `None` quando a fonte respondeu sem resultado.

## Fonte embutida `buffer`

`BufferSource` (chave `buffer`, raio padrão 500 m, finito e > 0) devolve um
candidato: um círculo geodésico de 64 vértices como `MultiPolygon`,
`approximate_circle`, `distance_m=0`, atributo `radius_m` e aviso
`approximate_area`. `find_by_id` é sempre `None`. O anel não é dividido no
antimeridiano (as longitudes são apenas normalizadas).

> O círculo **não** é o limite de uma propriedade. Ele só ocupa o lugar de um
> quando não há limite real disponível; os apps devem apresentá-lo assim.

## Adaptando a um país

Implemente o protocolo sobre o seu cadastro e registre-o. Defina seus próprios
timeouts de rede e mapeie as falhas para `PropertySourceError`:

```python
from semente.property_sources import (
    GeometryOrigin, PropertyCandidate, PropertySourceError, register_source,
)

# query_registry() and get_registry_row() are YOUR country's registry client; not part of Semente.


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
            candidate_id=row["registry_number"], origin=GeometryOrigin.REGISTERED_BOUNDARY,
            source=self.key, source_date=row["updated_at"], geometry=row["geojson"],
            area_ha=row["area_ha"], distance_m=row["distance_m"],
        )


register_source("registry", NationalRegistrySource)
```

## Registro e configuração

`register_source(key, factory)` registra (ou substitui) uma fonte; a instância é
criada sob demanda e compartilhada. `get_source(key)` levanta `KeyError` para
chave desconhecida. `enabled_keys(manifest=None)` e `enabled_sources(manifest=None)`
devolvem as fontes habilitadas por prioridade, a partir de:

1. a variável `SEMENTE_PROPERTY_SOURCES` (separada por vírgulas; ignorada se só tiver separadores);
2. `property_sources` no [manifesto](manifest.md);
3. o padrão `["buffer"]`.

Sem `manifest`, ele é lido de `SEMENTE_MANIFEST` ou `./semente.yaml` (ausente:
silencioso; quebrado: aviso no log). Chaves desconhecidas são ignoradas com
aviso. Registre suas fontes quando o seu domínio for importado.

```yaml
property_sources: [registry, buffer]
```
