# 类型化实体与校验

除非你用 Pydantic 模型描述实体，否则 `AsyncLLMEntityExtractor` 会以 `dict` 的形式返回模型
写出的对象。使用 `schema=` 后，每个实体在离开提取器之前都会按该模型校验，提取器返回的是
模型实例：

```python
import os

from pydantic import BaseModel, Field

from sci_etl_core import AsyncLLMEntityExtractor, AsyncOpenAICompatibleClient
from sci_etl_core.processors import NumericRangeValidator


class Galaxy(BaseModel):
    name: str
    ra_deg: float | None = Field(default=None, description="Right ascension, decimal degrees, ICRS")
    dec_deg: float | None = Field(default=None, description="Declination, decimal degrees, ICRS")
    effective_radius_kpc: float | None = None


llm = AsyncOpenAICompatibleClient(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.openai.com/v1",
    model="gpt-4o-mini",
    structured_output=True,
)
extractor = AsyncLLMEntityExtractor(
    llm,
    "Extract every ultra-diffuse galaxy the paper reports. Reply with JSON: {\"galaxies\": [...]}.",
    schema=Galaxy,
    result_key="galaxies",
    validator=NumericRangeValidator({"ra_deg": (0.0, 360.0), "dec_deg": (-90.0, 90.0)}),
    label_field="name",
)
```

## 结构化输出 {#structured-output}

请求要求整个回答（`result_key` 下的实体列表）符合根据模型构建的 JSON Schema；
`entity_list_schema(Galaxy, "galaxies")` 会返回这个模式。
`AsyncOpenAICompatibleClient(structured_output=True)` 会把它作为 `json_schema` 响应格式
发送。对于不支持该格式的端点（例如 DeepSeek 的端点），请关闭 `structured_output`：此时请求
以 JSON 模式发出，提示词仍须描述各字段，而每个实体仍会被校验。

你自己的客户端可以通过重写 `complete_structured(system_prompt, user_content, schema, timeout)`
获得结构化输出。默认实现调用 `complete_json`，因此任何客户端都能用于类型化提取。

模式是 LLM 缓存键的一部分，因此修改模型类之后，永远不会返回为旧模型缓存的回答；参见
[LLM 响应缓存](llm-caching.md)。

## 拒绝及其原因 {#rejections-and-their-reasons}

实体未通过模式校验，或被 `validator` 拒绝时，就会被拒绝。校验器在模式检查之后以 `dict` 的
形式看到实体。每次拒绝都会以 `INFO` 级别、连同原因一起记录到
`sci_etl_core.llm.extraction_async` 记录器：

```text
Entity rejected by validation: 'DF44' (ra_deg is 412, outside [0, 360])
```

`RecordValidator.validate(entity)` 返回一个 `ValidationResult`，其中每个 `violations` 项都
给出 `code`、`field`、`severity` 和 `message`。`NumericRangeValidator` 报告
`"out-of-range"` 和 `"not-a-number"`，`KeywordExclusionValidator` 报告 `"null-key"` 和
`"forbidden-keyword"`，模式校验失败报告 `"schema"`，`CompositeValidator` 则汇集它所包含的
每个校验器的违规项。只实现了 `is_valid` 的自定义校验器仍可使用：它的拒绝显示为
`"rejected"`。重写 `validate` 即可说明原因：

```python
from sci_etl_core.processors import RecordValidator, ValidationResult, Violation


class NoPaperLocalNames(RecordValidator):
    def is_valid(self, record):
        return self.validate(record).ok

    def validate(self, record):
        name = str(record.get("name", ""))
        if name.isdigit():
            return ValidationResult(
                violations=(
                    Violation(code="paper-local-name", field="name", severity="error", message=f"{name!r} is a table index"),
                )
            )
        return ValidationResult()
```

`severity="warning"` 的违规项会被报告，但不会导致实体被拒绝。

## 保留被拒绝的实体以供复核 {#keeping-rejected-entities-for-review}

传入一个拒绝记录存储后，每个被拒绝的实体都会连同其违规项、记录 id 以及生成它的模型和提示词
的标记一起保存，这样就能发现拒绝过多的校验器：

```python
from sci_etl_core.claims import AsyncSqliteRejectionStore

rejections = AsyncSqliteRejectionStore("review/rejections.db")
extractor = AsyncLLMEntityExtractor(llm, "Extract galaxies as JSON.", schema=Galaxy, rejections=rejections)


async def review() -> None:
    for entry in await rejections.unresolved(limit=20):
        print(entry.record_id, entry.entity, [violation.message for violation in entry.violations])
        await rejections.resolve(entry.entry_id, "rejection upheld")
```

在之后的运行中再次拒绝同一实体时，只保留一个条目及其处理结论。拒绝记录存储出现故障会导致
该记录失败，并在下一次运行时重试。*被拒绝的实体*与*被隔离的记录*无关，后者是指失败
`max_attempts` 次之后被流水线跳过的记录。

## 感知记录的提取器 {#record-aware-extractors}

流水线调用的是 `extract_record(record, text)`。其默认实现调用 `extract(text)`，因此只重写
了 `extract` 的提取器无需改动即可使用。需要记录本身的提取器（例如
`AsyncLLMClaimExtractor`）会设置 `requires_record = True`，其 `extract` 会抛出
`TypeError`。包装另一个提取器的提取器应调用内层提取器的 `extract_record`，并复制它的
`requires_record`：

```python
from sci_etl_core import AsyncEntityExtractor


class CountingExtractor(AsyncEntityExtractor):
    def __init__(self, inner):
        self.inner = inner
        self.requires_record = inner.requires_record
        self.calls = 0

    async def extract(self, text):
        return await self.inner.extract(text)

    async def extract_record(self, record, text):
        self.calls += 1
        return await self.inner.extract_record(record, text)
```

`AsyncLLMEntityExtractor.prepare(text)` 返回去除标记并截断之后发送给模型的文本，`stamp`
则描述了其实体背后的模型、提示词、模式和库版本。
