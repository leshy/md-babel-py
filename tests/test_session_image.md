

```python session=main
bla = "from previous code block"
print(bla)
```

<!--Result:-->
```
from previous code block
```

now we verify we have access to variables from previous code block

```python session=main output=output/test.svg
svg = '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="50"><text x="10" y="30">' + bla + '</text></svg>'
with open("{output}", "w") as f:
    f.write(svg)

print("wrote", "{output}")
```

<!--Result:-->
![output](output/test.svg)


```python session=main
# verify the SVG was created with content from session
with open("output/test.svg") as f:
    content = f.read()

assert bla in content, f"Expected '{bla}' in SVG"
print("SVG verified:", content[:50] + "...")
```

<!--Result:-->
```
SVG verified: <svg xmlns="http://www.w3.org/2000/svg" width="300...
```
