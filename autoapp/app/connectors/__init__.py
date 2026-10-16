"""
Connectors: how AutoApp reads from a scheduler (a WLA) through that scheduler's API.

One connector per technology. Each takes a registered Scheduler (its ApiUrl, and
its credential, kept as the secret variable ApiToken) and reads what AutoApp
needs to know about one of the WLA's jobs: so far, its parameters, which the WLA
puts in the environment when it runs the job. The job editor shows them, and its
preview and pre-run check use them. See docs/INTEGRATION.md.

    connector = connector_for(scheduler)
    job = connector.job("BILLING_EXPORT")       # WlaJob(name=..., parameters=[WlaParameter(...), ...])

Adding a technology: write a Connector subclass and list it in CONNECTORS.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

TOKEN_VARIABLE = "ApiToken"
MASK = "********"


class ConnectorError(Exception):
    """The scheduler could not be read: not reachable, refused, no such job. The message says which."""


@dataclass
class WlaParameter:
    name: str
    value: Optional[str]        # None for a secret: a WLA does not give those out
    secret: bool = False


@dataclass
class WlaJob:
    name: str
    parameters: List[WlaParameter] = field(default_factory=list)
    description: Optional[str] = None

    def environment(self) -> Dict[str, str]:
        """The parameters as the run's environment will have them, for a preview: secrets stand as ********."""
        return {p.name: MASK if p.secret or p.value is None else p.value for p in self.parameters}


class Connector:
    """Reads one scheduler. A subclass knows one technology's API."""
    TECHNOLOGY = ""

    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.api_url = (scheduler.ApiUrl or "").rstrip("/")
        self.token = next((v.VarValue for v in scheduler.variables if v.VarName == TOKEN_VARIABLE), None)
        if not self.api_url:
            raise ConnectorError(f"Scheduler '{scheduler.Name}' has no API address, so AutoApp cannot read it.")

    def job(self, name: str) -> WlaJob:
        raise NotImplementedError


def _connectors():
    from app.connectors.standin import StandinConnector
    return {c.TECHNOLOGY: c for c in (StandinConnector,)}


def connector_for(scheduler) -> Connector:
    """The connector for a scheduler's technology. Raises ConnectorError if there is none yet."""
    connectors = _connectors()
    if scheduler.Technology not in connectors:
        raise ConnectorError(f"AutoApp cannot read {scheduler.Technology} schedulers yet. "
                             f"It can read: {', '.join(sorted(connectors))}.")
    return connectors[scheduler.Technology](scheduler)
