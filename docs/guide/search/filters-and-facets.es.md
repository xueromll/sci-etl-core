# Filtros y facetas

Los filtros de metadatos son valores `MetadataFilter` y `RangeFilter` que se
pasan junto a la consulta, nunca escritos dentro de ella. Un almacén etiqueta
cada documento con las claves de metadatos indicadas en sus `facet_keys`. Todos
los extractores incluidos rellenan `categories` y `authors` en
`RawRecord.metadata`, y `published` y `year` cuando la fuente tiene una fecha
(consulta en [Fuentes compatibles](../sources.md) las claves que añade cada
fuente), y `AsyncSearchIndexer` copia esos metadatos en el índice.

```python
from sci_etl_core.search import MetadataFilter, RangeFilter, parse_query

filters = (
    MetadataFilter("categories", {"astro-ph.GA", "astro-ph.CO"}),
    RangeFilter("published", low="2020-01", high="2024-06"),
)
outcome = await searcher.search("dwarf galaxy", filters=filters)
facets = await text_store.facet_counts(["categories", "year"], query=parse_query("dwarf galaxy"), filters=filters)
```

- **Coincidencia.** Un `MetadataFilter` conserva los registros etiquetados con
  cualquiera de sus valores y, con `negated=True`, los descarta. Todos los
  filtros deben cumplirse. Varios valores de una misma clave van en un solo
  filtro: dos filtros sobre la misma clave, incluidos un `MetadataFilter` y un
  `RangeFilter`, o una clave fuera de `facet_keys`, lanzan `ValueError` antes
  de cualquier E/S.
- **Etiquetas.** Las cadenas, los enteros y las listas de ellos se convierten
  en etiquetas; los demás valores no se etiquetan. Un registro con varias
  etiquetas bajo una clave, como varios autores, pasa un filtro cuando
  cualquiera de ellas lo pasa.
- **Antes del límite.** Los filtros se aplican dentro del índice, antes de
  `limit`, y a las dos ramas de una búsqueda híbrida, así que un registro
  filtrado nunca ocupa un puesto de resultado. `filter_graph` los aplica del
  mismo modo a un grafo de descubrimiento.
- **Recuentos de facetas.** `facet_counts` asigna a cada clave pares
  `(value, count)`, ordenados por recuento y luego por valor, sin recuentos
  nulos. Los recuentos de cada clave aplican la consulta y todos los filtros
  sobre *otras* claves, de modo que un recuento indica cuántos resultados daría
  seleccionar ese valor, y los demás valores de una clave filtrada siguen
  visibles. `query=None` cuenta sobre todo el índice.
- **Cambiar `facet_keys`.** Las claves se fijan al construir un almacén y
  quedan registradas en el archivo. Para cambiarlas, construye el almacén con
  las claves nuevas y ejecuta `await text_store.rebuild_tags()`. Hasta
  entonces, un filtro o una faceta sobre una clave cuyas etiquetas no se han
  construido lanza `SearchStoreError`.

## Rangos {#ranges}

Un `RangeFilter` conserva los registros con una etiqueta entre `low` y `high`.
Ambos límites son inclusivos, cualquiera puede omitirse y `negated=True`
descarta en su lugar los registros dentro del rango. El tipo de los límites
decide cómo se comparan las etiquetas:

| Límites | Compara | Ejemplo | Conserva |
|---------|---------|---------|----------|
| Enteros | como números | `RangeFilter("year", 2020, 2024)` | las etiquetas de `2020` a `2024`, guardadas como enteros o como texto |
| Texto | como texto, con `high` comparado con el mismo número de caracteres iniciales | `RangeFilter("published", "2024-01", "2024-06")` | de `2024-01-01` hasta `2024-06-30T23:59:59Z` |

- **Enteros.** Solo una etiqueta escrita como Python escribe un entero puede
  estar en un rango entero: `2024`, `0` y `-3` pueden, mientras que `"07"`,
  `"+3"` y `"2024-05-01"` nunca lo están. Los límites enteros son adecuados
  para recuentos, como las citas, que la comparación de texto ordenaría mal.
- **Texto.** El texto se compara carácter a carácter, así que las fechas ISO
  8601 y los años de cuatro cifras se ordenan correctamente. Como `high` se
  compara con los primeros caracteres de la etiqueta, `high="2024-06"` conserva
  todas las fechas de junio de 2024 y `high="2024"` todas las de 2024.
- **Rangos no válidos.** Un rango sin límites, un límite de texto vacío, un
  límite `bool` o `float`, un límite entero y otro de texto, o un `low` mayor
  que `high`, de modo que nada podría coincidir, lanzan una excepción al
  construirse.

## Contar rangos {#counting-ranges}

`range_counts` cuenta los registros coincidentes en cada rango, para las barras
de un histograma o preajustes como "últimos 5 años". Igual que `facet_counts`,
cada recuento aplica la consulta y todos los filtros sobre *otras* claves, así
que seleccionar una barra deja visibles los recuentos de las demás:

```python
from sci_etl_core.search import RangeFilter, parse_query

buckets = [RangeFilter("year", low, low + 4) for low in range(2000, 2025, 5)]
counts = await text_store.range_counts(buckets, query=parse_query("dwarf galaxy"), filters=filters)
for bucket, count in zip(buckets, counts):
    print(f"{bucket.low}–{bucket.high}: {count}")
```

Los recuentos vuelven como una tupla en el orden de `ranges`, y los rangos
pueden compartir clave y solaparse. `AsyncSqliteFts5Store` cuenta todos los
rangos en una única lectura coherente. Un almacén personalizado hereda una
versión que llama a `filter_ids` una vez por rango.
