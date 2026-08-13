# Evaluation Plan

Nothing here has been measured. This is the design, written before the work,
so that a number produced later can be read against the method that produced
it rather than explained afterward.

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
the metric that says whether feeding the source changed anything, and it is the
only one that can catch a fluent interpretation of an article the model never
read.

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

**Scope.** Only items that arrived with body text. An item that fell back to the
headline is excluded from the denominator rather than scored zero, since there
is nothing to be faithful to. The archive footer already records how many items
had a body, which is what makes this exclusion auditable.

### 2. Ladder Coherence

**Question.** Does each lens build on the one above it?

**Why this one.** It is the specific design claim of the project. If the three
lenses do not connect, they are three summaries of the same thing at three
lengths, and the structure is decoration. Nothing about this is checkable by
rule, which is why the constraint block enforces it alone today.

**Unit.** The pair. Everyone to Developers, and Developers to Researchers.

**Labels.**

| Label | Meaning |
| --- | --- |
| Builds | The later lens names, extends, or depends on something the earlier lens established |
| Restates | Same ground, different words. Not wrong, but no step gained |
| Disconnected | The later lens introduces its subject as if the earlier one had not been read |

**Score.** Share of pairs labelled Builds.

## How It Gets Labelled

**The reader is the ground truth.** There is one subscriber and they are the
person the digest is for, so the question that matters is not one a model can
answer on their behalf.

The plan is 30 labelled items. At three items a day with the paper always
carrying an abstract and news bodies arriving most days, that is roughly two
weeks of accumulation from the archive. Items are drawn from `archive/`, which
is why the archive had to exist before this document could.

**Labelling procedure.**

1. Read the source text first, then the interpretation. Not the reverse: reading
   the interpretation first makes its claims feel familiar in the source.
2. Label without checking whether the item had a fetched body. That fact is
   recoverable afterward and knowing it in advance biases the reading.
3. Record a second pass on 10 of the 30 items, at least a day later, and report
   self-agreement. A rubric one person cannot apply consistently to themselves
   cannot be applied by anyone.

## The Judge, and Why It Is Not Trusted Yet

Labelling 30 items by hand is feasible. Labelling every item every day is not,
so an LLM judge is the only way this survives past the initial set.

**It does not get used until it agrees with the human labels.** The threshold is
set here, before any judge output has been seen: Cohen's kappa of 0.6 or above
against the 30-item set. Below that, the judge's numbers are not reported at
all, rather than reported with a caveat.

**Known bias, stated in advance.** The obvious judge is Gemini, which is also
the model that wrote the text. A model preferring its own output is a documented
effect, so if the judge is Gemini, its agreement is measured against human
labels and never assumed. Using a different model for judging is the cheaper
fix and should be tried first.

## What Is Deliberately Not Measured

- **Readability scores.** Korean readability formulas are not reliable enough to
  carry a claim, and the accessible-language requirement is already partly
  enforced by the gloss rule in the prompt.
- **Whether the digest is useful.** One reader, no counterfactual, and the
  honest answer is that they kept reading it or they did not.
- **Anything about items with no body text.** They cannot be scored for
  faithfulness, and pretending otherwise by scoring them against the headline
  would measure fluency and call it accuracy.

## Status

Design only, written 2026-08-13. No items labelled, no judge built, no numbers.
The archive began accumulating the same day, so the earliest point at which a
30-item set exists is late August 2026.
