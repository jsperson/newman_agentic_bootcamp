# Fix: Email Column Length Limit

## Issue
The `email` column in the `users` table is limited to 50 characters (`String(50)`), which is too short for many valid email addresses.

## Location
- **File:** `app/models.py`
- **Line:** 10

## Proposed Change
Change `String(50)` to `String(254)` for the `email` column.

**Rationale:** Per RFC 5321, the maximum length of a valid email address is 254 characters. This is the widely accepted standard limit.

### Before
```python
email: str = Column(String(50), unique=True, index=True)
```

### After
```python
email: str = Column(String(254), unique=True, index=True)
```

## Migration Note
Since this project uses SQLite with no migration tooling, existing databases will need the table recreated or an `ALTER TABLE` statement applied manually. For a fresh database, the change takes effect immediately.
