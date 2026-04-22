### browser_inputs

Discover all input elements on the current page.

Returns a JSON array of input info objects with:
- `index`: Use this with `browser_fill` or `browser_set_input`
- `type`: Input type (text, password, email, checkbox, etc.)
- `name`: Input name attribute
- `placeholder`: Placeholder text if any
- `value`: Current value
