from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LLMRoute:
    model: str
    temperature: float
    max_tokens: int
    timeout: int
    fallbacks: list[LLMRoute] = field(default_factory=list)


# Резюме отзывов критиков/игроков — короткий, детерминированный вывод
SIMPLE_ROUTE = LLMRoute(
    model="claude-haiku-4-5",
    temperature=0.1,
    max_tokens=700,
    timeout=30,
)

# Заключение по летсплею (Дополнительная часть 1) — короткая выжимка из
# транскрипта, той же формы что и SIMPLE_ROUTE; Haiku вместо ранее используемой
# Kimi K2 Thinking — задача экстрактивная, reasoning не нужен, и thinking-модель
# делает цену непредсказуемой (думающие токены считаются как output).
REASONING_ROUTE = LLMRoute(
    model="claude-haiku-4-5",
    temperature=0.3,
    max_tokens=600,
    timeout=30,
)
