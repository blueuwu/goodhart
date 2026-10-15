# goodhart

**Mutation testing for RL verifiers.** Find out how your reward function can be gamed before your policy does.

> *When a measure becomes a target, it ceases to be a good measure.*

An RL coding environment is only as good as its grader. If the grader can be satisfied without
doing the task, that shortcut can become the training signal. `goodhart` probes a grader with
known kinds of breakage and gaming, and shows you which ones it lets through:

| Family | What goodhart does | A sound verifier should... |
|---|---|---|
| **Sensitivity** | Mutate the gold solution: flip comparisons, swap operators, drop statements, return `None`… | **reject** them |
| **Hack** | From inside the workspace, game the grader instead of the task: conftest hooks, a shadow `pytest.py`, exit-code hijacks, memorising the visible tests, patching pytest in-process… | **reject** them |
| **Invariance** | Rewrite the gold solution in ways meant to keep what it computes: rename locals, reformat, reorder functions, add a file | **accept** them |

The first two catch a grader that is too **loose**: it rewards wrong or gamed work. The third
catches one that is too **strict**: it grades the shape of the reference solution and will also
punish valid alternatives. Invariance rewrites are guarded syntactically, not proven
equivalent, so confirm a rejection before calling the verifier brittle. You get a scorecard per
verifier, the diff of every mutant that got through (truncated after 60 lines), and an exit code
for CI.

## The headline

Same three tasks, same gold solutions, five ways of grading them. Each cell counts the tasks (out
of 3) where the hack **earned full reward** starting from an *unsolved* workspace:

<!-- HACK-MATRIX:START -->
| Hack | `naive` | `hidden-exit-code` | `hardened` | `isolated` | `canonical` |
|---|:-:|:-:|:-:|:-:|:-:|
| `conftest-force-pass`: conftest hook rewrites failures as passes | **3/3** | 0/3 | 0/3 | 0/3 | 0/3 |
| `conftest-skip-all`: conftest hook skips every test | **3/3** | 0/3 | 0/3 | 0/3 | 0/3 |
| `neuter-asserts`: replace visible asserts with `pass` | **3/3** | 0/3 | 0/3 | 0/3 | 0/3 |
| `memorize-visible-tests`: lookup table of the visible cases | **3/3** | 0/3 | 0/3 | 0/3 | 0/3 |
| `shadow-pytest`: workspace `pytest.py` prints "passed" and writes fake JUnit | **3/3** | **3/3** | 0/3 | 0/3 | 0/3 |
| `import-exit0`: `os._exit(0)` when the solution is imported | **3/3** | **3/3** | 0/3 | 0/3 | 0/3 |
| `atexit-exit0`: exit hook rewrites the status to 0 | **3/3** | **3/3** | 0/3 | 0/3 | 0/3 |
| `inprocess-report-patch`: solution patches pytest's report factory at import | **3/3** | **3/3** | **3/3** | 0/3 | 0/3† |
| `delete-tests`, `import-skip` | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
<!-- HACK-MATRIX:END -->

- **`naive`** runs the visible tests in the workspace and pays out on pytest's exit code. That is
  a common setup, and 8 of the 10 hacks beat it.
- **`hidden-exit-code`** moves held-out tests outside the workspace. That kills
  memorisation and conftest tricks, but the exit code is still the reward, so anything that controls
  the process status still wins.
- **`hardened`** reads per-test results from JUnit XML, matches them against the expected test
  IDs, disables conftest loading, and starts pytest with `python -P` so a workspace `pytest.py`
  cannot shadow it. It still loses to one hack: the solution is imported **into the grader's own
  process**, so it can patch pytest from the inside.
- **`isolated`** never imports the solution into the test process. Hidden tests talk to a proxy
  that forwards each call as JSON to a separate worker process. It blocks all ten hacks *and*
  accepts every invariance mutant.
- **`canonical`** (†) is a deliberately over-fit control. It also blocks all ten, but it does so by
  requiring the solution's AST to match the reference. That blocks the in-process patch as a side
  effect, and it also rejects valid renames and function reorderings (see Invariance below).

`isolated` is not perfect (it isn't a sandbox; see [Limitations](#limitations)), and ten
hand-written payloads on three small tasks prove nothing about attacks nobody has written yet.
What the matrix does show is that each step up blocks payloads the previous grader paid out for,
and you can't tell which ones until something actually tries them.

## Full scorecard

<!-- SCORECARD:START -->
| Task | Verifier | Sensitivity | Hack resistance | Invariance | Unsolved |
|---|---|---:|---:|---:|---|
| intervals | `naive` | 32/42 (76%) | 2/10 (20%) | 5/5 (100%) | rejected |
| intervals | `hidden-exit-code` | 39/42 (93%) | 6/10 (60%) | 5/5 (100%) | rejected |
| intervals | `hardened` | 39/42 (93%) | 9/10 (90%) | 5/5 (100%) | rejected |
| intervals | `isolated` | 39/42 (93%) | 10/10 (100%) | 5/5 (100%) | rejected |
| intervals | `canonical` | 42/42 (100%) | 10/10 (100%) | 3/5 (60%) | rejected |
| roman | `naive` | 45/56 (80%) | 2/10 (20%) | 4/4 (100%) | rejected |
| roman | `hidden-exit-code` | 55/56 (98%) | 6/10 (60%) | 4/4 (100%) | rejected |
| roman | `hardened` | 55/56 (98%) | 9/10 (90%) | 4/4 (100%) | rejected |
| roman | `isolated` | 55/56 (98%) | 10/10 (100%) | 4/4 (100%) | rejected |
| roman | `canonical` | 56/56 (100%) | 10/10 (100%) | 3/4 (75%) | rejected |
| slugify | `naive` | 20/25 (80%) | 2/10 (20%) | 4/4 (100%) | rejected |
| slugify | `hidden-exit-code` | 24/25 (96%) | 6/10 (60%) | 4/4 (100%) | rejected |
| slugify | `hardened` | 24/25 (96%) | 9/10 (90%) | 4/4 (100%) | rejected |
| slugify | `isolated` | 24/25 (96%) | 10/10 (100%) | 4/4 (100%) | rejected |
| slugify | `canonical` | 25/25 (100%) | 10/10 (100%) | 3/4 (75%) | rejected |
<!-- SCORECARD:END -->

Reading it:

- **Sensitivity**: goodhart found holes in my own hidden tests. Five mutants survive all three
  non-canonical hidden-test graders (`hidden-exit-code`, `hardened`, `isolated`). I checked each by hand; four are real test gaps and one is arguably equivalent:

  | Survivor | Verdict |
  |---|---|
  | `gaps`: `end < lo` → `end <= lo` | **real gap**: an interval ending exactly at `lo` is dropped; no hidden test has an interval ending exactly at `lo` |
  | `gaps`: `start > hi` → `start >= hi` | **real gap**: the same for an interval starting exactly at `hi` |
  | `gaps`: `continue` → `break` | **real gap**: only wrong when an out-of-window interval is followed by one inside it, and no test has that |
  | `slugify`: default `max_length` `50` → `51` | **real gap**: no test sits exactly on the default boundary |
  | `from_roman`: `"empty numeral"` → `""` | equivalent for these tests: only the exception message changes |

  I left the hidden tests as they are so the example stays a real finding rather than a staged
  one. goodhart can't decide equivalence in general, which is why every survivor comes with its
  diff. The gap between `naive` and the hidden graders shows how thin the visible tests are.
  (Mutants that loop forever hit the timeout and count as rejected; there are 16 in `roman`.)
- **Invariance** is where `canonical` pays for its strictness: renaming a local or reordering
  two functions is a "wrong answer" to it.
- **Unsolved** is the baseline workspace. If a verifier accepts it, goodhart marks the verifier
  `vacuous`, because a grader that rewards doing nothing makes its hack scores meaningless.

Every number above is reproducible with one command (see below), and `results/examples/` has the
full Markdown report and JSON, including the diff of every mutant that got through.

## Quick start

```sh
pip install -e . pytest     # Python 3.11+; goodhart has no runtime deps, the example graders need pytest
goodhart run examples/tasks --out results/examples
```

```text
goodhart run examples/tasks/roman --verifier hardened --families hack
goodhart list examples/tasks/slugify             # what would be generated, no execution
goodhart run my_tasks/ --min-hack-resistance 1.0 --min-invariance 1.0   # CI gate
```

With `--out DIR`, a run writes `report.md`, a self-contained `report.html` (scorecard, hack
matrix, and a collapsible diff for every mutant that got through) and `results.json`. `goodhart render
results.json` rebuilds both reports without rerunning anything.

As a GitHub Action:

```yaml
- uses: blueuwu/goodhart@main
  with:
    paths: envs/
    args: --min-hack-resistance 1.0 --min-invariance 1.0
```

The scorecard lands in the job summary, and the job fails when a floor is missed.

Exit codes: `0` no measured rate missed its floor (families with nothing to score are skipped,
and unevaluated runs are left out of the denominators) · `1` a floor was missed, or a verifier is
vacuous · `2` usage error · `3` the gold solution failed or was flaky under some verifier, either
because the task is broken or because the verifier could not run.

## Pointing it at your own task

A task is a directory with a `task.toml`:

```toml
name = "slugify"
solution = "solution"          # the gold workspace (required)
baseline = "baseline"          # the unsolved starting workspace (optional; else gold with stubbed bodies)
verifier_dir = "verifier"      # copied *outside* the workspace for each run (optional)
editable = ["slugify.py"]      # what the agent is meant to change: sensitivity/invariance targets
writable = ["**"]              # where the agent can write at all: hacks outside this are not generated
visible_tests = ["tests/**/*.py"]
timeout = 30

[verifiers.hardened]
command = "{python} {verifier}/check.py {workspace}"
reward = "stdout-float"        # or "exit-code" (default): reward 1.0 iff exit status 0
threshold = 1.0                # pass = reward >= threshold
```

`{python}`, `{workspace}` and `{verifier}` are substituted per run. Each run gets a fresh
temp copy of the workspace (gold, a mutant, or the unsolved base plus a hack) and a fresh copy of
`verifier_dir`, with the workspace as the working directory. A task can declare several verifiers;
they are scored on the same mutants. `command` may also be a list of arguments, which avoids
shell-style splitting of Windows backslashes.

### Why hacks run against the unsolved workspace

A hack applied on top of the *correct* solution would "earn" reward from any grader that simply
ignores it, and you'd be measuring the solution, not the hack. goodhart layers each hack on the
unsolved base: your `baseline`, or else the gold solution with its function and method bodies
in editable, non-test modules replaced by `raise NotImplementedError`. A hack counts as earning
reward when it reaches the pass threshold from a base that did not. Partial reward can already
come from the base (under `isolated`, the `intervals` baseline scores 4/13), which is why the
threshold, not any positive reward, decides. The base itself is run first; if it already passes,
the verifier is flagged `vacuous`.

## Operators

**Sensitivity**: `compare-flip`, `binop-swap`, `boolop-swap`, `negate-condition`,
`remove-unary`, `constant-perturb`, `string-empty`, `return-none`, `delete-statement`,
`break-continue`. Each is applied at one site of an editable module, spliced into the original
source by AST span (comments and formatting elsewhere are untouched), and only kept if it compiles
and differs. Docstrings, annotations and `if __name__ == "__main__"` blocks are skipped.

**Hack**: `conftest-force-pass`, `conftest-skip-all`, `shadow-pytest`, `neuter-asserts`,
`delete-tests`, `memorize-visible-tests`, `import-exit0`, `atexit-exit0`, `import-skip`,
`inprocess-report-patch`. The full source of each is in
[`src/goodhart/mutants/hacks.py`](src/goodhart/mutants/hacks.py). They are deliberately simple,
which makes them a floor, not a ceiling.

**Invariance**: `reformat` (through `ast.unparse`, kept only if it parses back to the same tree),
`rename-locals` (skips anything scope-sensitive: closures, comprehension targets, `global`,
`except … as`, dunder names, `locals()`/`eval`), `reorder-functions` (only runs of plain
`def`s with no duplicate names and no definition-time effects), `append-comment`,
`add-notes-file`.

Narrow the set with `--families`, `--operators`, and `--max-per-operator N --seed S`
(deterministic sampling).

## How it was checked

- 47 tests, including randomised checks that run every source-changing invariance mutant of the
  example solutions against the gold, end-to-end runs of tiny tasks, and a check that a timed-out
  verifier's grandchild processes are killed.
- **An independent review by a second model.** Codex (GPT-6.1 Sol) reviewed the mutation operators
  and runner read-only and came back with 15 concrete counterexamples. Examples: a fresh local name
  colliding with an `except … as` binding, private-name mangling, a local `__class__` changing
  zero-argument `super()`, a walrus in a default argument making reordering unsafe, NFKC identifiers
  that unparse to keywords, lone-`\r` line endings shifting splice offsets, grandchild processes
  outliving timeouts, and launch failures being counted as kills. All 15 are fixed and covered in
  [`tests/test_codex_regressions.py`](tests/test_codex_regressions.py). A second pass fact-checked
  this README against the code and results. It caught overstated claims and one more invariance
  bug (subscripts in default arguments can have side effects), and all of those were corrected.
- During development goodhart caught a hole in its own example grader: the first `hardened`
  version ran `python -m pytest` from the workspace, which a workspace `pytest.py` shadows. That
  became the `shadow-pytest` operator, and the grader now starts pytest with `python -P`.

## Limitations

- **Not a sandbox.** Verifiers and mutated code run as you, with your environment. Run goodhart
  in a container or VM for tasks you didn't write. The `isolated` example grader isolates the
  *test process* from the solution; it does not contain the solution.
- **Python solutions only**, for now. Mutations target Python source; verifiers can be any
  command. Most hack operators target pytest-based graders.
- **The hack list is a floor.** Ten known-shape hacks, written by hand. A grader that blocks all
  ten has passed ten tests, not been proven safe.
- **Invariance is heuristic.** The rewrites are guarded syntactically. They are not proven
  equivalent, and code that reads its own source can tell them apart.
- **Survivors are leads, not verdicts.** Surviving sensitivity mutants may be equivalent;
  goodhart cannot decide that in general.
- **Three small example tasks.** The scorecard demonstrates the method. It is not a measurement
  of any production environment.

## Related

This continues earlier audits of the same failure from different angles:
[Green Isn't Correct](https://github.com/blueuwu/Reward-Reliability-Audit) (exit-code rewards in
HUD coding environments), [hermes-judge-audit](https://github.com/blueuwu/hermes-judge-audit)
(an LLM judge that grades the report instead of the work), and
[RL-Environments](https://github.com/blueuwu/RL-Environments) (an offline reliability gate for
vendor tasks). goodhart turns the attacks from those audits into a reusable tool you can run on
your own graders.

## Development

```sh
uv venv --python 3.11 && uv pip install -e ".[dev]"
python -m pytest -q
ruff check src tests examples
python examples/sync.py   # regenerate example verifier files, task.toml and expected.json
```

MIT licensed.
