"""The connector for the Stand-in Scheduler (demo/scheduler_standin), technology STANDIN."""
import json
import urllib.error
import urllib.parse
import urllib.request

from app.connectors import Connector, ConnectorError, WlaJob, WlaParameter


class StandinConnector(Connector):
    TECHNOLOGY = "STANDIN"

    def _get(self, path: str):
        request = urllib.request.Request(self.api_url + path, headers={"Accept": "application/json"})
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise ConnectorError(f"Scheduler '{self.scheduler.Name}' refused RunMyFiles' credential. "
                                     f"Check its ApiToken variable.") from None
            if e.code == 404:
                return None
            raise ConnectorError(f"Scheduler '{self.scheduler.Name}' answered {e.code}.") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ConnectorError(f"Could not reach scheduler '{self.scheduler.Name}' at {self.api_url}: {e}") from None

    def job(self, name: str) -> WlaJob:
        found = self._get("/api/jobs/" + urllib.parse.quote(name, safe=""))
        if found is None:
            raise ConnectorError(f"Scheduler '{self.scheduler.Name}' has no job '{name}'.")
        return WlaJob(name=found["name"], description=found.get("description"),
                      parameters=[WlaParameter(p["name"], p.get("value"), bool(p.get("secret")))
                                  for p in found.get("parameters", [])])
