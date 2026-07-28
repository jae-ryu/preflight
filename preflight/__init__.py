"""PREFLIGHT — a council of Modular Cloud models that reviews a PR and calls GO / HOLD.

Three independent version axes are tracked deliberately (see CHANGELOG.md):

- ``__version__``      — the PRODUCT (SemVer, pre-1.0: 0.MINOR.PATCH). The tool as a
                         whole. Each significant iteration is a MINOR bump while we
                         are pre-1.0; the API/behavior is still allowed to move.
- ``CONTRACT_VERSION`` — the run@N JSON data contract emitted by ``build_result``.
                         An integer; bump when the stored shape changes so ingesters
                         can branch on it.
- ``rubric.RUBRIC_VERSION`` — the scoring rubric ONLY. Bump on any change to the
                         deduction math/clamp/gate, so a rubric change is a labelled
                         discontinuity on the trend and an anchor set can dual-score
                         across versions (Δreal = Δscore − Δrubric).

These are separate on purpose: the product can iterate without changing the data
contract, and the rubric can change without a product release.
"""

__version__ = "0.4.0"
CONTRACT_VERSION = 3
