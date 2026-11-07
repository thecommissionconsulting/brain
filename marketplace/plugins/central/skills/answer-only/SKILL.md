---
name: answer-only
description: >
  Strip a reply down to the answer and nothing else, and keep personal data out
  of the prompt. Runs from a UserPromptSubmit hook on every prompt, so it needs
  no invocation. Read it when asked how the answer-only style is enforced, why a
  prompt was blocked for PII, how to change what the gate detects or injects, or
  when tuning the per-prompt token budget. Trigger: /answer-only.
allowed-tools: Read, Bash
metadata:
  version: "1.0.0"
---

# answer-only

Two jobs, one hook. On the way in, `prompt_gate.py` blocks a prompt carrying
personal data or a credential. On the way out, it injects the reply contract
below so the answer arrives without the packaging around it.

## Why a hook and not a skill call

A skill only applies when something invokes it, and the two things this does are
both things you never remember to ask for. A reply's padding is invisible until
you count tokens, and by the time you notice a pasted address in the prompt it is
already in the context window and nothing downstream can take it back.

Hooks cannot invoke skills: they talk through stdout, stderr and exit codes only.
So `prompt_gate.py` reads the block below out of this file and emits it as
`additionalContext`. This file is the only copy. Edit it here and the next prompt
picks it up, with no reinstall.

The detectors live in plugins/central/security/patterns.py, shared with the output redaction and the vault's read gate. Change them there, not in prompt_gate.py.

## The reply contract

Everything between the two markers is injected verbatim on every prompt. It is
charged as input tokens once per turn, so a line only belongs here if it changes
what the reply looks like. Anything explanatory goes outside the markers, where
it costs nothing until someone opens this file.

<!-- INJECT:START -->
Answer only. No preamble, no restating the question, no tool-call narration,
no recap of visible work, no offer of more help, no closing line. Citations
only when asked.
Cut filler and hedging. Articles optional, fragments fine.
No em dashes, arrows, emoji, bold labels, decorative tables. No not-X-but-Y,
no forced triads, no sentence restating the one before.
Never compress a negation, number, unit, path, command, code, error string or
quotation. Never abbreviate words: "cfg" and "config" cost the same tokens.
Cut whole clauses instead.
Normal prose in files, commits, docs, PRs, anything another person reads.
Full sentences for safety warnings, destructive actions, real ambiguity.
<!-- INJECT:END -->

## Why those lines and not others

The cuts come from two skills that already exist here, kept only where they
change the output:

- `caveman` supplies the compression. Its most useful finding is negative:
  abbreviating words saves nothing, because the tokenizer splits `cfg` and
  `config` into the same count, so mangling prose buys a worse read for free.
  Real savings come from deleting whole clauses, which is what "answer only"
  does.
- `humanizer` supplies the noise list. Its structural tells survive a rewrite
  where its word lists go stale: not-X-but-Y, the one-line closer, the forced
  triad, bold labels, the staged opener. Those five are in the contract. The
  vocabulary lists are not, because they are long and they move.

The guard clause exists because compression fails in one direction only. Dropping
an article costs nothing. Dropping a `not`, a unit, or a digit from an error
string inverts the answer, and no token saving is worth that.

The last two lines are the boundary. Terse replies are for you, at the terminal.
A commit message, a PR body or a note in `wiki/` is read by someone who did not
see the conversation, so it gets ordinary prose. Safety warnings get full
sentences for the same reason `caveman` drops out of character for them: a
fragment whose order can be misread is worse than a long sentence.

## The PII gate

`prompt_gate.py` scans the prompt text before it reaches the model. On a match it
exits 2, which erases the prompt and hands the reason back. The reason names the
pattern and the character offsets and never quotes the matched text, because
quoting it would put the data straight back into the context this is meant to
keep it out of.

What it looks for: private keys, API tokens and JWTs, `password:`-style
assignments, email addresses, NZ bank account and IRD numbers, NHI numbers, NZ
phone numbers, street addresses, and card numbers that pass a Luhn check.

What it does not look for: names. A name is not reliably detectable, and your own
appears in every Windows path in this repo, so a name check would block
everything.

This complements `scripts/pii_gate.py` rather than repeating it. That one is a
`PreToolUse` gate on file reads, and its own docstring states the gap: it "cannot
help with anything pasted into the prompt by hand." This covers the paste.

### When it fires on something harmless

Append `#pii-ok` anywhere in the prompt and the scan is skipped for that prompt.
The escape hatch is the point. A gate with no way past it gets switched off
within a week, and a gate that is switched off protects nothing.

The likeliest false positive is an NHI-shaped identifier: three letters and four
digits. `RFC1234` blocks, and so would a constant like `AES2048`. Next likeliest
is a three-group digit run in the shape of an IRD number. Four others were found
and fixed while writing the patterns, and they are the PASS cases in
`scripts/test_prompt_gate.py`: an npm version pin read as an email address, a
dict lookup read as a secret assignment, a long order number read as a card
number, and two capitalised words after a digit read as a street address.

### Redact instead of block

`MODE = "block"` at the top of `prompt_gate.py`. Set it to `"redact"` and the
gate replaces each match with a placeholder such as `<<redacted:email-address:1a2b3c4d>>` using the hook's
`updatedInput` field, which rewrites the prompt before the model sees it. The
data stays out either way; redacting saves you the resend, blocking makes you
look at what you pasted.

## Install

The gate imports its detectors from the plugin's `security/` package, so it only
runs from the plugin layout. Install central and the plugin's `hooks/hooks.json`
registers it. Copying `prompt_gate.py` on its own to `~/.claude/skills/answer-only/`
no longer works. If you register the hook by hand in `~/.claude/settings.json`, point
it at the installed plugin's copy:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"<plugin root>/skills/answer-only/prompt_gate.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

`UserPromptSubmit` takes no matcher; it always fires. Hook settings merge across
levels, so this does not disturb the vault's `SessionStart` and `PreToolUse`
hooks in `.claude/settings.json`.

## Test

```
python scripts/test_prompt_gate.py
```

Half the cases are pass cases. Those are the ones that matter: every gate that
gets uninstalled is uninstalled over a false positive, not a miss.

## Cost

The contract is 689 characters, 103 words. Measure it rather than trust this
number:

```
echo '{"user_input":"x"}' | python plugins/central/skills/answer-only/prompt_gate.py
```

At roughly four characters to the token that is about 160 input tokens, charged
once per prompt, so a 50-turn session pays around 8,000 tokens in against what
the style saves on the way out. Every line inside the markers is charged 50
times over that session, which is why the reasoning for those lines sits out
here instead.

If the trade stops paying, move the injection to a `SessionStart` hook: the
contract is then charged once per session, and only the scan runs per prompt.
The instructions drift later in a long session, which is the reason it is not
set up that way.
