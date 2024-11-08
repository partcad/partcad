# PROMPTS

## Test Generation

> Generate gherkin test for {filename}.

> Generate gherkin test for %function% in {filename}. Add tags.

```
In your prompts, you can use the following placeholders to refer to specific parts of your codebase:

* `{function}`: the name of a function or method
* `{filename}`: the name of a file
* `{classname}`: the name of a class
* `{variable}`: the name of a variable
* `{directory}`: the name of a directory

You can also use more specific placeholders, such as:

* `{python_function}`: a Python function
* `{java_class}`: a Java class
* `{javascript_variable}`: a JavaScript variable

Additionally, you can use placeholders to specify the type of code or test you want to generate, such as:

* `{test}`: a test for a specific piece of code
* `{unit_test}`: a unit test for a specific function or method
* `{integration_test}`: an integration test for a specific feature or API endpoint

You can combine these placeholders to create more specific prompts, such as:

* "Generate a unit test for the `{python_function}` in `{filename}`"
* "Create a Gherkin test for the `{java_class}` in `{directory}`"

Feel free to get creative with your prompts, and I'll do my best to understand what you're asking for!
```