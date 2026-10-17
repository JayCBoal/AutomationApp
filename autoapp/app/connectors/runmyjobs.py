"""
The connector for RunMyJobs, technology RUNMYJOBS. A DRAFT: written from Redwood's
published specification of the Inbound REST extension (its swagger.yml, version
1.1.0.0), and tested only against a stand-in shaped like it. Not yet tried against
a real RunMyJobs. See docs/WLA_RESEARCH.md and integrations/runmyjobs.

The scheduler's ApiUrl is the extension's base address, for example
    https://<server>/<context>/api-extension/External/REDWOOD/Redwood_RestService/rest/v1
and its ApiToken variable holds an API key, sent as X-API-KEY.

A WLA job is named by its business key, <partition>.<name>, e.g. GLOBAL.AUTOAPP_BILLING_EXPORT.
GET <ApiUrl>/JobDefinition/<business key> returns the job definition, whose
JobDefinitionParameters each have a Name, a DefaultExpression, a Direction (In,
Out or InOut) and a Password flag. Those are what the job sets in the environment
of the script it runs, so they are what a AutoApp step can use.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from app.connectors import Connector, ConnectorError, WlaJob, WlaParameter

# The parameters of the RunMyJobs job definition that runs the runner itself (integrations/runmyjobs),
# which are AutoApp's settings rather than values for the job's steps
OWN_PARAMETERS = {"AutoAppJobKey", "AutoAppScheduler", "AutoAppSecretParameters", "BusinessDate"}


class RunMyJobsConnector(Connector):
    TECHNOLOGY = "RUNMYJOBS"

    def _get(self, path: str):
        request = urllib.request.Request(self.api_url + path, headers={"Accept": "application/json"})
        if self.token:
            request.add_header("X-API-KEY", self.token)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise ConnectorError(f"RunMyJobs ('{self.scheduler.Name}') refused AutoApp's API key. "
                                     f"Check the scheduler's ApiToken variable.") from None
            if e.code == 404:
                return None
            raise ConnectorError(f"RunMyJobs ('{self.scheduler.Name}') answered {e.code}.") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ConnectorError(f"Could not reach RunMyJobs ('{self.scheduler.Name}') at {self.api_url}: {e}") from None

    def job(self, name: str) -> WlaJob:
        """name: the job definition's business key, <partition>.<name>."""
        if "." not in name:
            raise ConnectorError(f"'{name}' is not a RunMyJobs job definition's business key: "
                                 f"give it as <partition>.<name>, e.g. GLOBAL.{name}.")
        found = self._get("/JobDefinition/" + urllib.parse.quote(name, safe="."))
        if found is None:
            raise ConnectorError(f"RunMyJobs ('{self.scheduler.Name}') has no job definition '{name}'.")
        parameters = []
        for p in sorted(found.get("JobDefinitionParameters") or [], key=lambda p: (p.get("DisplayOrder") or 0, p.get("Name"))):
            if p.get("Direction") == "Out" or p.get("Name") in OWN_PARAMETERS or str(p.get("Name", "")).startswith("JCS_"):
                continue
            secret = bool(p.get("Password"))
            parameters.append(WlaParameter(p["Name"], None if secret else p.get("DefaultExpression"), secret))
        return WlaJob(name=name, description=found.get("Description"), parameters=parameters)
