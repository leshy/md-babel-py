# Integration Test

## Session support

```python session=main
x = 42
print(f"x is {x}")
```

```python session=main
y = x * 2
print(f"y is {y}")
```

## Expected error

```python expected-error
# This should fail - no session, x is not defined
print(f"x is {x}")
```

## Skip

```python skip
# This block won't run
this_would_error()
```

## No-result (but still executes in session)

```python session=main no-result
# This runs but doesn't insert result
z = y + 10
```

```python session=main
# Should see z from previous block
print(f"z is {z}")
```
