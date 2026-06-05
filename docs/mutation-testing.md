# Mutation Testing

## Why

Line coverage tells you which code was **executed**, not whether your tests
would **catch a regression** if that code changed. Mutation testing modifies
your source code (creates "mutants") and checks whether any test fails. If a
mutant survives, your tests missed a behavioral change.

## Setup

`mutmut` is included in the dev dependencies:

```bash
pip install -e ".[dev]"
```

Configuration in `pyproject.toml`:

```toml
[tool.mutmut]
paths_to_mutate = "squad_runtime/"
tests_dir = "tests/"
```

## Running

```bash
mutmut run
mutmut results
```

To see surviving mutants:

```bash
mutmut show <mutant_id>
```

## Interpreting Results

| Metric | Meaning |
|--------|---------|
| Killed | Test suite detected the mutation |
| Survived | No test caught the change |
| Timeout | Mutation caused infinite loop |
| Suspicious | Mutation caused unusual behavior |

**Target: mutation score >= 60%.**

A low score on a module means tests exercise the code but don't assert its
correctness tightly enough. Focus on state machine transitions, gate logic,
and security paths.
