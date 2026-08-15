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

**Boundary.** This covers a malformed interpretation, not a missing one. If
selection yields fewer than three articles the run exits non-zero instead,
because the alternative is a mail carrying a header, a footer, and nothing
between them, which is worse for a reader than no mail at all.

## 2026-08-13 Delivered digests are committed to the repo as markdown

**Context.** The interpretations went out by mail and were kept nowhere. There
was no way to answer what was sent last week, and no corpus for the faithfulness
scoring the roadmap calls for. The options were a database, an external store,
or files in the repo, against a stated design of holding no state at all.

**Decision.** After a successful send, write `archive/YYYY-MM-DD.md` and commit
it from the workflow. Only delivered digests are written.

**Why.** What needs to persist is text, written once a day, read rarely, and
never queried, so a database would buy nothing that a file does not. It would
also add a service to keep alive in a project whose defining failure was an
unattended thing going quiet. Committing only what was delivered keeps the
archive a record of what readers actually received rather than of what the
model happened to produce.

**Consequence worth naming.** A daily commit resets the 60-day inactivity timer
on its own, so the keepalive job now sleeps through ordinary operation. It is
kept rather than removed, because the case it guards is a pipeline broken for
weeks, which is exactly when the archive commits stop too.

**Revisit if.** The repository grows large enough that cloning it is a chore, or
a question arrives that needs querying across days rather than reading one. A
few kilobytes a day takes years to reach either, so this is a note for a future
reader rather than an expected event.

## 2026-08-13 Retry counts are recorded, not just retry failures

**Context.** urllib3 handles retries below the application and hands back only
the final outcome. A call that succeeded on its third attempt produced the same
return value and the same log lines as one that succeeded on its first, so the
only trace was an unexplained jump in run time. Alerting covers a call that
exhausts its retries, which is the end state, not the approach to it.

**Decision.** Read the retry history urllib3 attaches to each response, print
the count when it is non-zero, and write the daily total into the archive file
alongside the validation counts.

**Why.** The budget is three attempts per call. Spending two of them every
morning is the difference between a pipeline that is fine and one that fails on
the first slightly worse day, and nothing distinguished those two states. The
count goes into the archive as well as the log because Actions drops logs after
90 days, so the log alone answers what happened yesterday but not whether this
month is worse than last.

**Revisit if.** The daily line stops being read, or a trend needs to be seen
across months rather than reconstructed by opening files. Counting is the cheap
half; nothing yet aggregates these lines or alerts on a rising number.

## 2026-08-13 A paper joins the digest, from a curated list rather than arXiv

**Context.** The two sources were never chosen. They were whatever came out of
an early session, and neither carries research, so the Researchers lens had
nothing real to work with and produced sentences that sounded like research
about product launches. Measuring the sources for the first time also showed
they are not independent: 4 of 15 Hacker News stories appeared in GeekNews the
same day, one of them under an identical title.

**Decision.** Add Hugging Face Daily Papers. The digest becomes two news items
plus one paper, with the paper slot fixed. The paper is chosen by upvote rather
than by a model call.

**Why.** Five things were compared: what a source contributes, whether it
overlaps the others, whether the article text comes with it, whether the daily
volume is rankable, and how stable the interface is. Raw arXiv failed the fourth
outright, returning 261 papers in one category in one day with no signal to
order them. Hugging Face Daily Papers is human-curated, carries upvotes, and
ships the abstract, which makes it the only candidate that also solves the
article-text problem for its own slot. The slot is fixed because a paper title
loses a relevance contest to a product headline every time, so leaving it to
compete means never getting a paper. Upvotes replace a model call because the
candidates are already ranked by people.

**Revisit if.** `huggingface.co/api/daily_papers` changes shape or goes away. It
is not a documented public contract, unlike the Hacker News Firebase API, and
this is the least stable dependency in the pipeline. Also revisit if upvotes
turn out to select for what is popular rather than what is worth reading, which
the archive will eventually show.

## 2026-08-13 A digest that fails its own check still renders readably

**Context.** The mail template now draws each lens as its own labelled block,
which requires the output to parse into three lenses. A violating interpretation
is sent anyway, by an earlier decision, so the template has to handle output it
cannot parse.

**Decision.** Fall back to the previous plain rendering when the three lenses
are not all present.

**Why.** The alternative is a template that drops text it cannot categorise,
which turns a formatting violation into missing content and quietly undoes the
reason for sending a flawed digest in the first place. A reader seeing an
unstyled paragraph knows something is off; a reader seeing nothing does not.

**Revisit if.** The fallback starts appearing often enough to notice, which
would mean the constraint check and the regeneration are not doing their job and
the problem is upstream of the template.

## 2026-08-13 The three lenses carry forward instead of standing apart

**Context.** The constraint block required the lenses to differ in sentence
structure, which follows from treating them as three audiences who each read
only their own. There is one reader who reads all three in order. The first
paper in the digest showed what that costs: the plain lens explained sampling an
answer several times and taking the majority, and the next lens reintroduced the
same idea as an untranslated term, so the reader met what they had just
understood as something unfamiliar.

**Decision.** A lens is written on top of the one above it and names in its own
vocabulary what the previous lens described in plain words. Terms are written in
English rather than transliterated, glossed once on first use, at most twice per
lens, and only when the term cannot be guessed from outside the field.

**Why.** A transliterated term cannot be looked up, which is the whole point
when the reader is trying to learn the field. English first also keeps one term
from appearing two ways in one message, which was happening. The gloss cap
exists because the first version of the rule had none and produced two sentences
carrying four parentheticals, including explanations of `weight` and `VRAM`.
The worked example was rewritten alongside the rules, since it anchors the
output more strongly than the rules do on their own.

**Revisit if.** Papers stop being the item that needs the ramp, or the
carry-forward starts reading as repetition rather than as a step up. Neither has
a mechanical test: this was judged by reading one day's output before and after,
on three items, which is an observation and not a measurement.

## 2026-08-14 The carry-forward happens without announcing itself

**Context.** The previous entry said to revisit if the carry-forward started
reading as repetition rather than as a step up. It did. Across the two archived
days, all twelve Developers and Researchers lenses opened by pointing at the
lens above: `앞서 언급한`, `앞의 두 관점에서 다룬`, `방금 다룬`, `이러한`. The
opening had become a fixed slot rather than a sentence. The worked example was
the cause, not the rules: its Developers lens began `앞에서 말한 ... 방식이`,
and the model copies the example more faithfully than it follows the constraints.

**Decision.** Keep the ladder, drop the narration. A later lens still names what
an earlier one described in plain words, but it does so by using the term rather
than by referring back to where the term came from. Pointing phrases are banned
from the start of a lens, the worked example was rewritten to demonstrate the
silent version, and `evaluate.check` now rejects a lens that opens with one.

**Why.** Two things were bundled together and only one of them was working. The
structure is what makes three lenses a ramp instead of three summaries, and it
is worth keeping. The announcement adds nothing, because the text being pointed
at sits three lines above and the reader has just read it. Removing it also
makes each lens readable on its own, which the ladder framing had been quietly
trading away. Unlike the rule it replaces, this one has a mechanical test: the
check is a literal string match on the first characters of a lens, so it costs
no call and cannot drift. Run against both archived days it flagged 12 of 12
lenses, and the rewritten example passes clean.

**Revisit if.** Regeneration starts firing on most items, which would mean the
prompt is not carrying the rule and the ban is being enforced after the fact
rather than before it. The cost is one extra call per violating item.

## 2026-08-15 One table holds everything a provider does differently

**Context.** Choosing a model for the daily job means comparing candidates, and
comparing them means running the same prompt through two of them. That was not
possible. `GEMINI_URL` was an f-string evaluated at import, so the model was
fixed for the life of the process and a comparison meant a separate run per
model, by which time the day's candidate stories had changed. Vendor knowledge
sat in four places inside one function: the address, the auth, the request
shape, and the path into the response.

**Decision.** A `PROVIDERS` table maps a name to the three things that vary:
a function building the request, a function pulling text out of the response,
and a default model. `call_model(prompt, provider=None, model=None)` reads the
table; the two call sites pass a prompt and nothing else. `LLM_PROVIDER` and
`LLM_MODEL` repository variables pick the default pair without a commit.
`GEMINI_MODEL` is still read when `LLM_MODEL` is empty, so the variable already
set in the repository keeps working. Provider keys are checked when a provider
is actually called rather than at import, and Gemini's key moved from the URL
query to the `x-goog-api-key` header.

**Why.** The bake-off needs two models answering the same prompt in one process,
and no arrangement of environment variables gets there while the URL is built
once at import. Naming the varying parts also shows how small they are: adding
an OpenAI-compatible provider is one line in the table, because Groq and
OpenRouter share a shape that a single builder covers. Checking keys lazily
keeps a provider nobody uses from ending the run, which an eager
`os.environ["GROQ_API_KEY"]` would have done every morning. Moving the key to a
header takes it out of the URL, which is the part of a failed request that ends
up in exception messages and retry logs.

**Revisit if.** A provider needs something the three-value shape cannot express,
such as streaming, a different retry policy, or system messages as a separate
field. The table is deliberately thin, and the first provider that does not fit
is the signal to widen it rather than to bend the caller around it.

## 2026-08-15 The bake-off compares models on a frozen input, read blind

**Context.** The provider table made it possible to call two models in one
process, which leaves the question of which model should write the digest. A
comparison needs the models to differ and everything else to hold still, but the
pipeline picks fresh stories on every run, so two runs an hour apart are already
interpreting different articles. Selection is itself a model call. The pipeline
also regenerates once when an output breaks a constraint.

**Decision.** `scripts/bakeoff.py` has two commands. `freeze` collects, selects,
and fetches article bodies once, then writes them to a file. `run` reads that
file and asks every named model for a reading of the same articles, without
regeneration, and writes two files: a JSON holding the label-to-model map, and a
markdown report in which each model appears only as a letter. Letters are
assigned by hashing the model name rather than by the order the models were
named on the command line, and the order they are printed in rotates by one
position per article.

**Why.** Fixing the selection to one model's picks means the comparison is of
the writing rather than of story-picking taste. Regeneration is left out because
obeying the constraints is part of what is being compared, and feeding the
violations back hides that difference behind a second call. The reader is the
only judge of whether the sentences are good, which `docs/evaluation.md` already
argues, and a reader who knows which model wrote a paragraph is not judging the
paragraph. Rotation keeps one model from always sitting in the position that
gets read first and most carefully. Hashing the letters came out of the first
run, where the letters followed the order given on the command line and the
command was still on screen, which is a blind that only holds until someone
scrolls up.

**Revisit if.** First-output pass rate stops separating candidates, either
because every candidate clears the format check or because none do. At that
point the interesting question becomes how well each recovers when told what it
broke, and the run would need the regeneration step it deliberately omits.

## 2026-08-15 The bake-off runs locally and commits only its results

**Context.** The daily pipeline runs only in Actions, where the keys are. The
bake-off needs the same keys, but it is started by hand and its output is read by
a person rather than mailed. Its frozen input holds the full text of other
people's articles, and this repository is public.

**Decision.** No workflow. The bake-off runs locally and reads keys from a
gitignored `.env` that `bakeoff.py` loads itself when the file exists. Frozen
inputs are gitignored. Results are committed, and a result file carries the
title, URL, and body length of each article rather than the body.

**Why.** An experiment that iterates through push, dispatch, and log-reading
iterates slowly, and nothing here needs a runner. Reading `.env` by hand is ten
lines and keeps a dependency out of the workflow, which installs only what the
daily run needs. Body length is the one thing later scoring needs from the body,
since faithfulness is only scored on items that arrived with one, and keeping the
length rather than the text records that without republishing the source.
Results are committed because a comparison whose output cannot be reread later
is an opinion.

**Revisit if.** The comparison ever needs to run unattended, such as re-scoring
the archive whenever a new model appears. That turns it back into a workflow and
moves key handling back to repository secrets.

## 2026-08-15 The digest does not repeat what it sent in the last seven days

**Context.** Hacker News keeps a story on its front page for days and Hugging
Face's daily papers linger longer, while the pipeline chose each morning with no
memory of the one before. The archive shows the result plainly: `z.ai/blog/glm-5.3`
went out on both 08-14 and 08-15. The selection prompt already forbade picking
two items about one event, but only within a single day's candidate list.

**Decision.** Candidates whose URL appears in the last seven days of archive are
dropped before selection, and the titles from that same window go into the
selection prompt so the model can also drop a different link to the same event.
Both steps give way rather than fail: if filtering would leave too few
candidates the filter is skipped, and if the model returns fewer items than
asked, the remainder is filled from what is left. Every relaxation is logged,
and the number dropped is written into the archive footer.

**Why.** The archive already records exactly what the reader received, so the
question of whether they have seen an item needs no new store. A second store
would eventually disagree with the first. The URL filter is deterministic and
costs nothing, but it is not enough on its own: the first run with it enabled
excluded two Hacker News links and immediately picked the GeekNews articles
covering the same two events. Whether two links are one event is a reading
rather than a rule, which is why that half is asked of the model. The
relaxations exist because a repeated article is a smaller loss than a morning
with no mail at all.

**Revisit if.** The counts now written into the archive footer show that seven
days is starving the selection, or that it is short enough that repeats still
arrive. Both are visible from the footer alone, which is why the number is
recorded rather than only logged. Reopen too if the model's same-event
judgement turns out to be unreliable once there are more days to look at; the
URL half would stand on its own, but the claim that the prompt catches the rest
rests on one run.
