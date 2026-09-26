"""Identity 0 — public name "Big Kahuna" — Nyx's main brain (Request S, ADR-001).

Every chat turn goes through it first (router provider ``identity0``). It decides which model
answers, brings in collaborators when a request is hard or a domain is weak, learns from judged
comparisons which model is good at what, and — once its own neural network is trained — lets that
model take over domain by domain ("2 models running at once, then 1"). The other models stay behind
it as collaborators and backups; a failure inside it never costs the turn.

Design, contracts and progress: ``docs/IDENTITY0.md``. The owner's words: ``AI_HANDOFF/01_GOALS.md``
§ Request S. This package never imports torch at import time: the model code in ``identity0.model``
runs in subprocess jobs and in its own serve process.
"""

NAME = "Big Kahuna"
CODENAME = "Identity 0"
PROVIDER_ID = "identity0"
VERSION = "0.1.0"
