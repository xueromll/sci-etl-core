# Установка

Требуется Python 3.11 или новее.

```bash
pip install "sci-etl-core[async,arxiv,llm,pdf]"   # всё, что использует «Быстрый старт»
pip install "sci-etl-core[full]"                  # все встроенные компоненты, кроме локальных эмбеддингов
```

Из клона репозитория:

```bash
pip install -e ".[full]"
```

Базовая установка требует только Pydantic. Она включает оба конвейера,
корректное завершение, события прогресса и метрики запуска, контракты
компонентов, модели конфигурации, бэкенды состояния, кэширование ответов LLM,
экспортёры CSV и JSON Lines, утверждения и происхождение, валидаторы записей,
разбор LaTeX, разбиение текста на фрагменты, булев текстовый поиск, слияние
ранжирований и графы связанных статей. Компонент, которому нужен другой пакет,
импортирует его при импорте самого компонента, поэтому добавьте extras для
компонентов, которые используете:

| Extra | Добавляет | Нужен для |
|-------|-----------|-----------|
| `config` | `pyyaml`, `python-dotenv` | `load_config`, `load_config_async`, `load_yaml` |
| `async` | `httpx`, `aiolimiter` | `AsyncArxivExtractor`, `AsyncPubMedExtractor`, `AsyncSemanticScholarExtractor`, `AsyncOpenAlexExtractor`, `build_async_client`, `AioLimiterRateLimiter` |
| `arxiv` | `beautifulsoup4`, `lxml` | `AsyncArxivExtractor`, которому нужен также `async` |
| `xml` | `lxml` | `JatsXmlParser`, `DocxParser` и `AsyncPubMedExtractor`, которому нужен также `async` |
| `html` | `beautifulsoup4` | `HtmlTextParser`, который `AsyncLLMEntityExtractor` по умолчанию использует для полного текста, начинающегося с разметки |
| `processors` | `pandas`, `numpy` | все шаги в `sci_etl_core.processors`, кроме валидаторов, и табличные приёмники |
| `llm` | `openai`, `tiktoken` | `AsyncOpenAICompatibleClient`, усечение по токенам |
| `pdf` | `pdfplumber` | `PdfPlumberParser` |
| `sql` | `sqlalchemy` | `SqlTableSink`, которому нужен также `processors` |
| `viz` | `plotly` | `Plotly3DSink`, которому нужен также `processors` |
| `cluster` | `scikit-learn`, `numpy` | `ClusteringStep`, которому нужен также `processors` |
| `embeddings` | `numpy`, `openai` | `AsyncOpenAIEmbedder`, векторные хранилища, `AsyncEmbeddingRelevanceFilter` |
| `embeddings-local` | `numpy`, `sentence-transformers` | `AsyncSentenceTransformerEmbedder` |
| `search` | ничего | ничего дополнительного: `sci_etl_core.search` нужна только стандартная библиотека, поэтому этот extra лишь фиксирует, зачем установлен пакет |
| `full` | все пакеты выше, кроме `sentence-transformers` | все встроенные компоненты, кроме локальных эмбеддингов |
| `dev` | pytest с плагинами, `hypothesis` | запуск набора тестов |
| `lint` | `ruff`, `mypy`, заглушки типов | проверка стиля и типов исходного кода |
| `docs` | MkDocs, Material for MkDocs, mkdocstrings, mkdocs-click, mike, mkdocs-static-i18n, `ruff` | сборка этого сайта документации |

Импорт компонента, для которого не установлен нужный extra, вызывает
`ModuleNotFoundError` с именем пакета, который нужно установить.

!!! tip "Нужно просто запустить конвейер?"
    `pip install sci-etl-cli` устанавливает [команду `sci-etl`](../cli/index.md),
    которая запускает проект извлечения данных из arXiv по YAML-файлу без
    кода для связывания компонентов.
