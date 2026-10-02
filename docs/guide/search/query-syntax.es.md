# Sintaxis de consultas

| Construcción | Ejemplo | Encuentra |
|--------------|---------|-----------|
| Término | `galaxy` | la palabra, sin distinguir mayúsculas ni acentos, así que `Müller` encuentra `Muller` |
| Frase | `"dwarf galaxy"` | las palabras juntas y en orden |
| Prefijo | `photometr*` | cualquier palabra que empiece por `photometr` |
| Ámbito de campo | `title:quasar`, `title,abstract:"dwarf galaxy"` | solo en los campos indicados: `title`, `abstract`, `body` |
| Proximidad | `NEAR(dwarf "dark matter" halo*, 5)`, `title:NEAR(dwarf halo)` | todos los términos y frases en un mismo campo, a 5 tokens como máximo entre sí (10 por defecto), en cualquier orden |
| Y | `a AND b`, `a && b`, `a b` | ambos |
| O | `a OR b`, `a \|\| b` | cualquiera de los dos |
| No | `NOT a`, `-a` | documentos sin `a` |
| Agrupación | `(a OR b) -c` | |

`NOT` es el que más liga, después `AND` y después `OR`. Los operadores van en
mayúsculas, así que `and` es una palabra normal. Una palabra que el tokenizador
divide, como `H-alpha`, se busca como una frase formada por sus partes.

## Proximidad {#proximity}

`NEAR(...)` acepta términos, frases y términos de prefijo separados por
espacios y, opcionalmente, una coma y un número entero de tokens. Eligiendo las
apariciones de modo que la que empieza en último lugar empiece en el token `p`,
cada uno de los demás operandos debe terminar como máximo esa cantidad de
tokens antes de `p`: `NEAR(a b, 2)` encuentra `a x x b` y `b x a`, pero no
`a x x x b`.

- **Limita el grupo, no sus partes.** `abstract:NEAR(dwarf halo)` busca en el
  resumen; un ámbito de campo dentro de los paréntesis, como
  `NEAR(title:dwarf halo)`, es un `SearchQueryError`.
- **Solo palabras dentro.** Dentro de un grupo se rechazan `AND`, `OR`, `NOT`,
  `-`, `&&`, `||` y los paréntesis anidados. Niega o combina el grupo entero en
  su lugar, como en `quasar -NEAR(dwarf halo, 3)`.
- **Formas abreviadas.** Un grupo con un solo operando, como `NEAR(dwarf)`,
  equivale a ese término. Un grupo con una sola frase entre comillas, como
  `NEAR("dwarf halo", 3)`, busca las palabras de la frase cerca unas de otras,
  no la frase.
- **En mayúsculas y sin espacio.** `NEAR` debe ir en mayúsculas y seguido
  directamente de `(`; `near(a b)` y `NEAR (a b)` se leen como la palabra
  `near` y los términos `a` y `b`.

Un grupo `NEAR` ordena, filtra y resalta como cualquier otro término, en los
dos almacenes de texto. En una búsqueda híbrida, sus palabras se convierten en
embedding como el resto de la consulta, salvo sus términos de prefijo.
`describe` devuelve un grupo como un único `QueryChip` cuyo `near` es su
distancia.

Hay una excepción en `AsyncSqliteFts5Store`: algunas compilaciones de SQLite,
entre ellas la 3.50.4, no consiguen resaltar en algunos documentos un grupo con
ámbito de campo dentro de `OR` o `NOT`, como `dwarf OR title:NEAR(dwarf halo)`
o `dwarf -title:NEAR(dwarf halo)`. La búsqueda lanza entonces
`SearchQueryError` indicando la versión de SQLite. Quita el ámbito de campo del
grupo o busca cada alternativa de `OR` por separado. `filter_ids` y el almacén
en memoria no se ven afectados.

## Análisis {#parsing}

El análisis es puro y síncrono, así que una barra de búsqueda puede ejecutarlo
en cada pulsación de tecla. Una consulta mal formada lanza `SearchQueryError`,
cuyos `position` y `token` señalan el error, y `describe` devuelve las palabras
y frases analizadas como `QueryChip` para mostrarlas:

```python
from sci_etl_core import SearchQueryError
from sci_etl_core.search import describe, parse_query

try:
    chips = describe(parse_query("title:quasar (blazar OR -dwarf"))
except SearchQueryError as exc:
    print(f"{exc} (column {exc.position}: {exc.token!r})")
```
