# UI Vision

What the AutoApp web interface should contain and how it should behave. This is the specification the interface is built from.

**Built so far:** the Main Index and the Operations Log, including the trace. See the blueprint for how the pages are put together.

It is based on the 2024 mockup deck (linked from the original design document) and adapted to the current data model. Items marked **Proposed** are not in the mockups and need a decision.

## Principles

- The interface talks only to the REST API. It never reads the database directly. This keeps it replaceable and lets a scheduler integration use the same API.
- Two kinds of page: **search pages** for finding records, and **detail pages** for viewing and editing one record.
- Records of what happened (operations, audits, job history) are read-only and have no detail page; everything meaningful is shown in the search results.
- Pages update in place. Expanding a job, reordering a step or unlocking a form does not reload the page.

## Navigation

A header with the AutoApp name and the page title, and a navigation bar on every page:

| Left | Centre | Right |
| :--- | :--- | :--- |
| Main Index | Applications, Entities, Sites, Jobs, Endpoints | Operations Log, Job History, Audit Log |

- The mockups show Processes, Sources and Deliveries. Processes is now Jobs, and Sources and Deliveries are the single Endpoints section.
- **Proposed:** an Admin group for Step Types, Tags and Credentials.

## Behaviour common to all search pages

- A criteria form above a results table.
- Text criteria are case-insensitive and match anywhere in the field.
- Date and time criteria are From/To pairs with date-time pickers, and are inclusive.
- In the results, the identifying columns (ID, name, abbreviation or key) link to the record's detail page.
- An **Export as CSV** button exports the current results. The export may include columns the table hides.
- Results are capped (the 2024 pages used 500 rows) and say when the cap was reached.

## Behaviour common to all detail pages

- A selector at the top lists records as `<id> | <name>`. It is searchable: typing narrows the list.
- Fields are locked (grey) on arrival.
- **Edit** unlocks the editable fields (white). It is disabled if the user may not modify the record.
- **Submit** is disabled until a field has changed.
- Required fields are marked with a red asterisk.
- ID, created and modified fields are always read-only.
- **Proposed:** a **New** button beside the selector to create a record, and **Deactivate** in place of delete for anything a job might reference.
- **Proposed:** every detail page for an object that can hold variables (application, entity, site, job, tag) has a **Variables** panel. See below.

## Page inventory

| Page | Kind | Origin | Notes |
| :--- | :--- | :--- | :--- |
| Main Index | index | Mockup | **Built.** Links to every page |
| Application Search / Detail | search, detail | Mockup | Name, abbreviation, description, support distribution list |
| Entity Search / Detail | search, detail | Mockup (same pattern as Application) | An entity's sites are listed on its detail page |
| Site Search / Detail | search, detail | Mockup (same pattern) | Host, port, protocol, owning entity, credential |
| Job Search / Detail | search, detail | Mockup's Process pages, changed | Detail page is the job editor |
| Endpoint Search / Detail | search, detail | Replaces Source and Delivery pages | See below |
| Operations Log | search | Mockup, changed | **Built.** The file trace; see below |
| Job History | search | Mockup | Reads `JobRuns`: one row per run, with status and error |
| Audit Log | search | Mockup | Read-only. Changes to definitions: who changed what, and when |
| Async Parent Process Search / Detail | search, detail | Mockup | Deferred until asynchronous processes are rebuilt |
| Step Type Detail | detail | Mentioned in the design document, no mockup | **Not planned.** Step types are seen where they matter, in the job editor |
| Tag Search / Detail | search, detail | **Proposed** | Waits on the tag design |
| Credential Search / Detail | search, detail | **Proposed** | Secret values are write-only: they can be set, never displayed |

## The job editor (Job Detail)

The central page. It follows the mockup's Process Detail page with the process level removed: a job, its steps, and each step's parameters, nested and expandable in place.

```
Job   id, JobKey*, Description, Active                             [Edit]
  Step(s)
  > Step   id, Order (up/down), Title, Enabled
  v Step   id, Order (up/down), Title, Enabled
        Step Type: [Copy Files v]
        Parameters
          Source*   (o) Endpoint [LEGAL_APP_EXTRACTS v] [New...]
                    ( ) Working folder path [                 ]
          Dest*     ( ) Endpoint [                   v] [New...]
                    (o) Working folder path [incoming         ]
          Move      [ ]
                                                         [Add Step]
[Submit]
```

**From the mockup**

- Steps expand and collapse with a triangle. Collapsed rows show the summary fields only.
- Steps are reordered with up and down arrows. Each step has an Enabled checkbox.
- **Add Step** appends a new row, expanded and ready to fill in.
- One **Submit** saves the job with its steps and parameters.

**Changed from the mockup**

- There is no process. The mockup's page opened on a process and nested its jobs; this page opens on one job. The process's Name, Application, Client and Severity fields are gone.
- `JobKey` replaces the job's Name and Job Order. It is the job's unique name and the value the scheduler passes. The page shows the exact command line a scheduler would use.
- The mockup shows Step Type and Step Function. There is now one value, the step type.

**Proposed**

- **Parameters come from the step catalog.** Choosing a step type shows that type's parameters as form fields, in a defined order, with required ones marked, defaults filled in and a description on hover. Boolean parameters are checkboxes. No free-form parameter names. The catalog is built and served at `GET /api/v1/step-types`.
- **File locations are a choice, not a text box.** Each location parameter offers either an endpoint picker or a path inside the job's working folder. The picker is searchable and has **New...**, which opens a small form to register an endpoint without leaving the page.
- **Placeholder preview.** Beside any value containing `${...}`, a preview shows what it resolves to for this job, or the error if it cannot be resolved.
- **Validation before saving.** Submit reports problems against the field that caused them: a missing required parameter, an unknown endpoint, an unresolved placeholder, a path outside the working folder. The check itself is built (`GET /api/v1/jobs/{job_key}/check`); it reports problems per step, not yet per field.
- **Remove** on jobs and steps, with a confirmation.
- A **Variables** panel on the job.
- **Duplicate**, to start a new job from an existing one.

## Endpoints

Replaces the Source and Delivery pages.

- **Search criteria:** name, application, site, entity (through the site), path, filename pattern, description.
- **Detail fields:** name*, application, site, path*, filename pattern*, description. The site's entity is shown read-only.
- **Proposed:** a "Used by" list on the detail page showing every job step that reads from or writes to the endpoint.
- **Proposed:** a "Recent operations" list showing the latest files through the endpoint.

## Operations Log and file trace

The mockup's Operations Search, with source and destination now taken from the endpoint register.

- **Criteria**, grouped as in the mockup:
  - Date and time range, operation type
  - Source: endpoint, path, filename
  - Destination: endpoint, path, filename
  - Automation: job, instance ID, run number, scheduler
  - Entity, application, site (matched on either side)
- **Results:** one row per operation, with a Source block and a Destination block. Each block shows endpoint, application, entity, site, path, filename and size. A side that was inside the working folder says so. Then start and end time, and the job and instance.
- **Proposed: Trace.** A link on any row shows that file's whole route: every operation that handled it, in order, from the endpoint it entered by to the endpoint it left by. A file copied to two places shows as two branches.
- The API behind this page and the trace is built: `GET /api/v1/operations` and `GET /api/v1/operations/{id}/trace`.

## Variables panel (Proposed)

On every detail page for an object that can hold variables.

- A table of name, value, secret flag and description, with add, edit and remove.
- Secret values are masked and cannot be read back.
- On a job: an "Effective variables" view listing every variable the job can see and which level each comes from, so an override is visible.

## Step Type Detail (Proposed)

The catalog that drives the job editor. For administrators.

- A selector of step types.
- Fields: name, code, description, active.
- A child table of parameter definitions: name, data type, required, default, description, display order, and whether it is a file location.
- Step types correspond to handlers in the code, so this page edits how a type is presented, not what it does.

## Differences from the 2024 mockups

| Mockup | Now |
| :--- | :--- |
| Sources and Deliveries sections | One Endpoints section |
| Process Detail page with nested jobs | Job Detail page; there is no process level |
| Source and Dest typed as free text | Endpoint picker, or a path inside the working folder |
| Placeholders written `<WorkingFolder>`, `<yyyyMMdd>` | Written `${...}` |
| Step Type and Step Function | Step type only |
| Operations show Entity and Site looked up from the path | Taken from the endpoints recorded on the operation |
| No pages for variables, tags, credentials or step types | Proposed above |

## Open questions

1. **Related jobs.** Whether the interface needs a way to see several jobs together, for example by tag, now that there is no process to group them.
2. **Users and permissions.** "Edit is disabled unless the user has permission" needs sign-in, users and roles. None exist yet.
3. **Look and feel.** Decided: dark by default with a light option. The light theme keeps the mockups' grey header and black navigation bar.
4. **Inside a scheduler.** Which of these pages would need to appear within a scheduling product, and in what form.
5. **Two people editing the same job.** Last save wins, or warn?

## Suggested build order

1. Operations Log, read-only. **Done.**
2. Endpoint Search and Detail. The simplest pages with editing; they establish the common search and detail behaviour.
3. The job editor.
4. Application, Entity and Site pages, which reuse the Endpoint pattern.
5. Variables panel, Step Type Detail, and the rest.
