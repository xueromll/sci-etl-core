# استهلاك الرموز

تُعيد `AsyncOpenAICompatibleClient.usage` و`AsyncOpenAIEmbedder.usage` لقطة
`TokenUsage` محسوبة على كل الاستجابات التي تلقّاها العميل، بما فيها الاستجابات
التي رُفض متنها لاحقًا:

```python
async with pipeline:
    await pipeline.run(query="all:galaxy", total_limit=50)
usage = llm.usage
print(f"{usage.requests} requests, {usage.prompt_tokens} prompt and {usage.completion_tokens} completion tokens")
```

يحتوي `TokenUsage` على `requests` و`prompt_tokens` و`completion_tokens`
و`total_tokens`. وتُحسب الاستجابة التي لا تتضمن بيانات استهلاك طلبًا برموز
عددها صفر. أما تطبيقات `AsyncLLMClient` و`AsyncEmbedder` الأخرى فتُعيد `None`
ما لم تُعِد تعريف الخاصية `usage`.
