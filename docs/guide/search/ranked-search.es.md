# Búsqueda por relevancia y filtrado

Los almacenes reciben consultas ya analizadas, y `AsyncHybridSearcher` recibe
texto y lo analiza una vez, antes de cualquier E/S. Una búsqueda ordenada por
relevancia necesita un término por el que ordenar, así que una consulta cuyos
términos están todos negados, como `NOT simulation` o
`NOT simulation OR quasar`, hace que `search` lance `SearchQueryError`. Usa
`filter_ids` en su lugar. Acepta cualquier consulta y devuelve un `frozenset`
de identificadores de registro, que no lleva orden y por tanto no puede
confundirse con una clasificación:

```python
from sci_etl_core.search import parse_query

hits = await text_store.search(parse_query("photometr* dwarf"), limit=20)
observational = await text_store.filter_ids(parse_query("NOT simulation"))
```

Un `TextHit` tiene un `score` en el que más alto es mejor. Su escala depende
del corpus, así que compara puntuaciones solo dentro de una misma lista de
resultados.

## Extractos {#snippets}

El `snippet` de un resultado es texto plano del campo que mejor coincidió, y
`highlights` contiene desplazamientos de caracteres `[start, end)` de las
palabras coincidentes dentro de él, para que la interfaz aplique su propio
marcado. Un campo de más de 24 tokens se recorta a una ventana de 24 tokens
alrededor de una coincidencia, con `…` donde se omite texto.

Cuando una consulta coincide en más de un campo, `snippets` contiene un
`Snippet` por cada uno, en el orden `title`, `abstract`, `body`, de modo que un
resultado puede mostrar a la vez la coincidencia en el título y el pasaje del
cuerpo:

```python
from sci_etl_core.search import parse_query

for hit in await text_store.search(parse_query("dwarf OR photometr*"), limit=10):
    for snippet in hit.snippets:
        marked = [snippet.text[start:end] for start, end in snippet.highlights]
        print(f"{hit.record_id} {snippet.field}: {snippet.text} {marked}")
```

Un campo aparece en `snippets` solo cuando en él se resalta una palabra
coincidente. Los dos almacenes de texto resaltan las mismas palabras, salvo en
las consultas en las que FTS5 cuenta también una palabra dentro de una parte de
la consulta que no coincide, lo cual documenta `InMemoryTextSearchStore`.

`passage_snippet(query, text)` construye del mismo modo un `Snippet` de
cualquier otro texto, resaltando cada palabra de la consulta que no esté
negada. El buscador híbrido lo usa para los pasajes que encuentra la rama
semántica.
