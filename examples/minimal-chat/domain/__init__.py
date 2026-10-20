"""minimal-chat domain — the DomainSpec Semente assembles into the app.

Replace the example tool with your own, add a knowledge base and skills as
needed (see the Semente docs: The Domain).
"""

from semente import tool
from semente.domain import DomainSpec


@tool(description="Echo the given message back to the user.")
def echo(message: str) -> str:
    """Return the message unchanged — an example tool to replace."""
    return f"Echo: {message}"


domain_spec = DomainSpec(
    name="minimal-chat",
    tools=[echo],
)
