# Decisions

Non-obvious choices, newest last. Each entry states the situation, the call,
the reason, and the condition that should make us reopen it.

Obvious choices are not recorded here. If a reasonable person would have made
the same call without thinking, it does not need an entry.

When an entry reverses an earlier one, add a line to the old entry pointing at
the new one. Nothing else marks a decision as no longer current.

Choices made before 2026-08-13 were not backfilled. The reasoning behind the
scheduler, model, delivery, and storage choices is in the README's Tech
Decisions table, written at the time rather than reconstructed afterward.

## 2026-08-13 Failure alerts go to the sending account, not the recipients

**Context.** A failed run had no signal outside the Actions tab, which is what
let the outage that began on 2026-06-04 pass unnoticed for ten weeks. The
pipeline already holds Gmail credentials and a recipient list, so an alert
could reuse either, and a hosted monitor was the third option.

**Decision.** The failure step mails `GMAIL_ADDRESS`. `RECIPIENTS` is not used
and no external monitor was added.

**Why.** Readers subscribed to a morning digest, not to an operations feed.
Reusing the sending account needs no new secret and no new service. An external
monitor would be one more unattended account that can go quiet, which is the
exact failure being guarded against, and the person who can act on the alert is
the one who receives it either way.

**Revisit if.** The recipient list ever holds someone who needs to be told the
mail is not coming, rather than someone who would simply notice it did not
arrive.

## 2026-08-13 The keepalive commits only after fifty quiet days

**Context.** GitHub disables a scheduled workflow after 60 days without
repository activity. That is what actually stopped this pipeline, and failure
alerting cannot catch it: a run that never starts has no job to send an alert
from. Resetting the timer requires a push.

**Decision.** A monthly job pushes an empty commit, but only when the last
commit is more than 50 days old.

**Why.** An unconditional monthly commit would put a no-op in the history
twelve times a year, and the history is part of what a reader looks at. The
threshold means ordinary development leaves no trace at all, while the monthly
cadence puts at most 31 days between checks, so 50 days is always reached
before 60.

**Revisit if.** GitHub changes the 60-day rule or what counts as repository
activity, since both the threshold and the cadence are derived from that
number. Note also that this has never fired: that a `GITHUB_TOKEN` push resets
the timer is taken from common practice, not from anything observed here.

## 2026-08-13 Model calls are retried even though POST is not idempotent

**Context.** A retry-mounted session existed but covered news fetching only, so
`call_gemini` posted directly and one transient 5xx ended the run. This stopped
being hypothetical on 2026-08-13, when Gemini returned 503 on the first
interpretation and two of three articles were never written.

**Decision.** `call_gemini` goes through the retry session, with POST added to
the retried methods.

**Why.** Mounting the existing session alone would have changed nothing,
because urllib3 leaves non-idempotent methods out of `allowed_methods` by
default and would have retried none of these calls. Retrying a POST is safe
here specifically: `generateContent` creates no resource and has no side
effect, so a duplicated request costs one call against a free-tier allowance
and nothing else.

**Revisit if.** A Gemini endpoint that does have side effects is called through
the same session. `retry_post` is a per-session flag defaulting to off for that
reason. Quota errors are deliberately outside `status_forcelist`, because
retrying an exhausted quota only delays the same failure.

## 2026-08-13 Constraint checks are rules, not a model judgment

**Context.** The prompt's constraint block was enforced by the prompt alone, so
a violation shipped unseen. Checking it before dispatch could be done by rule
or by a second model call acting as a judge.

**Decision.** Deterministic rule checks in `scripts/evaluate.py`. No judge
model.

**Why.** The block states its constraints literally enough to test
mechanically: no preamble, three lenses present and in order, two sentences
each, no markdown. A judge would add a call, a cost, and a second thing that
can be wrong, in exchange for a less reliable version of an answer the rules
already give exactly. One constraint, that the three lenses differ in sentence
structure, has no mechanical test and is left unchecked rather than
approximated by something that only resembles it.

**Revisit if.** The article body reaches the prompt. Faithfulness cannot be
tested by rule and is the case where a judge earns its cost, and it is blocked
today because the model only ever sees a headline.

## 2026-08-13 A constraint violation does not block the mail

**Context.** Once violations are detected, a failing interpretation can be
regenerated, dropped, or sent as it is. Dispatch happens once a day, so there
is no second chance that morning.

**Decision.** Regenerate once with the violations fed back into the prompt,
then send whatever the second attempt produced. Violations are recorded either
way.

**Why.** A malformed lens is a smaller loss to a reader than a missing morning,
and a hard gate would turn a formatting slip into an outage of exactly the kind
this pipeline just spent ten weeks in. One retry is bounded at three extra
calls on the worst day, still far inside the free tier. Recording the outcome
regardless is what would make a rising violation rate visible instead of
silently absorbed.

**Revisit if.** A violation degrades a mail badly enough that a reader notices,
or regeneration succeeds so rarely that the extra call buys nothing. The
per-run counts written to the job summary are what would show either.
