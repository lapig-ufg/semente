"""Brazil-specific input guardrails, packaged for Pasto Legal.

When this folder is copied into Pasto Legal's domain (``domain/guardrails/``),
this file becomes the package initializer. The guard is imported as::

    from domain.guardrails.brazil_pii import BrazilPiIGuardrail
"""

from .brazil_pii import BrazilPiIGuardrail

__all__ = ["BrazilPiIGuardrail"]