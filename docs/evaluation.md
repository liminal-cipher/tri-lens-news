# Evaluation Plan

Faithfulness and ladder coherence have not been quantitatively measured.
This plan began on 2026-08-13 and was clarified on 2026-10-28 before those
measurements. The separate bake-off records format checks, not these metrics.

Two changes made on 2026-08-13 are claims about quality, and neither was
checked: the pipeline now reads the article instead of the headline, and the
three lenses are written to carry forward rather than stand apart. Both were
judged by reading one day's output. That is an observation. This document is
how it becomes a measurement.

## What Is Being Measured

Two things, one for each claim. Adding a third would mean inventing a metric
before the first two have any data behind them.

### 1. Faithfulness

**Question.** Does the interpretation assert only what the source supports?

**Why this one.** The article body was added so that interpretations would stop
being guesses. On 2026-08-13 an interpretation named a GitHub repository for a
paper; checking the abstract by hand showed the claim was correct, but before
the body was in context there would have been no way to tell. Faithfulness is
a measure of source support, including fluent claims that the inspected source
does not substantiate. Establishing whether the input change caused an improvement
requires the controlled comparison described below.

**Unit.** A claim, not a sentence. Each lens is two sentences and usually
carries two to four separable assertions, and a sentence that is half supported
scores nothing useful as a whole.

**Labels.**

| Label | Meaning |
| --- | --- |
| Supported | The claim is traceable to a span of the source text |
| Unsupported | Plausible, possibly true, but not in the source |
| Contradicted | The source says otherwise |

**Score.** Share of claims labelled Supported, reported per lens and per item.
Unsupported and Contradicted are counted separately and never summed, because a
lens that invents a harmless detail and one that gets the result backwards are
not the same failure.

**Scope.** Score source-grounded items against the exact text supplied to the
model: a fetched article excerpt or paper abstract, not an assumed full paper.
Report headline-only and unknown-grounding items separately, outside this
denominator. The archive footer records a daily body count, not which items had
text or what that text was; it cannot establish item-level eligibility alone.

### 2. Ladder Coherence

**Question.** Does each lens build on the one above it?

**Why this one.** It is the specific design claim of the project. If the three
lenses do not connect, they are three summaries of the same thing at three
lengths, and the structure is decoration. Nothing about this is checkable by
the current rule checker, so it is requested by the prompt but not enforced.

**Unit.** The pair. Everyone to Developers, and Developers to Researchers.

**Labels.**

| Label | Meaning |
| --- | --- |
| Builds | The later lens names, extends, or depends on something the earlier lens established |
| Restates | Same ground, different words. Not wrong, but no step gained |
| Disconnected | The later lens introduces its subject as if the earlier one had not been read |

**Score.** Share of pairs labelled Builds.

## How It Gets Labelled

**Human labels are the reference.** The intended reader can assess whether
the ladder helps them, but faithfulness labels must cite source spans rather
than personal preference. Mark ambiguous claims for adjudication instead of
forcing a confident label. One annotator's labels are not independent truth.

The target is 30 eligible items, with dates, news/paper composition and selection
criteria fixed before labelling. Existing archives provide interpretations but
not the original model inputs. Collect a separate local evaluation record for
each item: source URL and retrieval time, exact supplied text and its hash,
grounding status, prompt/version, provider/model and generated output. Keep
restricted source snapshots outside the public repository. Refetching an old
URL does not recover the original input; label such evidence as retrospective.
This collection workflow has not been implemented.

**Labelling procedure.**

1. Read the source text first, then the interpretation. Not the reverse: reading
   the interpretation first makes its claims feel familiar in the source.
2. Hide model identity and experimental condition where feasible. Record source
   availability before scoring; do not claim blinding when the materials reveal
   it. Unsupported claims need an inspected source, not a missing snapshot.
3. Record a second pass on 10 of the 30 items, at least a day later, and report
   self-agreement. A rubric one person cannot apply consistently to themselves
   cannot be applied by anyone.

For a causal claim that supplying article text improves faithfulness, compare
headline-only and source-grounded generations on the same held-out articles,
with model/settings fixed and both scored against the same source snapshot.
For a ladder-prompt comparison, vary that prompt while holding source and model
fixed. An archive-only score describes observed output; it cannot isolate the
effect of either change. Report dates, sample counts, model/settings, runs and
uncertainty with any result, and keep prompt tuning separate from held-out scoring.

## The Judge, and Why It Is Not Trusted Yet

Labelling 30 items by hand is the initial target. An LLM judge is one option
for scaling beyond that set; periodic human sampling remains an alternative.

**It does not get used until it agrees with the human labels.** The threshold is
set here, before any judge output has been seen: Cohen's kappa of 0.6 or above
for each label task on a held-out set of 30 items. Treat this as a project
acceptance threshold, not proof of general validity. Use fixed claim units
for faithfulness and fixed lens pairs for coherence; report their counts,
label distributions, confusion matrices and agreement uncertainty separately.
If kappa is undefined or the threshold is missed, report that validation
failure and do not use the judge to publish automated quality scores.

**Potential bias.** A judge may share the generator's blind spots, especially
when it is the same model. Record both identities and evaluate agreement rather
than assuming that choosing a different model removes bias. Do not tune the
judge on the same labels used to report its held-out agreement.

## What Is Deliberately Not Measured

- **Readability scores.** No Korean readability formula has been selected or
  validated for these outputs. The prompt requests limited glosses but the
  rule checker does not measure accessibility or enforce the gloss limit.
- **Whether the digest is useful.** One reader, no counterfactual, and the
  honest answer is that they kept reading it or they did not.
- **Anything about items with no body text.** They cannot be scored for
  faithfulness, and pretending otherwise by scoring them against the headline
  would measure fluency and call it accuracy.

## Observed Errors

### Price Units

The [2026-10-27 delivered archive](https://github.com/liminal-cipher/tri-lens-news/blob/d9c63ec7a3b1c15053eb07751aa9b1caf8c2890d/archive/2026-10-27.md)
describes GPT-6.1 Terra prices as dollars per token, omitting the million-token
unit. The [original announcement](https://openai.com/index/introducing-gpt-6-1-terra/)
states $1 for input, $0.05 for cached input and $5 for output **per million
tokens**. This correction refers to that announcement, not a promise about
future pricing. The sent archive is retained as evidence of the error.

This single source-checked error is not a measured error rate. It demonstrates
why format checks alone do not establish faithfulness, and why a numeric claim
must retain its unit during labelling.

### Encoding Is Not Encryption

The [2026-09-26 archive](../archive/2026-09-26.md) calls layered Base64
transformation encryption. Base64 is an encoding, as described in the
[Python standard-library documentation](https://docs.python.org/3/library/base64.html);
it does not provide encryption or confidentiality. The historical sent text
is retained, with this correction recorded separately.

### Claims Requiring Further Checks

Several archived Researchers lenses assert that causes have not been separated
or that an ablation is missing. Those are checkable claims about the original
work, not automatically justified research questions. Likewise, statements
such as no risk of data leakage need evidence beyond a local-processing label.
Prioritise these claims during source comparison; their truth has not been
established by reading the generated archive alone.

## Status

Design only, updated 2026-10-28. No completed 30-item labelled set or validated
judge is recorded here. Archived output and the observed correction above do
not replace the missing input snapshots, labels or controlled comparisons.
