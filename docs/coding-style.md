# Code Style

## Общие правила

- Python 3.14, Django 6.0 conventions
- Бизнес-логика — в services/*.py, не во views
- Views — тонкие: авторизация + вызов сервиса + render/redirect
- Models — поля + простые свойства; без сложной бизнес-логики
- Без секретов в коде

## Именование

- Классы: PascalCase (`InboundRequest`, `RiskResult`)
- Функции/переменные: snake_case (`evaluate_rules`, `process_request_by_rules`)
- Константы: UPPER_SNAKE (`RISK_SIGNAL_SCORES`, `UA_MIN_LENGTH`)
- Модели: singular (`Deal`, `Client`, `InboundRequest`)

## Модели

```python
# Хорошо: поля + простые свойства
class InboundRequest(models.Model):
    phone_raw = models.CharField(...)
    
    @property
    def has_ai_analysis(self) -> bool:
        return bool(self.ai_topic)

# Плохо: бизнес-логика в модели
class InboundRequest(models.Model):
    def process(self):   # ← лучше в services.py
        ...
```

## Services

```python
# services.py — функции с keyword-only аргументами
def process_request_by_rules(*, inbound: InboundRequest) -> InboundRequest:
    risk = evaluate_rules(inbound)
    store_risk_result(inbound=inbound, risk=risk)
    ...
```

- Используй `*` для keyword-only args (избегает позиционных ошибок)
- `@transaction.atomic` для операций записи
- Возвращай объект (не None при успехе)

## Views

```python
@login_required
def some_view(request):
    if not is_head(request.user):
        raise PermissionDenied
    # вызов сервиса
    result = some_service(...)
    return render(request, "template.html", {"result": result})
```

## Тесты

```python
class MyTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(...)
    
    def test_something_specific(self):
        # Arrange
        inbound = self._make_inbound(phone="+7 999 000-00-00")
        # Act
        result = process_request_by_rules(inbound=inbound)
        # Assert
        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.PROCESSED)
```

- Один assert на тест (или связанный набор)
- Используй `external_id` уникальные в каждом тесте
- `refresh_from_db()` после изменений в БД

## Документация

- Docstrings для публичных функций
- Комментарии только для неочевидного кода
- ADR для архитектурных решений: [docs/decisions/](decisions/)
