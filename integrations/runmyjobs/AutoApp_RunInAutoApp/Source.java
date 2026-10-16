// Source of the Extension Point AutoApp_RunInAutoApp (RedwoodScript), a DRAFT. See ../README.md.
//
// For a run of an AutoApp job definition, shows one of AutoApp's pages for that run in the
// pop-up: the files it handled (Operations Log, each file's trace a click away) or its job
// log. The runner was given the job's ID as --instance-id (job_definition/AUTOAPP_RunJob.bash),
// so that is how AutoApp knows the run.
//
// DOCUMENTED: the pattern of writing an HTML page with jcsResponse, and jcsParameters giving
// the selected objects (the CountObjects example uses jcsParameters.getObjectCount()).
// TO CONFIRM: how the selected Job and the extension's name are read, and the job's methods.
package com.redwood.scheduler.custom;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

import com.redwood.scheduler.api.model.*;

public class Action
extends ActionStub
{
  private static final String AUTOAPP_URL = "https://autoapp.example.com";

  public void execute()
  throws Exception
  {
    Job job = (Job) jcsParameters.getObject(0);                                     // TO CONFIRM
    String extension = jcsExtensionPointContext.getExtensionName();                 // TO CONFIRM
    String jobKey = parameter(job, "AutoAppJobKey");
    String instance = String.valueOf(job.getJobId());

    String address;
    if ("AutoApp_Log".equals(extension))
    {
      address = AUTOAPP_URL + "/ui/log.html?job_key=" + enc(jobKey) + "&instance_id=" + enc(instance) + "&embed=1&theme=light";
    }
    else
    {
      address = AUTOAPP_URL + "/ui/operations.html?job_key=" + enc(jobKey) + "&instance_id=" + enc(instance)
                + "&embed=1&theme=light";
    }
    jcsResponse.setContentType("text/html");
    jcsResponse.getWriter().write("<!DOCTYPE html><html><head><meta charset='utf-8'>"
        + "<style>html,body{margin:0;height:100%} iframe{border:0;width:100%;height:100%;min-height:600px}</style>"
        + "</head><body><iframe src='" + address.replace("&", "&amp;").replace("'", "&#39;") + "' title='AutoApp'></iframe>"
        + "</body></html>");
  }

  /** A parameter's value on this run. TO CONFIRM: the method names. */
  private static String parameter(Job job, String name)
  {
    JobParameter p = job.getJobParameterByName(name);
    return p == null ? "" : String.valueOf(p.getInValueString());
  }

  private static String enc(String s)
  {
    return URLEncoder.encode(s == null ? "" : s, StandardCharsets.UTF_8);
  }
}
