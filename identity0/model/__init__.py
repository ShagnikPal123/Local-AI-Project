"""Identity 0's own neural network — written here, trained here, served here (Request S4, S5, S7).

The owner (2026-09-21): "be certain ID0 is its own local model right. Not qwen or anything our own one?"
So the model is **ours from the first weight**: our own decoder code (``runtime``), a tokenizer trained on
our own corpus (``tokenizer``), weights that start random and are trained on this PC (``train``). Qwen
on Ollama is only its teacher and collaborator — Identity 0 learns from its answers (Apache-2.0 allows
that) and, as it wins judged comparisons, takes over domain by domain and detaches.

Only ``client`` and ``registry`` may be imported by the app process: they never import torch. Everything
else runs in job subprocesses (``identity0.jobs``) or in the serve process (``serve``).
"""
