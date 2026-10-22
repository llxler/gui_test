# DNA provenance

Research source: Marcus Min et al., *Divide and Abstract: Autoformalization via
Decomposition and Abstraction Learning*, ICLR 2026.

- Paper: https://proceedings.iclr.cc/paper_files/paper/2026/hash/9f94298bac4668db4dc77ddb0a244301-Abstract-Conference.html
- Official repository: https://github.com/marcusm117/DNA
- Reviewed commit: `d0880f26e1076a43b454608d173eb8e26a2e2152` (2026-10-04 access)
- Upstream license: Apache-2.0; unmodified license text is retained in `LICENSE`.

Reviewed `Abstraction_Learning/extend_dsl.py`, its README, and
`dna/inference_openrouter.py`. This project independently implements the workflow
for a GUI domain: concept extraction/deduplication, dependency analysis, frozen
abstractions, requirement decomposition, composition, and validator feedback.
The original six-stage abstraction pipeline is simplified into a single LLM
extraction request plus up to two development-validation repairs. This is an
engineering adaptation, not an exact reproduction of the mathematics experiments.

No upstream Python source or Lean code is copied. Prompts, GUI reference code,
browser evaluator and budget ledger are newly authored. The upstream license is
included for provenance; it does not imply that this GUI extension is endorsed
by the DNA authors. The state contracts are this prototype's additional mechanism.
