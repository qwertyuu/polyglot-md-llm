# Hacker News launch draft

## Submission

**Title**

Show HN: Polyglot PMD - plain-text notebooks with explicit dependencies

**URL**

https://github.com/qwertyuu/polyglot-md-llm

## First comment

Hi HN,

I built Polyglot PMD because I wanted notebooks that behave like normal source
files: readable diffs, explicit dependencies, no hidden in-memory state, and a
document that remains useful when the runtime is gone.

A `.pmd` file is ordinary Markdown with fenced code cells. Python, shell,
PowerShell, and SQL cells run in separate OS processes. Cells can exchange small
JSON values through `ctx`, larger artifacts through declared output files, and
shared source through explicit library cells. A dependency graph controls order
and cache invalidation.

Here is a complete example:

````markdown
```python {#generate independent=true}
ctx.values = [3, 8, 13, 21, 34]
```

```python {#summarize depends-on=generate}
average = sum(ctx.values) / len(ctx.values)
ctx.average = average
display.markdown(f"The mean is **{average:.2f}**.", name="summary")
```

```python {#verify role=test test-of=summarize}
assert ctx.average > 0
```
````

Run it from a clone with Python 3.10+:

```console
git clone https://github.com/qwertyuu/polyglot-md-llm.git
cd polyglot-md-llm
python -m venv .venv
# activate the environment for your shell
python -m pip install polyglot-pmd
pmd check examples/basic.pmd --graph
pmd run examples/basic.pmd --fresh --verbose
pmd test examples/basic.pmd --fresh
pmd render examples/basic.pmd --to html --out example.html
```

The HTML report is self-contained. It includes source, graph, stdout/stderr, and
rich outputs without making network requests. There is also a local browser
workbench (`pmd workbench .`) for editing and running cells.

The `examples/` gallery includes dependency attachments, CSV and Markdown
artifacts, declared input fingerprints, library-cell source composition,
Python/SQL workflows, and JSON context crossing between Python and both POSIX
shell and PowerShell.

The other experiment in the project is an agent protocol for notebooks. An LLM
can request a bounded semantic view, edit cells with revision and content-digest
preconditions, inspect the execution plan, and receive a verification receipt.
Execution is never implied by an edit and requires explicit host authorization.

The important limitation: this is process isolation, not a security sandbox.
Notebook code runs with the invoking user's filesystem and network permissions.
The project reports that boundary directly rather than claiming otherwise.

PMD is alpha software, MIT licensed, and currently has 95 passing tests. I would
especially value feedback on the file format, the separation between context and
file outputs, and whether the agent protocol solves problems people actually see
when using coding agents with notebooks.

Repository: https://github.com/qwertyuu/polyglot-md-llm

## Launch checklist

- Enable GitHub private vulnerability reporting so the `SECURITY.md` link works.
- Confirm the CI workflow is green on Linux and Windows.
- Create a fresh virtual environment and run the commands above verbatim.
- Add one screenshot or short GIF of the rendered report to the README if it
  communicates more than the text example.
- Confirm the public PyPI installation in a clean virtual environment.
- Post when you can stay available for technical questions and bug reports.
