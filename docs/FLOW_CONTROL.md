# Flow control

Decided with the owner on 2026-10-16. ActiveBatch's Jobs Library was the point of comparison: borrowed from where it helps, not copied.

## What a job can now hold

A job's steps form a tree. Most steps do one thing; a **block step** holds other steps and decides which of them run, and how often.

| Step type | Holds | What it does |
|---|---|---|
| **If** | one **Then**, any number of **ElseIf**, at most one **Else**, in that order | Runs the Then of the first condition that holds (its own, then each ElseIf's); the Else if none does |
| **ElseIf** | one **Then** | Its own condition, tried when the ones before it did not hold |
| **Then**, **Else** | any steps | The steps of one branch. Hidden: never chosen from the step type list, put in place by the editor |
| **For Each File** | any steps | Runs its steps once for each file at a location, naming the file (say `File`) for the steps inside |
| **While** | any steps | Runs its steps again and again while its condition holds, up to `MaxIterations` passes |

Then, ElseIf and Else exist only inside an If (a Then also inside an ElseIf). The editor shows them as headers of the If, not as steps of their own.

**First version:** If/ElseIf/Else, For Each File and While. Later: a general For Each (rows of a SQL step's result, a list), Break and Continue, and SQL row outputs.

### In the database

- `JobSteps.ParentStep_id`: the block step a step sits in; empty at the top level, so every job built before this is unchanged.
- `JobSteps.StepOrder`: the position among the steps of the same block.
- Then, ElseIf and Else are step types of their own, so no "branch" column is needed.

### Numbering

Top-level steps are numbered 1, 2, 3. The steps inside step 3 are 3.1, 3.2 and so on. Then, ElseIf and Else take no number of their own: the steps of all an If's branches are numbered in one run, so the If at 3 holds 3.1 (Then), 3.2 (ElseIf) and 3.3 (Else).

```
3    If  %{CheckFiles.FileCount} = 0
       Then:     3.1 Send alert
       ElseIf    %{CheckFiles.FileCount} > 100
       Then:     3.2 Split batch
       Else:     3.3 Copy to archive
```

## Names, outputs and context

### StepName

Every step has a **StepName**: letters, digits and `_`, starting with a letter. It is how other steps refer to it.

- The editor fills it in from the title as the title is first typed, with spaces turned into underscores ("Check files" gives `Check_files`). Once the name is edited by hand, the title no longer changes it. A saved step's name never changes by itself, because other steps may use it.
- Names need not be unique. A step that runs later replaces what an earlier step of the same name left, as in ActiveBatch. That allows a step called `Fetch` in both the Then and the Else, read after the If as `%{Fetch.Status}`; and in a loop, each pass replaces the last.
- A step saved without a name gets one from its title, or `Step<n>`.

### Outputs

After a step runs, what it did can be read by the steps after it as `%{StepName.Output}`.

Every step has these, set by the runner whatever its type:

| Output | |
|---|---|
| `Status` | `SUCCESS`, `FAILED` or `SKIPPED` (not run: a branch not taken, a loop with nothing to do) |
| `ReturnCode` | 0 for success, 1 for failure. A step that runs a program will give the program's own |
| `ErrorMessage` | Why it failed; empty otherwise |
| `StartTime`, `EndTime` | When it ran, as `2026-10-16 14:03:07` |
| `DurationMs` | How long it took, in milliseconds |

Each step type declares its own besides, as it declares its parameters (`OUTPUTS` in its handler; `GET /api/v1/step-types` lists them):

| Step type | Its own outputs |
|---|---|
| Copy Files | `FileCount`, `Bytes` |
| Check Files | `FileCount`: how many matched, set even when the check fails |
| Delete Files, Unzip Files | `FileCount` |
| Zip Files | `FileCount`, `ArchiveName` |
| For Each File | `FileCount` |
| While | `Passes`, readable inside the loop and in its own condition as it goes, 0 before the first pass |

A step not yet run, or never run, has `Status` `SKIPPED` and no other outputs.

### For Each File and its file

The loop names its file (its `ItemName` parameter, default `File`). Inside the loop the file is an object; its properties are read with `%{File.Name}` and the like:

| Property | Example |
|---|---|
| `Name` | `inv_02.csv` |
| `BaseName` | `inv_02` |
| `Extension` | `.csv` |
| `FullName` | `/data/billing/out/inv_02.csv` |
| `Directory` | `/data/billing/out` |
| `Size` | `2048` (bytes) |
| `Modified` | `2026-10-16 14:03:07` |
| `Index` | `2`: which pass this is, counting from 1 |
| `Count` | `5`: how many files the loop has |

`%{File}` on its own is not a value, and the pre-run check says so, listing the properties.

The files are found once, when the loop starts. A step inside the loop may use the file's path as its own location, even when the loop reads from a registered endpoint outside the working folder: the path is accepted because it lies in the folder the loop reads from, and the operations it records point at that endpoint, so the trace follows the file.

### `%{...}` and `${...}`

- `${...}` is a job-level variable, filled in before the job starts, as it always has been.
- `%{...}` is a value from the run itself: a step's output or a loop's file. It is filled in as each step starts, so it may be used in any step parameter as well as in conditions: a Copy Files step inside a loop takes `%{File.FullName}` as its source.

## Conditions

If, ElseIf and While take a condition, written as a SQL `WHERE` clause:

```
%{Check_files.Status} = 'SUCCESS' AND %{Check_files.FileCount} > 0
%{File.Name} LIKE 'inv_%' AND %{File.Size} BETWEEN 1 AND 1000000
%{File.Extension} IN ('.csv', '.txt')
%{Archive.ErrorMessage} IS NULL OR ${RetryCount} >= 3
lower('%{File.BaseName}') <> 'readme'
```

- **Operators:** `=`, `<>` (or `!=`), `<`, `<=`, `>`, `>=`, `AND`, `OR`, `NOT`, `LIKE`, `IN (...)`, `BETWEEN ... AND ...`, `IS NULL`, `IS NOT NULL`, parentheses, and arithmetic.
- **Functions:** SQLite's own, such as `lower`, `upper`, `length`, `trim`, `substr`, `instr`, `replace`, `coalesce`, `abs`, `round`, and `date('now', '-1 day')`.
- **Text** goes in single quotes. Double quotes are accepted too, and mean the same.
- **Case:** `=` tells upper and lower case apart, as everything in AutoApp does; `LIKE` does not.

How values go in:

- A `%{...}` or `${...}` **inside quotes** is filled in as text, so `'%{File.BaseName}_old'` needs no joining. A quote inside the value cannot end the text early.
- **Outside quotes**, a value goes in as itself: a number as a number, text as text, nothing as `NULL`. A variable's value that reads as a number (`10`, `2.5`) counts as a number, so `${Limit} > ${Count}` compares numbers.
- Nothing a value holds can change what the condition means: values are never pasted into the condition's text outside quotes.

Checks:

- **Before the run**, every condition is checked like any other parameter: that it is a valid condition, that each `%{Name...}` names a step in the job or a loop's file around it, and that the output or property exists. A step's name used inside its own loop's condition (a While waiting for a check inside it) is fine.
- **In the editor**, a comparison of text with a number is pointed out, where both sides are known: `%{File.Size} > '100'`, or two variables, one holding a number and the other not.
- **When it runs**, a condition that is true, false or empty (`NULL`, which counts as false) is logged with the values it used.

Conditions are worked out by SQLite, which comes with Python, in a database of its own that holds nothing and may only compute values.

## When a step fails

Every step has **On failure**:

| Choice | |
|---|---|
| **Fail the job** (default) | The job stops and fails, as before |
| **Continue** | The job goes on with the next step; `%{Name.Status}` is `FAILED` |
| **End the job with success** | The job stops at once and reports success |

It applies to block steps too: a While that reaches `MaxIterations` fails, and its On failure says what happens next. A step that fails inside a loop and is set to Continue lets the loop go on to the next pass. A block whose own work went well is `SUCCESS` even if a step inside it failed and continued.

## Loops are limited

- **While:** `MaxIterations` is required (default 100). Going past it fails the step, naming it. `WaitSeconds` (default 0) pauses before each pass after the first, for "poll until the file arrives".
- **For Each File:** as many passes as files found when it starts. No files, no passes: the loop succeeds, unless `AllowNoFiles` is False.

## Log and trace

- Each step is named by its number: `BEGIN Step 3.1: Copy (Copy Files)`.
- Inside a loop the pass is named too: `[File 2 of 5: inv_02.csv]`, or `[pass 3]` for a While.
- An If says which branch it took, and each condition the values it used: `Condition: %{Check.FileCount} > 0  is false, with %{Check.FileCount} = 0`, then `END Step 4: If late (If): took the Else branch.` (or `no condition held, so no branch ran.`).
- A step that fails and carries on, or ends the job with success, says so, quoting its On failure.
- Each operation records its step's number (`Operations.StepNumber`, e.g. `3.1`) and pass (`Operations.Iteration`, e.g. `2`, or `2.3` in nested loops). The Operations Log shows both; the trace keeps the passes of a loop apart (each pass's zip is its own archive).
