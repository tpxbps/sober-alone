# Script quality and player-facing text

Four fields serve different readers:

- `profile`: public character selection, without private secrets.
- `character_script`: the character's own experiences, relationships, secrets and motivations.
- `character_script_summary` (`script_summary` in the workshop): a private human-readable brief, derived from that script. It is not a truncated introduction or an agent prompt.
- `system_prompt`: AI role instructions and author settings. Game responses never expose it.

Historical actions remain valid story material. Platform constraints belong in generation and runtime instructions, not in every player's story. Unknown facts must not appear even in negated statements such as “you do not know who your father is” followed by his identity. The same knowledge boundary applies to AI input. A culprit must still know their own actions. Fictional recollections and uncertainty may remain when supported by the story.

The workshop reviews these boundaries after author edits. Its model-based quality report is separate from an optional externally maintained AI rating. Editing text invalidates the content-bound quality decision and rating. An absent brief stays absent rather than being synthesized from the first 200 characters at save time.

## Rating rubric `script-quality-v3`

The optional rating evaluates the reading, reasoning and conversation opportunities offered by the text. It does not measure player satisfaction or win rates. No real-player votes enter the calculation. Operational reports and actual script evaluations are not shipped in this repository.

| Dimension | Weight | Evidence to consider |
| --- | ---: | --- |
| System compatibility | 10% | Can the current objectives actually be pursued? More rule disclaimers do not earn more points. |
| Causal consistency | 15% | Can events and character knowledge coexist without retrospective patches? |
| Deducibility | 20% | Can players combine available observations into a conclusion? A dossier announcing the answer is not an excellent deduction experience. |
| Role fairness | 15% | Does each role have useful knowledge, decisions and defensible interpretations? Do instructions reveal other roles' secrets? |
| Conversation and pacing | 15% | Are there reasons to question, respond, reconsider and disclose? Count neither rounds nor clue volume as quality by themselves. |
| Narrative and characters | 20% | Do specific relationships, motives and voices support involvement? Length, ornate language and template completeness alone are not quality. |
| Reading clarity | 5% | Can a reader understand who they are and what happened without an instruction manual? Complexity appropriate to the script is not automatically a defect. |

Use integer scores from 0 to 5: unusable, severe weakness, substantial weakness, adequate, good, excellent. A 3 means a workable experience, not merely presence of a field. A 4 requires concrete strengths with manageable costs. A 5 requires exceptional evidence and a countercheck; completing a checklist is insufficient. Convert `sum(score × weight) / 5` to an integer (these weights make the result integral).

Before scoring, reconstruct the timeline, each role's initial knowledge and round-by-round disclosure. Walk through what a human in each role could plausibly ask, infer, conceal and reconsider, without inventing dialogue or claiming a human playtest. Compare against a fixed, source-backed reference script using identical criteria, recording both advantages and disadvantages. The reference is an anchor, not a required winner or a target number.

Caps remain evidence-based: at most 49 when the main solution requires unavailable functionality or decisive evidence arrives only after voting; at most 69 when an important current objective directs a player to unavailable functionality but the main mystery remains playable. Cite an actual passage and its contextual impact, not keywords. Serious knowledge leaks require corresponding deductions and explicit findings even if a functionality cap does not apply. Do not reward remedial disclaimers or mechanically raise scores after revisions.

Reports must identify the content fingerprint, model, time, rubric and capability versions, seven scores, evidence and counterchecks. Public projection exposes only score metadata and dimensions. Old-rubric or changed-content ratings are displayed as pending until reevaluated; original reports should be archived by the operator.
