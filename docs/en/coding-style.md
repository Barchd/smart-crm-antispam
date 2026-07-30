# Code Style

## General rules

- Python 3.14, Django 6.0 conventions
- Business logic lives in `services/*.py`, not in views
- Views are thin: auth + service call + render/redirect
- Models: fields + simple properties; no heavy business logic
- No secrets in code

## Naming

- Classes: PascalCase (`InboundRequest`, `RiskResult`)
- Functions/variables: snake_case (`evaluate_rules`, `process_request_by_rules`)
- Constants: UPPER_SNAKE (`RISK_SIGNAL_SCORES`, `UA_MIN_LENGTH`)
- Models: singular (`Deal`, `Client`, `InboundRequest`)

## Models

```python
# Good: fields + simple properties
class InboundRequest(models.Model):
    phone_raw = models.CharField(...)
    
    @property
    def has_ai_analysis(self) -> bool:
        return bool(self.ai_topic)

# Bad: business logic on the model
class InboundRequest(models.Model):
    def process(self):   # ← belongs in services.py
        ...
```

## Services

```python
# services.py — keyword-only arguments
def process_request_by_rules(*, inbound: InboundRequest) -> InboundRequest:
    risk = evaluate_rules(inbound)
    store_risk_result(inbound=inbound, risk=risk)
    ...
```

- Use `*` for keyword-only args (avoids positional mistakes)
- `@transaction.atomic` for write operations
- Return the object (not `None` on success)

## Views

```python
@login_required
def some_view(request):
    if not is_head(request.user):
        raise PermissionDenied
    # service call
    result = some_service(...)
    return render(request, "template.html", {"result": result})
```

## Tests

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

- One assert per test (or a related set)
- Use unique `external_id` in every test
- Call `refresh_from_db()` after DB changes

## Documentation

- Docstrings for public functions
- Comments only for non-obvious code
- ADRs for architecture decisions: [docs/en/decisions/](decisions/)
