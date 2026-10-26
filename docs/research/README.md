# JaegerAI research — proactive agents with a world model

This folder is the paper library for the research Jaeger was originally meant to be built on: advanced AI systems that are proactive, with a world model, which most chatbots and most agent frameworks do NOT use.

Most chatbots are turn-based: prompt in, reply out. Most agent frameworks are prompt -> LLM -> tool call -> reply, still in a turn. Neither has a sensor bus, a heartbeat, a learned world model that imagines consequences, an arbitration step that decides whether to act, or a deterministic verifier bound to an artefact. The papers below are about systems that do.

This library was built from research done on 2026-10-21/22, after no proactive/world-model paper library was found by name in JaegerAI docs, jaeger-agent, or the NAS Research Library. It does not claim a previous agent did this paperwork.

## Method note — read this before quoting a number

- `opened` = read on the primary page for that research.
- `index` = found via web-index search, not opened in full.
- `secondary` = secondary coverage only, re-verify against the primary paper before building on it.
- No paper in this list, alone or in combination, is a turnkey proactive world-model agent for a humanoid, a CNC machine, or a drone.

## Proactive, not turn-based

- Google, "Proactive AI for Superintelligent Agents" (2026, survey, opened): https://research.google/pubs/proactive-ai-for-superintelligent-agents/ — six capacities: awareness, anticipation, agenda formation, arbitration, action, adaptation. Initiative and authority must be separate dials.
- Lu et al., ICLR 2025, ProactiveBench (opened): https://proceedings.iclr.cc/paper_files/paper/2025/file/75c37811e830bf029584b1c6fac17726-Paper-Conference.pdf — F1 66.47% for proactively offering assistance. Roughly a third wrong/missed, so a threshold + arbitration layer is mandatory.
- BDI, Belief-Desire-Intention (Bratman -> Rao & Georgeff, 1990s, index): beliefs, desires/goals, intentions; event-driven loop, the ancestor of "act on sensor events, not on prompts".
- Heartbeat-Driven Autonomous Thinking (Su, arXiv 2604.14178, index): https://arxiv.org/html/2604.14178 — periodic heartbeat runs cognitive modules and learns when to engage each.

## Learned world models

- Ha & Schmidhuber, "World Models" (2018, opened): https://ar5iv.labs.arxiv.org/html/1803.10122 — VAE latent z, MDN-RNN next-latent prediction, tiny controller trained in the dream. Toy domains, dream-exploitable, latent not inspectable.
- Hafner et al., DreamerV3 (Nature 2025, DOI 10.1038/s41586-025-08744-2): https://danijar.com/project/dreamerv3/ — RSSM, one hyperparameter set across 150+ tasks, Minecraft diamonds from scratch. DayDreamer: real-robot learning in hours, but not a verifier.
- LeCun, JEPA path (2022, index): https://ar5iv.labs.arxiv.org/html/2306.02572 — predict meaning in latent space, not pixels.
- Assran et al., V-JEPA 2 (arXiv:2506.09985, opened): https://arxiv.org/html/2506.09985v1 — >1M hours video pretraining, <62 hours DROID robot video, Franka manipulation zero-shot in new labs. Anticipation at 1 second, degrades longer, kitchen-only limits in the paper.
- H-JEPA (Oct 2026, secondary only): hierarchical JEPA, reported AntMaze 18% -> 73%, simulated/offline only, re-verify.
- AdaJEPA (arXiv:2606.32026, index): https://arxiv.org/html/2606.32026 — plan, act, observe, one gradient step, replan. Benchmarks only.

## Neuro-symbolic: proposer + symbolic verifier (the Jaeger gate pattern)

- Pesjak & Zabkar, SPCA, Sense-Plan-Code-Act (Machines 2026, opened in full): https://www.mdpi.com/2504-4990/8/1/22 — VLM -> symbolic summary -> LLM drafts PDDL -> Fast Downward solves + validates -> simulation critics -> execution only after validation. ~71-75% in Gazebo sim, not hardware. Caveat: verifier proves the plan valid against an LLM-written formalisation, not against the real world.
- CEGIS-style LLM + Z3/SMT (index): https://www.alphaxiv.org/abs/2309.16436 — solver returns counterexamples as causal feedback.

## Different AI types, not one LLM

- Music waveform: MERT, MusicFM (masked modelling, CQT spectrogram, index, arXiv 2512.17209). CLAP is text-dependent by construction, not pure waveform understanding.
- Live video: StreamingVLM (arXiv:2510.09608), LiveVLM (arXiv:2505.15269) — streaming VQA/commentary, not workshop safety judgement.
- Live voice: Pipecat (open source, barge-in by default, only words actually spoken enter LLM context) ships today. Moshi, BayLing-Duplex (arXiv:2606.14528) are research systems.
- Body: OpenVLA (7B, 970k demos, index), pi0, LeRobot — proposers only, with Nav2/MoveIt-style collision checks and a human gate. JROS is our operating layer, not external ROS 2.

## How a paper becomes a Jaeger skill

One paper -> one skill, with a test, later. Do not turn this library into a second brain. A paper list is a reference library; it becomes a skill only when one paper is turned into one tested skill.
