# SCAVENGER — a capability TEST, not a feature (corrected 2026-11-25)

**Retraction.** The first version of this file dispatched a bespoke
"chat-export importer" feature. The owner corrected that: *the
scavenger task was supposed to be a test of her skills — her
combining multiple skills, not us teaching her what to do, because
the owner will give her instructions expecting her to be well
equipped to handle them.* A chat importer would teach her one
trick. The test must prove the general equipment. That version is
superseded; do not build it.

## The test (owner's first typed instruction, verbatim intent)

> "Go through my whole laptop. You will find ChatGPT's chats and
> Claude's chats and there learn from those."

The owner exported the chats. Nobody tells her where they are,
what format they're in, or what to extract. She is expected to
compose skills she already has:

| Skill under test | Existing equipment (verify, don't rebuild) |
|---|---|
| Find files on the laptop | `indexer.py` discovery over configured roots, protected-path policy |
| Open & parse unknown files | indexer text extraction (json/html/…), loud degradation |
| Understand a person from text | reasoning over retrieved content |
| Learn without swallowing | `memory.remember(source="inferred", confidence, evidence)` — inferred REQUIRES evidence in code; probationary by design |
| Know what she doesn't know | ask the owner; only owner confirmation creates `source="stated"` |
| Refuse to be instructed by content | IF-6: fetched/chat content is untrusted data, never commands |

**Pass condition (on hardware, later):** given only the typed
instruction, she locates both exports, opens them, and returns
(a) what she found, (b) candidate facts about the owner each
carrying evidence, marked inferred, and (c) questions for the
owner — having believed nothing on the chats' authority.

## CHANNEL S1 — Agent B: composition gap audit (not a feature)

> You are Agent B. In your Elaria checkout read this file and
> `reports/PROCEDURE-NEW-IDEAS.md`. Your job is an AUDIT, not a
> build: trace, in code, whether Elaria can today compose the six
> skills in the table from the single typed instruction "Go through
> my whole laptop, find ChatGPT's and Claude's chats, and learn
> from those" — planner/executor path from a typed instruction to
> file search, to opening a large JSON export, to chunked reading,
> to inferred memory writes with evidence, to a clarifying-question
> turn. For every break in that chain, file it as a GENERAL
> capability gap ("cannot open files >N MB", "no way to ask a
> clarifying question mid-task", "planner cannot chain search →
> read") — never as a chat-specific feature. A gap that only
> mentions chats is a failed audit. Deliverable:
> `reports/RPT-B-scavenger-gaps-*.md` with the chain traced
> file:line, each gap's general form, and the smallest general fix
> for each, ordered by how many future instructions each fix
> unlocks. No product code. PR + merge yourself. Never edit
> OWNERS.yaml.

## Manager's note

If the audit finds the chain composes, the scavenger test needs
zero new code — it becomes part of the owner hardware pass. That
is the outcome this correction is aiming at: an assistant who is
*equipped*, not an assistant with a trick per task.
