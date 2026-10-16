// Source of the Extension Point AutoApp_JobTab (RedwoodScript), a DRAFT. See ../README.md.
//
// A "RunMyFiles" tab on a job definition's edit page. The tab holds RunMyFiles' job editor
// for the RunMyFiles job this job definition runs (its AutoAppJobKey parameter), embedded,
// and passes on what the editor tells it (docs/INTEGRATION.md, "Messages to the WLA"):
//
//   ready    -> the tab is shown (redwood.epl.showDone)
//   saved    -> AutoAppJobKey is set if the job is new or renamed, the definition is
//               marked as changed (redwood.epl.setChanged) and RunMyFiles' verdict is shown
//               (redwood.epl.showMessage)
//
// Before RunMyJobs saves the definition (Persist), it asks RunMyFiles whether the job would
// run, and warns if not.
//
// What is DOCUMENTED ("Extending Edit Pages with ObjectPageExtensionPoint", RunMyJobs 2025.4):
// the life cycle (Init, RetrievePage, Persist), that RetrievePage returns the tab's HTML,
// the page's redwood.ep.showTab/hideTab and the parent's redwood.epl.showDone/hideDone/
// setChanged/showMessage, the JSON message list, ExtensionPointValidationException, and
// jcsExtensionPointContext.getSharedSchedulerSession().
//
// What is NOT, and is marked TO CONFIRM below: how the request type and the invocation ID
// reach the code, how the job definition being edited is found, and the names of the
// scheduler API's methods for its parameters.
package com.redwood.scheduler.custom;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;

import com.redwood.scheduler.api.model.*;

public class Action
extends ActionStub
{
  // Where RunMyFiles is, and what RunMyFiles calls this RunMyJobs (its Schedulers page).
  // These could live in a library or a registry key instead.
  private static final String AUTOAPP_URL = "https://autoapp.example.com";
  private static final String SCHEDULER_NAME = "RMJ_PROD";
  private static final String KEY_PARAMETER = "AutoAppJobKey";

  public void execute()
  throws Exception
  {
    // TO CONFIRM: how the RequestType parameter is read
    String requestType = jcsRequest.getParameter("RequestType");
    // TO CONFIRM: how the invocation ID is read; the page needs it for redwood.epl calls
    String invocationId = jcsRequest.getParameter("InvocationId");
    String action = jcsRequest.getParameter("action");      // our own: the page calling back

    JobDefinition definition = editedDefinition();

    if ("setKey".equals(action))
    {
      setKey(definition, jcsRequest.getParameter("key"));
      jcsResponse.setContentType("application/json");
      jcsResponse.getWriter().write("{\"ok\": true}");
    }
    else if (String.valueOf(ExtensionParameters.REQUESTTYPE_INIT).equals(requestType))
    {
      // Messages only: everything but the OutputStream is ignored on Init
      if (keyOf(definition) == null)
      {
        writeMessages(message("This job definition has no RunMyFiles job yet. Open the RunMyFiles tab to make one.", null, 2));
      }
      else
      {
        writeMessages("");
      }
    }
    else if (String.valueOf(ExtensionParameters.REQUESTTYPE_PERSIST).equals(requestType))
    {
      persist(definition);
    }
    else
    {
      // RetrievePage, the first time the tab is shown
      jcsResponse.setContentType("text/html");
      jcsResponse.getWriter().write(page(definition, invocationId));
    }
  }

  /** The job definition on the edit page, unsaved changes included. TO CONFIRM: how it is identified. */
  private JobDefinition editedDefinition()
  throws Exception
  {
    SchedulerSession shared = jcsExtensionPointContext.getSharedSchedulerSession();
    String businessKey = jcsRequest.getParameter("BusinessKey");     // TO CONFIRM
    return shared.getJobDefinitionByName(businessKey);
  }

  /** The RunMyFiles job key the definition holds, or null. TO CONFIRM: the parameter API's method names. */
  private String keyOf(JobDefinition definition)
  {
    JobDefinitionParameter p = definition.getJobDefinitionParameterByName(KEY_PARAMETER);
    if (p == null || p.getDefaultExpression() == null || p.getDefaultExpression().trim().isEmpty())
    {
      return null;
    }
    return p.getDefaultExpression().trim();
  }

  private void setKey(JobDefinition definition, String key)
  {
    JobDefinitionParameter p = definition.getJobDefinitionParameterByName(KEY_PARAMETER);
    if (p == null)
    {
      p = definition.createJobDefinitionParameter();                 // TO CONFIRM
      p.setName(KEY_PARAMETER);
    }
    p.setDefaultExpression(key);
  }

  /** The tab: RunMyFiles' job editor, embedded, and a few lines passing on what it says. */
  private String page(JobDefinition definition, String invocationId)
  throws Exception
  {
    String key = keyOf(definition);
    String businessKey = definition.getPartition().getName() + "." + definition.getName();
    String host = jcsRequest.getScheme() + "://" + jcsRequest.getServerName()
                  + (jcsRequest.getServerPort() > 0 ? ":" + jcsRequest.getServerPort() : "");
    String address = AUTOAPP_URL + "/ui/job.html?"
        + (key != null ? "key=" + enc(key) : "new&key=" + enc(definition.getName()))
        + "&scheduler=" + enc(SCHEDULER_NAME) + "&wla_job=" + enc(businessKey)
        + "&embed=1&theme=light&host=" + enc(host);
    // This Extension Point's own address, for the page to call back (Internal: needs the user's session)
    String self = jcsRequest.getContextPath() + "/api-extension/Internal/"
        + jcsExtensionPointContext.getExtensionPoint().getPartition().getName() + "/"
        + jcsExtensionPointContext.getExtensionPoint().getName() + "/";       // TO CONFIRM

    return "<!DOCTYPE html><html><head><meta charset='utf-8'>"
      + "<style>html,body{margin:0;height:100%} iframe{border:0;width:100%;height:100%}</style></head><body>"
      + "<iframe id='autoapp' src='" + attr(address) + "' title='RunMyFiles'></iframe>"
      + "<script>"
      + "var AUTOAPP=" + js(AUTOAPP_URL) + ", INVOCATION=" + js(invocationId) + ", SELF=" + js(self) + ", KEY=" + js(key) + ";"
      + "var epl=window.parent.redwood.epl;"
      // RunMyJobs calls these on this page as the user moves between tabs or saves
      + "window.redwood=window.redwood||{};"
      + "window.redwood.ep={showTab:function(id){epl.showDone(id);},hideTab:function(id){epl.hideDone(id);}};"
      + "window.addEventListener('message',function(e){"
      +   "if(e.origin!==AUTOAPP||!e.data||e.data.source!=='AutoApp'||e.data.page!=='job')return;"
      +   "var m=e.data;"
      +   "if(m.event==='ready'){epl.showDone(INVOCATION);}"
      +   "else if(m.event==='saved'){"
      +     "var verdict={message:m.valid?'Saved in RunMyFiles: ready to run.':'Saved in RunMyFiles, with problems to fix before it can run.',"
      +       "additional:(m.problems||[]).join('\\n'),severity:m.valid?1:2};"
      +     "if(m.job_key!==KEY){"
      +       "fetch(SELF+'?action=setKey&key='+encodeURIComponent(m.job_key)+'&InvocationId='+encodeURIComponent(INVOCATION),{credentials:'same-origin'})"
      +       ".then(function(){KEY=m.job_key;epl.setChanged(true);epl.showMessage(verdict);});"
      +     "}else{epl.showMessage(verdict);}"
      +   "}"
      +   "else if(m.event==='deleted'){epl.showMessage({message:'The RunMyFiles job was deleted. This job definition cannot run until it has another.',severity:3});}"
      + "});"
      + "</script></body></html>";
  }

  /** Before the save: warn if the RunMyFiles job would not run. Throwing ExtensionPointValidationException would refuse the save. */
  private void persist(JobDefinition definition)
  throws Exception
  {
    String key = keyOf(definition);
    if (key == null)
    {
      writeMessages(message("This job definition has no RunMyFiles job yet, so it cannot run.", null, 2));
      return;
    }
    String businessKey = definition.getPartition().getName() + "." + definition.getName();
    String url = AUTOAPP_URL + "/api/v1/jobs/" + enc(key) + "/summary?scheduler=" + enc(SCHEDULER_NAME)
                 + "&wla_job=" + enc(businessKey);
    try
    {
      HttpResponse<String> answer = HttpClient.newHttpClient().send(
          HttpRequest.newBuilder(URI.create(url)).header("Accept", "application/json").GET().build(),
          HttpResponse.BodyHandlers.ofString());
      if (answer.statusCode() == 404)
      {
        writeMessages(message("RunMyFiles has no job '" + key + "'.", null, 2));
      }
      else if (answer.body().contains("\"ready\":false") || answer.body().contains("\"ready\": false"))
      {
        // A JSON library would be better here; any the server has will do
        writeMessages(message("The RunMyFiles job '" + key + "' would not run yet. Open the RunMyFiles tab to see why.", null, 2));
      }
      else
      {
        writeMessages("");
      }
    }
    catch (Exception e)
    {
      writeMessages(message("Could not reach RunMyFiles to check its job: " + e.getMessage(), null, 2));
    }
  }

  private void writeMessages(String messages)
  throws Exception
  {
    jcsResponse.getOutputStream().write(("[" + messages + "]").getBytes(StandardCharsets.UTF_8));
  }

  private static String message(String text, String additional, int severity)
  {
    return "{\"message\":" + js(text) + (additional != null ? ",\"additional\":" + js(additional) : "")
           + ",\"severity\":" + severity + "}";
  }

  private static String enc(String s)
  {
    return URLEncoder.encode(s, StandardCharsets.UTF_8);
  }

  private static String attr(String s)
  {
    return s.replace("&", "&amp;").replace("'", "&#39;").replace("<", "&lt;");
  }

  /** A JavaScript or JSON string literal, or null. */
  private static String js(String s)
  {
    if (s == null)
    {
      return "null";
    }
    return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("<", "\\u003c") + "\"";
  }
}
