# 重试

`AsyncArxivExtractor`、`AsyncPubMedExtractor`、`AsyncSemanticScholarExtractor`、
`AsyncOpenAlexExtractor`、`AsyncOpenAICompatibleClient` 和 `AsyncOpenAIEmbedder`
会对限流（`429`）、服务器错误和传输故障进行重试，每个请求最多尝试 `max_retries` 次
（默认 3 次）。四个提取器共用同一条重试路径，并且也会重试 `408` 请求超时。
`AsyncArxivExtractor` 还会重试 `406`，arXiv 网关会对有效请求间歇性地返回该状态码：

- **退避。** 两次尝试之间等待 `backoff_factor ** attempt` 秒：在默认因子为 2 时，
  先等 1 秒，再等 2 秒。
- **`Retry-After`。** 当响应通过 `Retry-After` 或 OpenAI 兼容 API 发送的
  `retry-after-ms` 头说明需要等待多久时，只要这一时长比退避时间长，就改为等待该时长，
  上限为 `max_retry_after` 秒（默认 60）。
- **单层重试。** OpenAI SDK 自身的重试已关闭，因此 `max_retries` 就是总尝试次数。
- **可见性。** 提取器会通过 `logger` 记录每次重试及其等待时间。

`build_async_client` 返回的客户端还会在传输层重试失败的连接（`total_retries`，
默认 5 次），之后提取器才会记为一次失败的尝试。
