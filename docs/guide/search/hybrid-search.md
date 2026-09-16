# Hybrid search

`AsyncHybridSearcher(text_store, finder).search(query, top_k, mode=..., filters=...)`
runs one or both retrieval legs:

| `mode` | Runs | Without a `finder` |
|--------|------|--------------------|
| `"lexical"` | BM25 over the text index | unaffected |
| `"semantic"` | the vector memory, scoring each article by its best chunk | raises `SearchQueryError` |
| `"hybrid"` (default) | both at once, then fuses the two rankings | runs the lexical leg only and reports `skipped=("semantic",)` |

- **What the embedder sees.** The semantic leg embeds the query's words, not
  its syntax. Operators, field scopes, negated terms, and prefix terms are
  dropped, so `quasar -dwarf` is embedded as `quasar`, and `quasar OR blazar`
  the same as `quasar blazar`. A hybrid query made only of prefix terms skips
  the semantic leg; in semantic mode it raises `SearchQueryError`.
- **Degraded and skipped legs.** `SearchOutcome.degraded` names legs that were
  attempted and failed. In hybrid mode, an `EmbeddingError` is logged through
  `logger`, and the lexical results are returned. `SearchOutcome.skipped`
  names legs that had nothing to run. Tell the user about both. A lexical
  failure is always raised, because it means the local index is broken.
- **Fusion.** Reciprocal rank fusion reads only the order of each list, so
  BM25's corpus-dependent scale never skews the blend. Pass
  `strategy=normalized_score_fusion` when score gaps should count, and
  `fusion=FusionParams(weights=(1.0, 2.0))` to weigh the lexical and semantic
  lists, in that order.
- **Hits.** A `FusedHit` carries `lexical_rank` and `semantic_rank` (`None`
  where that leg did not return it), `title`, `metadata`, and the lexical
  snippet and highlights. Show ranks, never the fused score as a percentage. A
  record found only by the semantic leg has no snippet; read its abstract with
  `text_store.get_documents`.
- **Candidate pool.** Each leg fetches `HybridParams.candidate_pool` records
  (default 100, and never fewer than `top_k`) before fusion, so a record
  ranked 40th lexically and 3rd semantically can still reach the top 20. The
  semantic leg asks the vector memory for `candidate_pool × chunk_pool_factor`
  chunks (default factor 5). Raise the factor when long articles fill the top
  chunks and the pool comes back short.
