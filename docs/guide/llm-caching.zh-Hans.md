# LLM 响应缓存

在崩溃之后、在别处微调了提示词之后，或者修改导出代码之后重新运行流水线，都会再次向 LLM
提出同样的问题。`CachingLLMClient` 从缓存中回答重复的请求，因此这些请求不消耗 token，
而且会立即返回：

```python
from sci_etl_core import (
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    AsyncSqliteLLMResponseCache,
    CachingLLMClient,
)

cache = AsyncSqliteLLMResponseCache("cache/llm.db")
llm = CachingLLMClient(AsyncOpenAICompatibleClient.from_config(config.llm), cache)

relevance_filter = AsyncLLMRelevanceFilter(llm, relevance_prompt)
entity_extractor = AsyncLLMEntityExtractor(llm, extraction_prompt)
```

把 SQLite 缓存列入流水线的 `closeables`，以便在运行结束时关闭它的连接。

## 请求如何匹配 {#how-requests-are-matched}

请求的键由模型名、端点的 `base_url`、温度、响应格式、类型化请求的 JSON Schema、客户端的
`variant` 以及两条提示词组成，并用 SHA-256 计算哈希；超时时间不属于键的一部分。系统提示词
改变、论文文本改变、换了模型、换了服务商、温度不同、响应格式不同或实体模式改变，都会导致
未命中。模式按排序后的键序列化，因此以其他顺序书写的相同模式仍会命中。没有模式且
`variant` 为空的请求，其键与 0.5.1 中相同。

`CachingLLMClient(..., variant="sample-2")` 会把它的回答与同一缓存上其他变体的客户端的
回答分开保存，例如用于有意把同一个问题问两遍。

`CachingLLMClient` 从它所包装的客户端读取 `base_url`、`temperature` 和
`response_format`。`AsyncOpenAICompatibleClient` 三者都提供。每个客户端都有
`response_format`，除非子类重写，否则为 `{"type": "json_object"}`；没有 `base_url` 或
`temperature` 的自定义客户端，其键中就不包含它们。

## 缓存哪些内容 {#what-is-cached}

失败的请求永远不会被缓存，因此下次会再次发送。被本库拒绝的响应也不会保留：

- `AsyncLLMEntityExtractor` 会拒绝不含实体列表的响应，或实体列表不是对象列表的响应。
- `AsyncLLMRelevanceFilter` 会拒绝没有明确结论的响应。

两者都会调用客户端的 `invalidate`，`CachingLLMClient` 随即删除缓存的响应，因此下一次
运行中的重试会真正请求模型，而不是重放同一个回答。

## 后端 {#backends}

- **`InMemoryLLMResponseCache(max_entries=None)`** 的生命周期与进程相同。设置
  `max_entries` 后，缓存满时会淘汰最久未使用的响应。
- **`AsyncSqliteLLMResponseCache(path)`** 在多次运行之间把响应保存在 SQLite 文件中。
  `clear()` 清空缓存，`count()` 报告其大小。

自定义后端（例如 Redis）需继承 `AsyncLLMResponseCache` 并实现 `get`、`set`、`delete` 和
`clear`。没有 `delete` 的后端仍然可用，但每个被拒绝的响应都会留在缓存中，并被记录为缓存
故障。

## 缓存出错时 {#when-the-cache-fails}

缓存永远不会导致模型请求失败。如果读取或写入缓存时抛出异常，错误会以 `WARNING` 级别记录
到 `sci_etl_core.llm.cache_async` 记录器，内容为 `LLM cache get failed: ...`、
`LLM cache set failed: ...` 或 `LLM cache delete failed: ...`，而请求会像没有缓存一样发往
LLM。`stats` 统计 `hits`、`misses` 和 `faults`，`usage` 则是被包装客户端的用量，因此
缓存命中不消耗 token：

```python
print(llm.stats, llm.usage)
```
