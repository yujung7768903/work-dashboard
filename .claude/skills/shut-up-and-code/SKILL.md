---
name: shut-up-and-code
description: Load-bearing comments only. Use when writing or editing code in any language, or when the user asks about comment standards.
---

# shut-up-and-code

A comment earns its place by being **load-bearing**: delete it and a competent reader loses something the code cannot tell them. Write those. Let the code speak for everything else.

This holds for every file you write or edit for the rest of the session, and does not lapse when the topic changes. If you are unsure whether it still applies, it does. The user turns it off by saying "normal comments" — confirm in one line, then return to your default style.

## The test

Before writing a comment, name what the reader loses without it. A concrete answer means it is load-bearing, so write it. Silence — or an answer that restates the line below — means the code already carries it, so let the code carry it.

Say it in different words than the code. A comment assembled from the identifiers beneath it is that line spelled twice. If the only phrasing you have reuses the names already on screen, there was nothing to add.

The test runs per sentence, not per comment. Keep the sentence that carries the answer; every further sentence needs its own. A four-line comment with one load-bearing line is one line long.

Comments describe the code as it stands, in the voice of the file. The edit that produced them belongs in the commit message.

Apply the same test to comments already in code you touch: load-bearing ones stay as they are, and one your own edit made false gets corrected or removed in that same edit. An edit can falsify a comment it never touched — reread the comments around the edit site, not only the ones you rewrote.

## What is load-bearing

Five kinds, in practice:

1. **Why, not what** — a decision, tradeoff, or constraint the code cannot express. `// Retry 3x — the upstream 502s on cold start.`
2. **A landmine** — something that looks safe to change and is not. `// Set the auth header before reading the body.`
3. **A deliberate omission** — something absent on purpose that a reader would otherwise take for a bug. `// Unsorted; the caller re-sorts by locale.`
4. **A pointer out of the file** — a ticket, RFC, spec section, or upstream bug that explains the code's shape.
5. **A toolchain annotation** — `// eslint-disable-next-line`, `# type: ignore`, pragmas, codegen markers.

Density follows the file. An uncommented neighbourhood stays uncommented. A heavily commented one sets its ceiling by its load-bearing comments, not by its total.

## Contracts

Everything above governs comments *inside* a function. The comment *on* it is a different instrument.

A doc comment on public surface — an exported function, a public method, a module, a published type — is a **contract**. It exists so callers never read the body, and it does that job even when it restates the signature in prose. Delete it and the abstraction goes with it: callers read your implementation to learn what you promise, and you lose the freedom to change it.

Write the contract in the form the language expects, and put in it what a signature cannot hold:

- **Units and bounds** — `timeout` in what? Is `end` inclusive?
- **Failure** — what it returns, raises, or panics on, and when.
- **Caller obligations** — preconditions, call ordering, ownership, whatever an `unsafe` block trusts.
- **Concurrency** — safe to call from more than one thread, or not.
- **The edges** — empty, zero, negative, overflow: the cases you had to decide.

Where a project's own standard overrides this skill, the project wins. Internal helpers carry no contract; they get the ordinary test.

## Reach for the alternative first

Most explanations land better somewhere other than a comment:

- Rename the variable or function until it says what the comment would have said.
- Extract the confusing block into a named function.
- Write a test that demonstrates the behaviour.
- Put the reasoning in the commit message or PR description.
- Put it in your response to the user. Chat prose is free, and this ruleset governs files, not replies.

## When the comment is hard to write

Difficulty explaining a block is a fact about the code, not about your prose. Split the function, name the intermediate value, or fix the abstraction — then the comment either writes itself or turns out to be unnecessary. A block that needs a paragraph was asking to be two functions.

## The audit point

A commit — or the end of any turn that edited files — is where the audit runs, unprompted. Account for **every comment in the diff**: for each one, state what the reader loses without it, sentence by sentence. Keep the ones with a concrete answer, drop the rest. Contracts answer by default.

Test names are comments the runner prints: a `describe` or `it` string claims only what its body exercises.

The diff is ready when every surviving sentence has an answer.
