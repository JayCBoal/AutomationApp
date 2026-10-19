# Roadmap

AutoApp's long-term features, beyond workflows. Each item is something RunMyJobs does badly, and the direction AutoApp would take to show a better way. Started 2026-10-18 from discussions with the owner.

- Items here are ideas and directions, not designs. Each one gets a design session when its turn comes, as workflows did.
- When an item starts, its shortcomings become a goal in [PROJECT_GOALS.md](PROJECT_GOALS.md) and its design gets its own page.
- Smaller follow-ups and open decisions stay in [TO-DO.md](TO-DO.md).
- The order below is the order the items were raised. Their priority is not set yet.

## In progress

- **Workflows.** Goal 2 in PROJECT_GOALS.md; the design is in [WORKFLOWS.md](WORKFLOWS.md).

## Features

### Security and permissions

- **In RunMyJobs:** the model is very flexible but monstrously complex to set up and to understand.
- **Direction:** keep the flexibility and make the model far simpler. It covers who may see, change, run or administer what, and how to tell why someone can or can't.
- **Starts with:** the owner's list of what is wrong with the RunMyJobs model.
- **Builds on:** user accounts ([HOSTING.md](HOSTING.md), item 1), which arrive with every account allowed everything.

### Credentials

- **In RunMyJobs:** credentials are kept centrally, which is good. But a job never names its credential: the credential is found at run time by matching the job's Run As User against the stored credentials. Which job uses which credential can't be seen, only worked out.
- **Direction:** the ActiveBatch way.
  - A credential is an object, and whatever uses it names it explicitly: a job, a step or a connection.
  - Each credential's "used by" list shows everything that would be affected by changing or removing it.
  - AutoApp already has a `Credentials` table, but nothing refers to it yet. Run SQL takes its database as a URL in a secret variable.
- **What matching does better than explicit links** (discussed 2026-10-18). Little, for credentials:
  - *Keeping job authors away from secrets:* no advantage. A credential object has its own security, so an author can be allowed to use it without seeing it (a "use but not read" right, for the permissions design).
  - *Moving jobs between environments:* a tie, provided links name the credential rather than an internal id. Then PROD needs a credential of the same name, as RunMyJobs needs one for the same user.
  - *Fixing a job without editing it:* narrow. A password change touches no job in either model. Only when a needed credential doesn't exist yet does matching let you fix the job without touching it.
  - *The right password on each host:* the one real advantage. One job that runs on several servers gets each server's credential automatically.
- **Keeping that advantage, and environment differences:**
  - A credential linked at the site or endpoint level, or holding a value per site, covers one job on many hosts.
  - A variable can pick the credential, for example `${DB_CREDENTIAL}` from the `Environment / TEST` tag, so one job definition runs as different users in different environments with no copy of the job.
  - The link stays explicit either way, and the job resolves its credential once at the start of each run, not through a search.
- **Goes with:**
  - the Connections item in TO-DO.md (a registered database or server names its credential);
  - encrypting the stored secrets (TO-DO item 6, Security);
  - vault connectors, later (TO-DO item 6).

### Alerting

- **In RunMyJobs:** alerts are kept centrally, which is good. But they are matched by pattern, not linked. Every time any job changes state, the whole alerts table is searched for alerts that match. With finely customised alerting in a busy system, those searches slow everything down and delay runs.
- **Direction:** the ActiveBatch way.
  - An alert is an object: who is told, by what channel (email first; Teams or a webhook later), and what the message says.
  - A job or workflow names the alerts it uses and for which outcomes. When a run changes state, AutoApp looks only at that run's own links. No search across all alerts.
  - Each alert's "used by" list shows who would hear about what.
- **What matching does better than per-job links** (discussed 2026-10-18). Here the advantages are real:
  - *Coverage by default:* a rule covers jobs that don't exist yet. With per-job links, a new job nobody linked fails without telling anyone, the worst way for alerting to fail.
  - *Rules across many jobs:* "every PROD failure outside business hours" is one rule, not thousands of links.
  - *Alerting changes without job changes:* when the link lives on the job, adding or retiring alerting means editing jobs, each under change control. A matching rule sits outside them.
  - Matching's costs are the search on every state change and not being able to see why an alert did or didn't fire. The search is how RunMyJobs implements matching, not a necessity: which rules apply changes only when a job or rule changes.
- **Keeping those advantages without matching:**
  - Link alerts to groups as well as to single jobs: a tag, an application, a workflow. The link is explicit and visible, and a new job carrying the tag is covered from the start. Tags already give inheritance.
  - Work out what applies when a job, tag or alert is saved and store it, so a state change only looks up what's stored.
  - A job's page lists the alerts that apply and the path each came through ("from tag Environment / PROD"), like the "Which variables a job can see" item in TO-DO.md.
  - Warn about jobs with no alerting path, such as a PROD job nothing covers. Explicit links can show what isn't covered; matching can't.
  - Whether a group's alert list belongs to the jobs' owners or to operations decides whether alerting changes need job edits. A question for the permissions design.
- **Fits with workflows:** alerting goes through **Reactions**, built in Workflows Phase 3 ([WORKFLOWS.md](WORKFLOWS.md), "Reactions to outcomes").
  - A Reaction has two sections: **What happens next** (the first that holds wins) and **Also** (every one that holds fires). **Notify** is a side effect, so it goes under Also, and it names an alert object.
  - Notify itself is planned for Workflows Phase 8, with the time-based Reactions such as "not started by 03:00".
  - Reactions are stored on the job definition, and a workflow can override them for its use of the job. That is per-job linking, with the coverage gap above. **Reactions inherited from a tag** (or an application) would close the gap. That belongs to the alerting design, not to a workflow phase.
  - This page and the Workflows work should agree on Notify before it is built.
- **To decide:**
  - which groups can carry alerts or Reactions: a workflow, a tag, an application; and how they combine with a job's own;
  - acknowledging an alert, escalating it, and holding repeats back;
  - what the alert shows: the job, the outcome, a link to the run and its Operations Log.
- **Builds on:** a way to send messages (the Send email step planned in TO-DO.md).

### Hosting in the cloud

- **Why:** a demo the owner can open from anywhere and show colleagues, and the way to a RunMyJobs integration later.
- **Plan:** [HOSTING.md](HOSTING.md).
