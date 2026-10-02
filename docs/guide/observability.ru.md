# События прогресса и метрики

Каждый запуск конвейера собирает метрики и может сообщать о своём прогрессе по
ходу работы.

## Метрики запуска {#run-metrics}

`pipeline.last_run_metrics` возвращает `RunMetrics` для последнего запуска, как
бы он ни завершился:

```python
from sci_etl_core import AsyncETLPipeline

pipeline = AsyncETLPipeline(..., usage_sources=[llm, embedder])
try:
    await pipeline.run(query="all:galaxy", total_limit=200, newest_first=True)
finally:
    metrics = pipeline.last_run_metrics
    print(
        f"{metrics.outcome}: {metrics.processed} processed, {metrics.irrelevant} irrelevant, "
        f"{metrics.failed} failed in {metrics.duration_seconds:.0f} s"
    )
```

| Поле | Значение |
|------|----------|
| `pages`, `listed` | Полученные страницы выдачи и число элементов на них |
| `processed`, `irrelevant`, `deferred`, `failed`, `skipped` | Записи по исходу; записи `deferred` ждут следующего запуска из-за `total_limit` или завершения работы, а у записей `skipped` не было идентификатора |
| `entities_exported` | Сущности, переданные экспортёру |
| `memory_faults` | Сбои загрузки в память, которые были записаны в журнал, не приведя к неудаче записи |
| `quarantined` | Записи из выдачи, пропущенные потому, что в прошлых запусках они не удались `max_attempts` раз; каждая учитывается один раз за запуск |
| `listing_truncated` | `True`, когда источник остановил выдачу на своём лимите результатов |
| `duration_seconds` | Фактическое время запуска |
| `token_usage` | Токены, израсходованные `usage_sources` за этот запуск, или `None` без источников |
| `outcome` | `completed`, `aborted`, `interrupted`, `cancelled` или `failed` |

`usage_sources` принимает любые объекты со свойством `usage`, например
`AsyncOpenAICompatibleClient`, `AsyncOpenAIEmbedder` или `CachingLLMClient`.
Их расход до запуска вычитается, поэтому клиент, общий для нескольких
запусков, сообщает о каждом запуске отдельно.

## События прогресса {#progress-events}

Передайте `on_event`, чтобы по ходу запуска получать типизированные события из
`sci_etl_core.observability`:

```python
from sci_etl_core.observability import PageFinished, RecordFinished, RunFinished


def report(event):
    if isinstance(event, RecordFinished) and event.outcome == "failed":
        print(f"{event.record_id} failed after {event.duration_seconds:.1f} s: {event.error!r}")
    elif isinstance(event, PageFinished):
        print(f"page at {event.cursor or 'start'}: {event.metrics.processed} processed so far")
    elif isinstance(event, RunFinished):
        print(f"run {event.metrics.outcome}")


pipeline = AsyncETLPipeline(..., on_event=report)
```

| Событие | Когда |
|---------|-------|
| `RunStarted(query, start_index, total_limit, newest_first, cursor)` | Перед первым запросом выдачи |
| `PageFetched(offset, entries, new_records, cursor, truncated)` | Пришла страница выдачи; `new_records` ещё не обработаны, а `truncated` отмечает страницу, на которой источник остановился на своём лимите результатов |
| `RecordFinished(record_id, title, outcome, duration_seconds, entities, error)` | Запись покинула конвейер в этом запуске |
| `PageFinished(offset, duration_seconds, metrics, cursor)` | Все записи страницы завершены; `metrics` — запуск на данный момент |
| `RunFinished(metrics)` | Запуск закончился, как бы он ни закончился |

`cursor` — это курсор выдачи, с которым запрашивалась страница, и `None` для
первой страницы. `start_index` и `offset` содержат ту же позицию в виде
смещения в выдаче, когда экстрактор листает по смещению, и `None` в противном
случае. Каждое событие и `RunMetrics` — dataclass только с именованными
аргументами.

Обработчик выполняется в цикле событий, поэтому он должен быть быстрым:
передавайте медленную работу, например сетевой вызов, в очередь. Выброшенное им
исключение записывается в журнал как `Event handler failed: ...` и никогда не
останавливает запуск. `ETLPipeline` принимает те же аргументы и тоже
предоставляет `last_run_metrics`.
