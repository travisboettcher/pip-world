# Research: introspection and a sense of self

Goal (from ROADMAP): mechanisms from which thoughts like "this is my first night" or "I used to be more careful"
arise on their own, without scripting the sentence. Design rule so far: **give Pip logged facts and the occasion; never
write the line for it.** Everything here is about functional mechanisms ("records and models"); nothing claims Pip is
conscious or feels.

Collected 2026-10-30 by three parallel literature passes. **Verification key:** OPENED = page fetched and read (often
only the abstract); SEARCH = bibliographic record or snippets seen, not read; UNVERIFIED = from memory or a failed
fetch. Before citing anything publicly, open the primary papers for: Conway & Pleydell-Pearce, Tulving, Habermas &
Bluck, Pennebaker & Chung, Symons & Johnson, the MemGPT paper's core-memory section, ACT-R's base-level equation.

## 1. LLM-agent work

| Work | Status | What Pip could take |
|---|---|---|
| Generative Agents (Park et al. 2023) [arXiv 2304.03442](https://arxiv.org/abs/2304.03442) | OPENED (body text) | Retrieval = recency (0.995/hour decay) + importance (1-10, rated at write time) + relevance, each normalized, weights 1. Reflection triggered when summed importance passes a threshold (~2-3/day): model proposes 3 salient questions, each is a retrieval query, insights **cite the memory ids behind them**; reflections can cite reflections. |
| Reflexion (Shinn et al. 2023) [2303.11366](https://arxiv.org/abs/2303.11366) | OPENED (abstract) | Verbal reflection tied to a concrete outcome, kept in an episodic buffer and shown at the next similar occasion. |
| Voyager (Wang et al. 2023) [2305.16291](https://arxiv.org/abs/2305.16291) | OPENED (abstract) | Skill library written only after a **verified** success, with use counts: a logged "what I can do" that isn't a self-report. |
| MemGPT (Packer et al. 2023) [2310.08560](https://arxiv.org/abs/2310.08560) | OPENED (abstract); core-memory/Letta details UNVERIFIED | A small pinned "core" block Pip can edit via a tool, every edit logged with a diff, so change over time is itself a fact. |
| CoALA (Sumers et al. 2023) [2309.02427](https://arxiv.org/abs/2309.02427) | OPENED (abstract) | Vocabulary for our schema: episodic = event log; semantic = insights/people; procedural = abilities; working = the prompt. "Write to long-term memory" is a deliberate, logged internal action. |
| MemoryBank (Zhong et al. 2023) [2305.10250](https://arxiv.org/abs/2305.10250) | OPENED (abstract) | Ebbinghaus-style retention that decays with age and is reinforced on recall; archive, never delete. |
| A-MEM (Xu et al. 2025) [2502.12110](https://arxiv.org/abs/2502.12110) | OPENED (abstract) | Links between notes. **Caution:** new notes rewriting old ones destroys the record; append revisions instead. |
| Episodic memory position paper (Pink et al. 2025) [2502.06975](https://arxiv.org/abs/2502.06975) | OPENED (abstract) | Store episodes with context (when/where/who/state) so they can be cued by situation. |
| Sleep-time Compute (Lin et al. 2025) [2504.13171](https://arxiv.org/abs/2504.13171) | OPENED (abstract) | An efficiency trick, not about identity. Useful idea: the night pass precomputes a "tomorrow brief" (open threads, people to follow up). |
| SCM sleep-consolidated memory (Shinde 2026) [2604.20943](https://arxiv.org/abs/2604.20943) | OPENED; single author, self-benchmarked: **weak evidence** | Two-stage night: dedupe/merge/decay first, reflect second; importance as several columns. |
| Emergent Introspective Awareness (Lindsey/Anthropic 2025) [link](https://transformer-circuits.pub/2025/introspection/index.html) | OPENED (first quarter) | Introspection is real but ~20% at best, unreliable, and models confabulate detail. **Treat self-reports as unverified text; ground claims in logged facts.** |
| Looking Inward (Binder et al. 2024) [2410.13787](https://arxiv.org/abs/2410.13787) | OPENED (abstract) | Privileged self-prediction exists for simple tasks only. Cheap analogue: Pip predicts its next action; the log scores the hit rate. |
| Introspect-Bench (Naphade et al. 2026) [2603.20276](https://arxiv.org/abs/2603.20276) | OPENED (abstract) | Evaluation idea: does Pip's self-portrait predict Pip's behaviour better than a stranger's description would? |
| Narrative Continuity Test (Natangelo 2025) [2510.24831](https://arxiv.org/abs/2510.24831) | OPENED; conceptual, no experiments | Five continuity axes (memory, goals, self-correction, style, persona) as a nightly audit over logged data. |
| Sophia (2025) [2512.18202](https://arxiv.org/abs/2512.18202), Self-Aware Recursively Self-Improving Agents (2026) [2607.12254](https://arxiv.org/abs/2607.12254) | OPENED (abstracts); conceptual | Design vocabulary only: narrative memory as a dated chain; self-model fields (identity, capabilities, limits, relationships, history, change). |

Not opened: Perrier & Bennett "Time, Identity and Consciousness in Language Model Agents"; arXiv 2605.26099, 2606.03979,
2603.07670 (found by search only).

## 2. Classic AI and cognitive architectures

| Work | Status | What Pip could take |
|---|---|---|
| Russell & Norvig, *AIMA*, ch. 2: agent programs (reflex -> model-based -> goal-based -> utility-based), **learning agent** (critic, learning element, performance element, problem generator) [contents](https://aima.cs.berkeley.edu/contents.html) | Section numbers OPENED (4th ed., 2.4.2-2.4.6); component names from memory | The day loop is the performance element; the nightly reflection is critic + learning element; a "problem generator" is a night query surfacing untried tools, neglected people, stale projects. Keep the critic's standard as logged numbers, not prose. |
| Belief states (AIMA 4.4, 7.7.3, 14.1.1 are the nearest sections) | OPENED (contents) | A `belief` row (claim, confidence, last evidence) separate from the GM's hidden truth: surprise = mismatch between belief and a revealed outcome. |
| Bounded optimality / metareasoning: Russell & Wefald 1991; Russell & Subramanian 1995 | SEARCH (not AIMA sections) | Thinking is budgeted: log token/time cost, let Pip see its own deliberation cost as a fact. |
| Soar [Wikipedia](https://en.wikipedia.org/wiki/Soar_(cognitive_architecture)) | OPENED (secondary) | **Impasse -> substate -> chunking.** A project "crossroads" is a logged impasse; resolving it stores a precedent (situation -> approach -> outcome) so Pip can later truthfully see "I've faced this before / I have no precedent." Episodic memory as a stepable stream (`prev`/`next` episode). |
| ACT-R [Wikipedia](https://en.wikipedia.org/wiki/ACT-R) | OPENED (secondary); base-level equation SEARCH only | Activation from recency and frequency (`B = ln(sum t^-d)`, d~0.5) plus threshold and noise: principled forgetting, "I'd half forgotten", and "first" = zero prior retrievals. Keep full-text search as an effortful action so nothing is truly lost. |
| BDI [Wikipedia](https://en.wikipedia.org/wiki/Belief%E2%80%93desire%E2%80%93intention_software_model) | OPENED (secondary) | Intentions as a table with adopted/reconsidered/dropped-with-reason: "I used to intend X" is a query. Reconsideration cadence shapes character (stubborn vs fickle). |
| LIDA / Global Workspace [Wikipedia](https://en.wikipedia.org/wiki/LIDA_(cognitive_architecture)) | OPENED (secondary); Baars's GWT not opened | Build the wake prompt as a **salience competition**; log winners and losers ("what's on my mind" becomes a fact). A first-ever milestone is a high-novelty candidate. |
| MIDCA (Cox et al. 2016) [AAAI](https://ojs.aaai.org/index.php/AAAI/article/view/9886) | SEARCH (abstract) | Dual cycle: the nightly reflection should read the object-level trace and be able to **write back a goal change**, not only a summary. Journaling vs self-regulation. |
| Metacognitive loop (Anderson & Perlis; Cox & Raja) [AI Magazine 2008](https://unpaywall.org/10.1609%2FAIMAG.V29I2.2126) | SEARCH; book UNVERIFIED | Note-Assess-Guide: store an `expectation` when Pip plans or predicts; a violated one is flagged automatically as a surprise occasion. |
| Lipson self-modelling robots [Wikipedia](https://en.wikipedia.org/wiki/Hod_Lipson) | OPENED (secondary); 2006 Science paper UNVERIFIED | A measured `capabilities` table (success rate per tool/skill) feeding the self-portrait: "my fetches fail more than my writes". |
| Metzinger self-model theory [Wikipedia](https://en.wikipedia.org/wiki/Self-model) | OPENED (secondary) | Use only the persistence idea: a versioned self-portrait. Also a warning: Pip's self-reports are generated text, not read-outs of its mechanism. Show Pip its self-model as an object it can check against the logs. |
| Schmidhuber artificial curiosity [arXiv 0812.4360](https://arxiv.org/abs/0812.4360) | OPENED | Interesting = **learning progress** (falling prediction error), not novelty. Per-topic expectation error over time: falling = "getting clearer", flat-high = stuck, flat-low = boring. |
| Oudeyer & Kaplan intrinsic motivation [Frontiers](https://www.frontiersin.org/journals/neurorobotics/articles/10.3389/neuro.12.006.2007/text) | SEARCH | Competence-progress curves per activity bias time toward activities with positive slope; preferences emerge from history. |

Probably a poor fit: Sigma (graphical-model machinery), explicit numeric utility functions (Pip's values should emerge
from logged history), formal bounded-optimality results, Metzinger's phenomenology as an engineering target.

## 3. Psychology and philosophy of self

| Idea | Status | What Pip could take |
|---|---|---|
| Tulving: episodic memory, autonoetic awareness, mental time travel [PDF](https://turing.iimas.unam.mx/~luis/cursos/MARE2024-2/lecturas/Tulving.pdf) | SEARCH | A recall frame: surface a memory with its original timestamp and Pip's state then ("from day 3, 02:10; now day 9") without saying how to feel. A future-oriented slot (intentions) checked against what happened. |
| Conway & Pleydell-Pearce, Self-Memory System [record](https://research-information.bris.ac.uk/en/publications/the-construction-of-autobiographical-memories-in-the-self-memory-/) | OPENED (bibliographic only) | Three layers: immutable raw events (correspondence), auto-segmented **life periods** ("the first week", "since I met X"), then the self-portrait. Inject current goals into the retrieval query. |
| Neisser, five selves | SEARCH | Separate data feeds under factual headers (body state, people, journal, the unsaid, portrait), not one identity blob. |
| Damasio: proto/core/autobiographical self [Wikipedia](https://en.wikipedia.org/wiki/Damasio%27s_theory_of_consciousness) | OPENED (secondary) | Log state deltas caused by events ("after meeting X, energy +"); an event-to-state-change record is the core-self analogue. |
| Dennett: center of narrative gravity | SEARCH (secondary) | The portrait is a derived, regenerated, versioned summary Pip can diff against old versions. |
| McAdams: narrative identity, turning points [SciAm](https://www.scientificamerican.com/blog/bering-in-mind/what-8217-s-your-story-the-psychological-science-of-life-history-research) | OPENED (popular article); papers SEARCH | A **turning-point detector** over logged facts: large state swing vs Pip's own baseline, a first-time event, a change in who Pip talks to most, a goal changed/abandoned/achieved, a topic returning after a gap. Don't label arcs "redemptive/contaminating"; those findings are about human well-being, not a target. |
| Gallagher: minimal vs narrative self [abstract](https://digitalcommons.memphis.edu/facpubs/6335) | OPENED (abstract) | Log **agency**: did Pip cause this event or did it happen to Pip? The "interpreter" warns the narrative layer always produces a plausible story. |
| Metzinger, Schechtman/Ricoeur | SEARCH (thin; SEP/IEP fetches 404) | A "surprises" log (outcome differed from the written plan) makes Ricoeur's concordance/discordance two logged quantities; ask separately what stayed constant (traits, habits) and what Pip committed to and kept. |
| Firsts, reminiscence bump, flashbulb memory [Wikipedia](https://en.wikipedia.org/wiki/Reminiscence_bump) | SEARCH/secondary | A **novelty index**: for each event, has this (action, place, person, object, time-of-day) combination occurred before? "First night", "first conversation with X", "first failure at Y" are computed facts, weighted up in recall and reflection, plus a later-computed consequentiality field. |
| Self-reference effect (Symons & Johnson 1997) | SEARCH | In journaling, store "what did this have to do with you?" as a separate searchable field; keep world observations too so recall isn't all self-flavoured. Part of the effect may just be elaboration. |
| Self-recognition and the temporal self (Povinelli; Suddendorf's challenge) | SEARCH | A cheap "delayed video" test: show Pip an old undated journal entry or old portrait and see whether it recognises the voice. |
| Expressive writing (Pennebaker); autobiographical reasoning (Habermas & Bluck 2000) | SEARCH | Nightly reflection includes explicit link-making: event-to-event, event-to-self, event-to-future; log how many of each. **Don't reward insight/causal words**: a language model emits them regardless. |

## 4. What the sources agree on

1. **Facts first, narrative derived.** Raw logs are authoritative and immutable; the self-portrait, life periods and
   insights are regenerated summaries that cite log ids and are versioned (Generative Agents, Conway, Dennett,
   Lindsey). Append revisions, never overwrite (A-MEM caution; continuity papers).
2. **"Firsts" are computed, not told**: novelty over a logged event signature (reminiscence-bump work, ACT-R
   "zero prior retrievals", Soar "no precedent", LIDA salience).
3. **Surprise is a mismatch**: a stored expectation or belief vs what happened (Metacognitive Loop, AIMA belief
   states, Ricoeur's discordance, Schmidhuber's learning progress). This is the raw fact behind curiosity, "I was
   wrong about myself" and turning points.
4. **A real meta-cycle**: the night pass should read the day's trace and be able to change goals and habits (MIDCA,
   AIMA learning agent), choose what to remember or let fade (ACT-R, MemoryBank), and cite what it relied on.
5. **Self-description from measured competence** (Voyager, Lipson): what Pip says it can do should come from
   outcomes it can see.

## 5. Where sources disagree or warn

- Sleep papers use "sleep" three ways (compute trick, neuroscience analogy, consolidation); none shows sleep
  *produces* a self. Our sleep is justified by cost and rhythm; treat identity benefits as a hypothesis.
- Memory rewriting (A-MEM) vs immutable history (continuity papers): choose immutable plus appended revisions.
- Forgetting is endorsed, but with thin evidence: make it an archived, queryable state Pip can see ("I let this go").
- Newer identity/continuity papers are largely conceptual or self-benchmarked: vocabulary, not evidence.
- **Confabulation and over-narrativizing:** require citations, spot-check them against the log, and allow "nothing
  notable today"; never force a chapter or a turning point nightly.
- **Scripting emotions / gaming markers:** no mood words in prompts; offer state numbers and let Pip describe or
  ignore them.

## 6. Candidate mechanisms for Pip (to choose from; nothing here is built)

Ordered roughly by leverage over effort, and by how directly they serve "first night":

1. **Event signatures and firsts.** Add a signature (kind, place, people, object, time-of-day) to events; compute
   `novelty` (prior count) at write time. Surface recent firsts as a short dated list in the perception and the
   nightly reflection. Covers first night, first visitor, first failure, first return to a place.
2. **Cited reflections.** Reflection asks for 3 questions, retrieves per question, and writes insights with the
   event ids they rest on; a spot-check verifies citations. Adds importance (1-10) at write time and a Generative-
   Agents-style retrieval score.
3. **Versioned self-portrait with diffs and dated recall.** Keep every portrait; show Pip the last one and what
   changed; show recalled memories with original timestamp and Pip's state then. Log behavioural metrics (e.g. checks
   before acting, risk taken) so "I used to be more careful" has a number behind it.
4. **Expectations and surprise.** When Pip plans or predicts (project steps, experiments, "I expect..."), store an
   expectation; outcomes flag mismatches. Feeds turning points, curiosity (learning progress) and the self-portrait.
5. **Turning-point detector and life periods.** Flag days with state swings, firsts, goal changes, a changed
   conversation partner or a topic returning after a gap; cluster days into proposed "periods". The flag is an
   occasion, never a script.
6. **Capabilities table.** Per-tool/ability success rates from outcomes, fed into the portrait.
7. **Meta-cycle that can act.** Let the night pass propose goal/habit changes (e.g. adjust an intention, drop a
   stale project) with reasons logged, and keep an intention history ("I used to intend X").
8. **Later:** ACT-R activation with archived forgetting; salience competition for the wake prompt; a "problem
   generator" nightly query; a delayed-self recognition test as an evaluation.

Evaluation ideas: Introspect-Bench-style check (does the portrait predict behaviour better than a stranger's
description), a continuity audit over the Natangelo axes, and a citation spot-check rate.
