# Блокирующий режим

`ETLPipeline` — единственный синхронный класс. Он принимает те же аргументы,
что и `AsyncETLPipeline`, включая те же **асинхронные** компоненты, плюс
`run_timeout`:

```python
import os

from sci_etl_core import (
    AsyncArxivExtractor,
    AsyncCsvExporter,
    AsyncFileStateManager,
    AsyncLLMEntityExtractor,
    AsyncLLMRelevanceFilter,
    AsyncOpenAICompatibleClient,
    ETLPipeline,
    PipelineAborted,
)
from sci_etl_core.http_async import build_async_client
from sci_etl_core.parsers import LatexTarballParser, PdfPlumberParser

RELEVANCE_PROMPT = (
    "Decide whether the paper reports measurements of galaxies. "
    'Reply with JSON: {"relevant": true} or {"relevant": false}.'
)
EXTRACTION_PROMPT = (
    "Extract every measured object from the paper. Reply with JSON: "
    '{"items": [{"name": "...", "value_a": 0.0, "value_b": 0.0}]}.'
)

client = build_async_client()
llm = AsyncOpenAICompatibleClient(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="gpt-4o-mini",
)

with ETLPipeline(
    extractor=AsyncArxivExtractor(
        client=client,
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
    ),
    relevance_filter=AsyncLLMRelevanceFilter(llm_client=llm, system_prompt=RELEVANCE_PROMPT),
    entity_extractor=AsyncLLMEntityExtractor(llm_client=llm, system_prompt=EXTRACTION_PROMPT),
    exporter=AsyncCsvExporter("results.csv", columns=["name", "value_a", "value_b"]),
    state_manager=AsyncFileStateManager("state/processed.txt", "state/metadata.json"),
    closeables=[client, llm],
    run_timeout=3600,
) as pipeline:
    try:
        processed = pipeline.run(query="all:galaxy", total_limit=50)
    except PipelineAborted as exc:
        processed = exc.partial_count

print(f"Processed {processed} relevant records")
```

- **Блокирующих версий отдельных компонентов нет.** Чтобы вызвать экстрактор,
  клиент или экспортёр напрямую из синхронного кода, оберните вызовы в
  корутину и запустите её через `asyncio.run`. Чтобы подключить блокирующий
  код к пайплайну, реализуйте асинхронный интерфейс и выполняйте блокирующую
  работу внутри него через `asyncio.to_thread` — так вызываются встроенные
  парсеры и процессоры.
- **`run_timeout`** задаётся в секундах и по умолчанию не ограничен. Когда он
  истекает, запуск отменяется и выбрасывается `TimeoutError`.
- **Цикл событий.** `ETLPipeline` выполняет пайплайн в общем фоновом потоке с
  циклом событий. Он работает из обычных скриптов, а также при вызове изнутри
  уже запущенного цикла событий (например, в ноутбуке). При этом он всё равно
  блокирует вызывающий поток до окончания запуска, поэтому в асинхронном коде
  используйте `await` с `AsyncETLPipeline`. Как только `ETLPipeline`
  воспользовался компонентом, этот компонент принадлежит фоновому циклу — не
  используйте его ещё и из собственного цикла событий.
- **`with ETLPipeline(...)`** закрывает `closeables` при выходе, отводя до 30
  секунд на каждый ресурс.
