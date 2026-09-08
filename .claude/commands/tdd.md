---
allowed-tools: Bash(poetry run pytest*), Read, Write, Edit, Glob, Grep
description: Test-first workflow for features and bugfixes
---

## RED — Напиши падающий тест

1. Создай тест, описывающий желаемое поведение
2. Запусти: `poetry run pytest tests/test_<file>.py::test_<name> -v`
3. Тест должен УПАСТЬ (не ошибка импорта — именно AssertionError)

## GREEN — Минимальный код

Напиши минимальный код, делающий тест зелёным. Ничего лишнего.

## REFACTOR — Убери дублирование

Только после зелёного. Не добавляй поведение.

## REPEAT

Один цикл = один тест = одно поведение.

## Чеклист

- [ ] Видел тест падающим
- [ ] Написан минимальный код
- [ ] Все тесты зелёные: `poetry run pytest tests/ -q`
- [ ] `poetry run ruff check .` без ошибок
- [ ] `poetry run tach check` без ошибок
