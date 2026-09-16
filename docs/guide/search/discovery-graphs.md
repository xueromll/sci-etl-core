# Discovery graphs

`build_discovery_graph` grows a graph of related papers around a seed record,
in the spirit of Connected Papers, from edge sources that relate records by
similarity:

```python
from sci_etl_core.search import (
    EmbeddingEdgeSource,
    GraphParams,
    MetadataEdgeSource,
    MetadataFilter,
    build_discovery_graph,
    filter_graph,
)


async def show_neighborhood(record_id: str) -> None:
    sources = [
        EmbeddingEdgeSource(embedder, vector_store, text_store),
        MetadataEdgeSource(text_store, keys=("categories",)),
    ]
    graph = await build_discovery_graph(record_id, sources, text_store, params=GraphParams(depth=2, fanout=8))
    recent = filter_graph(graph, filters=[MetadataFilter("year", {"2025", "2026"})])
    for node in recent.nodes:
        print(f"community {node.community}  links {node.degree}  {node.title}")
```

- **Edge sources.** `EmbeddingEdgeSource` relates records whose title and
  abstract are close in the vector memory, and `MetadataEdgeSource` records
  that share tags, weighted by the Jaccard index of their tag sets. Its keys
  must be among the text store's `facet_keys`, and it defaults to
  `("categories", "authors")`. Other notions of relatedness, such as
  citations, plug in as subclasses of `AsyncEdgeSource`.
- **Growth.** The graph grows `depth` levels. Each record adds up to `fanout`
  neighbors per source whose weight is at least `min_weight` (default 0.35),
  and `max_nodes` (default 200) is checked before each level. With
  `mutual_only` (the default), an edge is kept only when each record is among
  the other's nearest, which keeps a hub paper from linking to everything.
  Only records connected to the seed remain.
- **Communities.** `GraphNode.community` comes from label propagation, which
  is deterministic: the same graph always gives the same communities. When
  `max_iterations` (default 20) cuts it short,
  `DiscoveryGraph.communities_converged` is `False`, and a UI should say the
  communities are approximate.
- **Topology only.** Nodes and edges carry no coordinates or colors; the UI
  runs its own layout.
- **Filtering without I/O.** `filter_graph` is pure and synchronous, so a UI
  can re-run it on every facet toggle. The seed always stays, edges that lose
  an endpoint are dropped, and communities are kept so colors stay stable.
  Pass `matched_ids=await text_store.filter_ids(parse_query(...))` to keep only
  records matching a query; that call accepts pure negation, such as
  `NOT simulation`.
- **Cost.** `EmbeddingEdgeSource` issues up to one vector query per node, and
  `AsyncSqliteEmbeddingStore` scans every stored chunk on each query, so keep
  `max_nodes` small for a large memory.
