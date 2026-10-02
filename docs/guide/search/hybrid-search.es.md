# Búsqueda híbrida

`AsyncHybridSearcher(text_store, finder).search(query, top_k, mode=..., filters=...)`
ejecuta una o las dos ramas de recuperación:

| `mode` | Ejecuta | Sin un `finder` |
|--------|---------|-----------------|
| `"lexical"` | BM25 sobre el índice de texto | sin cambios |
| `"semantic"` | la memoria vectorial, puntuando cada artículo por su mejor fragmento | lanza `SearchQueryError` |
| `"hybrid"` (por defecto) | ambas a la vez y luego fusiona las dos clasificaciones | ejecuta solo la rama léxica e informa `skipped=("semantic",)` |

- **Lo que ve el generador de embeddings.** La rama semántica genera el
  embedding de las palabras de la consulta, no de su sintaxis. Se descartan los
  operadores, los ámbitos de campo, los términos negados y los términos de
  prefijo, así que `quasar -dwarf` se convierte en el embedding de `quasar`, y
  `quasar OR blazar` en lo mismo que `quasar blazar`. Una consulta híbrida
  formada solo por términos de prefijo omite la rama semántica; en modo
  semántico lanza `SearchQueryError`.
- **Ramas degradadas y omitidas.** `SearchOutcome.degraded` nombra las ramas
  que se intentaron y fallaron. En modo híbrido, un `EmbeddingError` se
  registra a través de `logger` y se devuelven los resultados léxicos.
  `SearchOutcome.skipped` nombra las ramas que no tenían nada que ejecutar.
  Informa al usuario de ambos casos. Un fallo léxico siempre se lanza, porque
  significa que el índice local está dañado.
- **Fusión.** La fusión por rango recíproco (reciprocal rank fusion) solo lee
  el orden de cada lista, así que la escala de BM25, que depende del corpus,
  nunca sesga la mezcla. Pasa `strategy=normalized_score_fusion` cuando deban
  contar las diferencias de puntuación, y
  `fusion=FusionParams(weights=(1.0, 2.0))` para ponderar las listas léxica y
  semántica, en ese orden.
- **Resultados.** Un `FusedHit` lleva `lexical_rank` y `semantic_rank` (`None`
  cuando esa rama no lo devolvió), `title`, `metadata`, `snippet`,
  `highlights` y `snippets`. Muestra los rangos, nunca la puntuación fusionada
  como porcentaje.
- **Extractos.** Un registro que devolvió la rama léxica conserva sus
  extractos léxicos, uno por cada campo coincidente. Un registro encontrado
  solo por la rama semántica recibe un extracto del fragmento que lo
  clasificó, con las palabras de la consulta resaltadas donde aparecen, como un
  único `Snippet` cuyo campo es `"body"`. Ese pasaje coincidió por significado,
  así que puede no resaltar nada; comprueba `lexical_rank is None` para
  etiquetarlo, por ejemplo como "pasaje relacionado", o lee el resumen con
  `text_store.get_documents`.
- **Grupo de candidatos.** Cada rama obtiene `HybridParams.candidate_pool`
  registros (100 por defecto, y nunca menos que `top_k`) antes de la fusión,
  de modo que un registro en el puesto 40 léxicamente y en el 3 semánticamente
  aún puede llegar a los 20 primeros. La rama semántica pide a la memoria
  vectorial `candidate_pool × chunk_pool_factor` fragmentos (factor 5 por
  defecto). Aumenta el factor cuando los artículos largos llenan los primeros
  fragmentos y el grupo vuelve incompleto.
