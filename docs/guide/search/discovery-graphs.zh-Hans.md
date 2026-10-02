# 发现图

`build_discovery_graph` 以一条种子记录为中心，借鉴 Connected Papers 的思路，利用按相似度
关联记录的边来源，生长出一张相关论文图：

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

- **边来源。** `EmbeddingEdgeSource` 关联标题和摘要在向量记忆中相近的记录；
  `MetadataEdgeSource` 关联共享标签的记录，权重为它们标签集合的 Jaccard 指数。后者的键必须
  属于文本存储的 `facet_keys`，默认为 `("categories", "authors")`。其他关联概念可以作为
  `AsyncEdgeSource` 的子类接入。目前还没有内置来源使用引用关系，但
  `AsyncOpenAlexExtractor` 会把论文引用的作品保存在元数据的 `references` 下。
- **生长。** 图生长 `depth` 层。每条记录对每个来源最多添加 `fanout` 个权重不低于
  `min_weight`（默认 0.35）的邻居，并在每一层之前检查 `max_nodes`（默认 200）。在
  `mutual_only`（默认开启）下，只有当两条记录互为对方的近邻时才保留这条边，这样可以防止
  一篇枢纽论文连接到所有论文。最终只保留与种子相连的记录。
- **社区。** `GraphNode.community` 来自标签传播算法，它是确定性的：同一张图总是得到相同的
  社区。当 `max_iterations`（默认 20）提前截断它时，`DiscoveryGraph.communities_converged`
  为 `False`，界面应说明社区划分是近似的。
- **只有拓扑。** 节点和边不携带坐标或颜色；由界面自行布局。
- **无 I/O 的过滤。** `filter_graph` 是纯函数且同步，因此界面可以在每次切换分面时重新运行
  它。种子始终保留，失去端点的边会被删除，社区保持不变，以便颜色稳定。传入
  `matched_ids=await text_store.filter_ids(parse_query(...))` 可以只保留匹配某个查询的
  记录；该调用接受纯否定查询，例如 `NOT simulation`。`filters` 也接受 `RangeFilter`，
  例如 `RangeFilter("year", low=2020)`。
- **开销。** `EmbeddingEdgeSource` 会为每个节点的标题和摘要生成嵌入，并且每个节点最多发出
  一次向量查询。`AsyncSqliteEmbeddingStore` 每次查询都会为所有已存储的文本块打分，但只
  从磁盘读取一次向量，因此整张图请传入同一个存储实例；记忆很大时请把 `max_nodes` 设小。
