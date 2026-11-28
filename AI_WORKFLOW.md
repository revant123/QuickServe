# How I built QuickServe with Claude Code

**Short version:** most of the code in this repository was written by **Claude Code**, Anthropic's coding agent. The commits authored by `Claude <noreply@anthropic.com>` are its work. I decided what to build, set the constraints, reviewed every change and merged it. All **24 pull requests** were opened from feature branches and merged by me, after CI passed.

I'm stating this up front because the git history shows it, and because I think how a developer works with an AI agent now matters as much as what they build.

---

## Who did what

| | Me | Claude Code |
|---|---|---|
| **What to build** | Chose the project, the learning goals (ORM, DevOps, FinOps) and the order of the 16 phases | Suggested how to break each phase into steps |
| **Constraints** | Hardware, ports, cost limits, what may go to AWS and when | Worked within them |
| **Code** | Read the diffs, ran the app, asked for changes | Wrote the code, tests and docs on a feature branch |
| **Correctness** | Required tests for every behaviour, against a real PostgreSQL and Redis | Wrote the tests and fixed what they caught |
| **Merging** | Merged each PR myself, only with green CI | Never merged anything |
| **Spending money** | Decides whether the AWS stack is applied (Phase 16: "applying it is your call") | Wrote the Terraform, tested with mocks in CI |

## The loop for every phase

```
 plan the phase  →  feature branch  →  code + tests  →  CI (7 jobs)  →  my review  →  merge
      (me)            (Claude)          (Claude)         (automatic)      (me)        (me)
                                            ↑                                  │
                                            └────── changes I asked for ───────┘
```

1. **Plan first.** Each phase starts with a goal and a definition of done: what can be shown at the end (a passing CI run, a dashboard, a URL). The roadmap is in the README (section 13).
2. **One phase, one branch, one PR.** For example `feature/phase8-notifications-outbox`, `feature/phase10-netpol`, `fix/desktop-layout`. Fixes got their own small PRs (`fix/quickserve-port-5433`, `fix/deploy-exact-commit`), not edits slipped into a feature.
3. **Tests come with the code.** A change without a test for its behaviour wasn't finished.
4. **CI is the gate.** Seven jobs: backend tests, frontend, Docker, image publish, Terraform tests, a Kubernetes cluster run (kind) and deploy. A red pipeline means no merge.
5. **Review, then merge.** I read the diff and ran it locally. Each phase also adds an interview-style Q&A section to the README, which I used to check that I could explain the change myself.

## Guardrails, because AI-written code has to earn trust

An agent writes code fast and sounds sure of itself even when it's wrong. These are what made its output safe to merge:

- **290 backend tests against real PostgreSQL and Redis**, not mocks. They include concurrency tests with real threads, attacks on login, and Redis outages. There are also **52 frontend tests** and Playwright browser journeys.
- **Lock files** (`requirements.lock`, `requirements-dev.lock`), so CI installs exactly what was tested.
- **Migration round-trips:** every test run downgrades and re-upgrades the schema.
- **Infrastructure tests:** Terraform modules have their own tests, and the Kubernetes manifests are deployed to a real kind cluster in CI.
- **Budgets enforced in CI:** a 150 KB JavaScript limit for the frontend and a size check on the EC2 boot script.
- **No secrets in the repo:** `.env.example` only. On AWS, GitHub deploys through OIDC (no stored access keys), and the demo passwords come from Parameter Store.

## What the process caught

The README's **"Bugs the tests caught while building this"** section records 13 real bugs. A few show why the guardrails mattered more than the speed of generation:

- **Code that only existed on my machine (bug 9).** Everything passed locally, but CI failed. A Python `.gitignore` rule (`lib/`) was silently ignoring `frontend/src/lib/`. A clean clone in CI caught what my laptop couldn't.
- **A button nobody could see (bug 10).** All 48 frontend tests passed, but a screenshot showed the Reject button had red text on a red background. Tests check behaviour, so someone still has to look at the screen.
- **Tracing that traced nothing (bug 11).** The OpenTelemetry instrumentation silently did nothing on SQLAlchemy 2.1. A test asserting that SQL spans *exist* found it.
- **A deploy bug no unit test could find (bug 12).** A dry run of the deploy script in a sandbox found an IP address clash that would have stopped HTTPS from coming up on the real server.

The lesson I took from these: **a green test from an AI-written suite is a claim, not proof.** You check that it fails when it should, and you look at the real output.

## Decisions that came from my constraints

These are choices the agent wouldn't have made without me telling it about my situation:

- **Ports 5433, then 5434** (PRs #2, #3), so QuickServe's database runs next to my other project, QuickKart.
- **A "lite" Kubernetes overlay** (PR #17). The full stack didn't fit next to QuickKart on my 8 GB Mac, so we measured it: 1.90 GiB for the full stack, 1.44 GiB for lite.
- **One EC2 server with blue/green containers instead of EKS**, to keep a student budget, with a budget alert set up first (`infra/bootstrap/`).

## What I can explain without the AI

If you ask me about any of these, I'll walk you through the code:

- the **stock / consumed / cycle** inventory design, and why it makes sell-through and waste tracking possible
- the **order state machine** and the restaurant's accept-within-a-time-limit rule
- **idempotent payments**, and why the key is checked again after taking the lock (bug 1)
- the **transactional outbox** for notifications, and what it guarantees that "send after commit" doesn't
- **race-safe coupon redemption** and atomic rating totals
- **blue/green deploys** with a smoke test and automatic rollback

The README's **Interview cheat sheet** (section 14) is what I revise from.

## What I'd do differently

- **Commit under my own name with a `Co-authored-by` trailer**, instead of the agent being the commit author. The history would show the collaboration more accurately.
- **Spread the work over more time.** The 71 commits span about six days. Building it more slowly would have left more room to write some modules myself first and then compare them with the agent's version.
- **Write a few core pieces by hand**, such as the inventory cycle and the payment lock, before asking for them. That's the fastest way to know an agent's code is right.

---

*Back to the [README](README.md).*
