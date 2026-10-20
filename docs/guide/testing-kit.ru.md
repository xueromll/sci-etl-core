# Тестирование своих компонентов

`sci_etl_core.testing` содержит контрактные наборы тестов: тестовые классы
pytest, которые проверяют поведение компонента по контракту его базового
класса. Унаследуйте набор для своего компонента, добавьте фикстуру, которая его
создаёт, и pytest запустит каждый тест набора против вашей реализации.
Встроенные реализации проходят те же наборы.

| Набор | Проверяет | Встроенные реализации, против которых он запускается |
|-------|-----------|------------------------------------------------------|
| `ExtractorContract` | `AsyncExtractor` | `AsyncArxivExtractor`, `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`, `AsyncOpenAlexExtractor` |
| `StateManagerContract` | `AsyncStateManager` | `AsyncFileStateManager`, `AsyncSqliteStateManager` |
| `ExporterContract` | `AsyncExporter` | `AsyncJsonlExporter`, `AsyncCsvExporter`, `AsyncClaimStoreExporter` |
| `EmbeddingStoreContract` | `AsyncEmbeddingStore` | `InMemoryEmbeddingStore`, `AsyncSqliteEmbeddingStore` |

## Установка {#installing}

Наборам нужен pytest, который устанавливает extra `testing`:

```bash
pip install "sci-etl-core[testing]"
```

Ни один другой модуль библиотеки не импортирует pytest. Тесты — обычные
функции, которые запускают каждый сценарий через `asyncio.run`, поэтому
pytest-asyncio не нужен.

## Написание контрактного теста {#writing-a-contract-test}

Унаследуйте набор в тестовом модуле под именем, которое собирает pytest, и
дайте ему фикстуру, которую набор запрашивает. Здесь менеджер состояния,
хранящий состояние в памяти, проходит `StateManagerContract`:

```python
import dataclasses

import pytest

from sci_etl_core import AsyncStateManager, PipelineMetadata
from sci_etl_core.testing import StateManagerContract


class MemoryStateManager(AsyncStateManager):
    def __init__(self) -> None:
        self._processed: set[str] = set()
        self._metadata = PipelineMetadata()

    async def load_processed_ids(self) -> set[str]:
        return set(self._processed)

    async def mark_processed(self, record_id: str) -> None:
        self._processed.add(record_id)

    async def load_metadata(self) -> PipelineMetadata:
        return dataclasses.replace(self._metadata)

    async def save_metadata(self, metadata: PipelineMetadata) -> None:
        metadata.touch()
        self._metadata = dataclasses.replace(metadata)


class TestMemoryStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self):
        manager = MemoryStateManager()
        return lambda: manager
```

Теперь `python -m pytest` запускает каждый тест набора против
`MemoryStateManager`. Сам класс набора не собирается, потому что его имя не
начинается с `Test`.

Фикстура возвращает фабрику: вызываемый объект без аргументов, который при
каждом вызове возвращает новый экземпляр над тем же хранилищем, как его
открывает каждый запуск пайплайна. Набор вызывает её в одном тесте больше
одного раза, чтобы проверить, что сохранённое одним экземпляром загружает
следующий. Компонент, который хранит состояние в памяти, как приведённый выше,
каждый раз возвращает один и тот же экземпляр. В каждом тесте хранилище
начинается пустым, поэтому создавайте его из `tmp_path` или внутри фикстуры.
Набор вызывает фабрику внутри работающего цикла событий и завершает каждый
экземпляр так, как завершается запуск: состояние менеджера состояния
записывается на диск, затем менеджер закрывается через `aclose()`, если этот
метод у него есть, а экспортёр или векторное хранилище закрывается.

## Фикстуры {#fixtures}

| Набор | Обязательные фикстуры | Необязательные фикстуры |
|-------|-----------------------|-------------------------|
| `ExtractorContract` | `make_extractor` | `make_unavailable_extractor` |
| `StateManagerContract` | `make_state_manager` | `write_newer_schema` |
| `ExporterContract` | `make_exporter`, `read_exported` | `make_entities`, `write_newer_schema` |
| `EmbeddingStoreContract` | `make_store` | `write_newer_schema` |

- **`make_extractor`, `make_state_manager`, `make_exporter` и `make_store`**
  возвращают фабрику, описанную выше.
- **`read_exported`** возвращает асинхронный вызываемый объект, который
  принимает id записи и возвращает сущности, которые место назначения хранит
  для этой записи, или пустую последовательность. Набор сравнивает два
  чтения, поэтому возвращайте форму, которая равна при одинаковом содержимом.
- **`make_entities`** возвращает вызываемый объект, который создаёт `count`
  различных сущностей для записи. По умолчанию он создаёт словари с ключами
  `name` и `value`; переопределите его, если ваш экспортёр принимает другие
  сущности, например утверждения.
- **`write_newer_schema`** возвращает вызываемый объект, который записывает в
  хранилище, открываемое фабрикой, файл или базу данных с более новой версией
  схемы, чем поддерживает ваш компонент. Набор вызывает его до создания
  экземпляра и ожидает `SciEtlError`. По умолчанию возвращается `None`.
- **`make_unavailable_extractor`** возвращает фабрику экстрактора, источник
  которого отвечает на каждый запрос ошибкой на стороне сервера, например
  статусом `503`, без ожидания между повторными попытками. Набор ожидает
  `UpstreamError`, а не пустую страницу. По умолчанию возвращается `None`.

Тот же набор для менеджера состояния, запущенный против встроенного
SQLite-менеджера состояния, также проверяет, что база данных из более нового
релиза отвергается:

```python
import sqlite3
from contextlib import closing

import pytest

from sci_etl_core import AsyncSqliteStateManager
from sci_etl_core.testing import StateManagerContract


class TestSqliteStateManager(StateManagerContract):
    @pytest.fixture
    def make_state_manager(self, tmp_path):
        return lambda: AsyncSqliteStateManager(tmp_path / "state.db")

    @pytest.fixture
    def write_newer_schema(self, tmp_path):
        def write():
            with closing(sqlite3.connect(tmp_path / "state.db")) as connection:
                connection.execute("PRAGMA user_version = 99")

        return write
```

Экспортёру нужна ещё фикстура `read_exported`, которая читает место
назначения обратно:

```python
import pytest

from sci_etl_core.exporters import AsyncJsonlExporter, read_jsonl_export
from sci_etl_core.testing import ExporterContract


class TestJsonlExporter(ExporterContract):
    @pytest.fixture
    def make_exporter(self, tmp_path):
        return lambda: AsyncJsonlExporter(tmp_path / "out.jsonl", fsync=False)

    @pytest.fixture
    def read_exported(self, tmp_path):
        async def read(record_id):
            return read_jsonl_export(tmp_path / "out.jsonl").get(record_id, [])

        return read
```

## Тестирование экстрактора без сети {#testing-an-extractor-offline}

Набор для экстракторов никогда не обращается к сети. Отдавайте листинг из
заглушки, например из `httpx.AsyncClient`, построенного на
`httpx.MockTransport`, и пусть она каждый раз одинаково отвечает на один и тот
же запрос. Листинг должен содержать хотя бы две страницы для запроса набора и
заканчиваться не позже чем через `max_pages` страниц. Задайте эти атрибуты
класса в своём подклассе под свой источник:

| Атрибут | По умолчанию | Значение |
|---------|--------------|----------|
| `query` | `"contract"` | Запрос, который листингует каждый тест |
| `page_size` | `2` | Размер страницы, который запрашивает каждый тест |
| `max_pages` | `50` | Наибольшее число страниц, за которое листинг должен закончиться |

## Необязательные возможности и пропуски {#optional-capabilities-and-skips}

Тест, который проверяет необязательную возможность, пропускается с указанием
причины, если у вашего компонента её нет:

- **Менеджеры состояния:** неудачные попытки, если `record_failure` оставлен
  по умолчанию и ничего не отслеживает; `forget`, если менеджер состояния не
  `Forgetting`; повторное использование после `aclose()`, если у него нет
  `aclose`.
- **Экспортёры:** чтение записанного до `flush`, если `durable_writes` равно
  `False`.
- **Векторные хранилища:** `iter_records`, если хранилище оставляет реализацию
  по умолчанию, которая выбрасывает `NotImplementedError`.
- **Экстракторы:** тест смещений, если экстрактор не `OffsetListing`; тест
  недоступного источника, если `make_unavailable_extractor` возвращает `None`.
- **Менеджеры состояния, экспортёры и векторные хранилища:** тест версии
  схемы, если `write_newer_schema` возвращает `None`.

## Что проверяют наборы {#what-the-suites-check}

- **`ExtractorContract`:** первая страница — корректный `ListingPage` с
  записями и следующим курсором; следующий курсор снова возвращает ту же
  страницу, в том числе из нового экстрактора, как её запрашивает
  возобновлённый запуск; переход по следующим курсорам доводит листинг до
  конца, а у усечённой страницы нет следующего курсора; для `OffsetListing`
  смещение 0 — это первая страница, а число записей первой страницы —
  смещение второй; `fetch_full_text` возвращает строку; недоступный источник
  выбрасывает `UpstreamError`.
- **`StateManagerContract`:** новое хранилище пусто; обработанные id,
  сохранённые метаданные и неудачные попытки доходят до следующего
  экземпляра; все одновременные пометки сохраняются; `save_metadata` ставит
  время запуска; `mark_processed` очищает попытки записи; `forget` очищает
  пометки и попытки и сохраняет курсор; состояние с более новой версией схемы
  отвергается; менеджер состояния снова работает после `aclose()`.
- **`ExporterContract`:** запуск экспортирует сущности каждой записи;
  повторная запись — одновременная, в том же запуске или в следующем —
  оставляет то же, что одна запись; запись без сущностей не хранит ни одной;
  запуск без записей завершается успешно; экспортёр снова работает после
  `aclose()`; при `durable_writes = True` записанное можно прочитать до
  `flush`; место назначения с более новой версией схемы отвергается.
- **`EmbeddingStoreContract`:** новое хранилище пусто; чанк, снова добавленный
  под тем же id записи и индексом, заменяет старый; чанки доходят до
  следующего экземпляра; результаты идут от лучшего по косинусному сходству и
  учитывают `top_k`, `min_score` и `exclude_record_id`; вектор с NaN никогда не
  совпадает; `delete_record` и `replace_record` не оставляют старых чанков
  записи; `iter_records` выдаёт фрагменты по порядку; хранилище снова
  работает после `aclose()`; хранилище с более новой версией схемы
  отвергается.

Наборы проверяют поведение только через публичные методы.
[Таблица контрактов](../project/contributing.md#adding-a-new-component)
перечисляет, что должен делать каждый компонент, а
[справочник API по тестированию](../reference/testing.md) описывает каждый
набор.
