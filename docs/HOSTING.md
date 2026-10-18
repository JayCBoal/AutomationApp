# Hosting AutoApp in the cloud: plan

What it would take to run AutoApp on a cloud server, so the owner can log in from anywhere and show it to Redwood colleagues. Written 2026-10-18 from a discussion with the owner.

Status: **long-term. Nothing is built.** It starts once the features that show improvements over RunMyJobs are built and the work has moved on to refinements.

## What is wanted

- One hosted copy of AutoApp, reached over HTTPS from any browser.
- Two kinds of login:
  - **The owner's account.**
  - **Guest accounts** for demos: a standing guest whose password the owner changes after each demo, or a temporary account made for one demo and deleted after it.
- Not wanted for now:
  - RunMyJobs calling AutoApp;
  - several customers on one copy (true SaaS);
  - runners on other machines.

## The shape

One small Linux server holds everything, as on the owner's machine today:

- AutoApp's server;
- the runner;
- MariaDB;
- the demo folders.

A web server in front of AutoApp (Caddy or nginx) provides HTTPS with a free certificate and hands requests to AutoApp. AutoApp itself listens only inside the server. The server's firewall lets in only HTTPS from the internet, and SSH from the owner's address.

AWS is the natural choice because RunMyJobs runs there, but any provider works the same way. **Lightsail**, AWS's simple fixed-price servers, is enough to start with. A server with 2 GB of memory costs around $10 to $12 a month; check the price at the time. EC2 does the same job with more settings to learn.

## What AutoApp needs

In rough order. Items 1 and 2 are the TO-DO's item 6 (Security), in part or in full.

1. **User accounts and login.**
   - A login page, and sessions that time out. Passwords are stored only as hashes, never as text.
   - A short Users page for the owner: add an account, change its password, disable it, delete it.
   - Every page and API call requires a login.
   - Audit rows record the user who made the change, instead of "web interface".
  - **Every account may do everything**, guests included, managing accounts too (decided 2026-10-18). Roles and permissions are a separate design: "Security and permissions" in [ROADMAP.md](ROADMAP.md).
   - A login layer outside the app (Cloudflare Access, or AWS's load balancer with Cognito) could do the login with no code. Accounts inside the app are preferred, because the audit needs the user's name, and because RunMyJobs would later need an API key, which belongs in the same place.
2. **Secrets.**
   - Encrypt `Credentials.SecretData`.
   - Stop returning `IsSecret` variables from the API.
   - With guests logging in, both become necessary.
3. **Reset the demo.** One command, or a button for the owner, that puts back a known set of jobs, workflows and demo files, so that a guest's changes don't carry into the next demo. `demo/demo.py setup` is the starting point.
4. **Settings for running behind HTTPS.**
   - The public address.
   - Cookies sent only over HTTPS.
   - AutoApp listening only on the server itself.
5. **Deployment.**
   - A script that sets up a fresh server: packages, the database, the services that start AutoApp at boot.
   - A script that updates it from git.
   - A nightly database backup kept off the server.

Not needed for this: the runner using the API (decision 2), Connections, or keeping customers apart.

## What the owner does

1. **An AWS account.**
   - Turn on multi-factor sign-in for the root user. After that, use the root user only for billing.
   - Create a separate admin user for day-to-day work.
   - Set a monthly budget alert (for example $25), so a mistake shows up as an email, not a bill.
2. **A domain name**, such as `autoapp-demo.com`. It can be bought through AWS (Route 53, roughly $15 a year) or any registrar, or be a subdomain of a domain the owner already has.
3. **The server.**
   - Create the Lightsail server (Ubuntu) in the region nearest the owner.
   - Give it a fixed IP address and point the domain at it.
   - Download its SSH key.
   - Claude can then do the rest over SSH, with the owner's go-ahead at each step: run the setup script, load the demo data, and test the logins.
4. **Ongoing.**
   - Apply operating system updates (they can be automatic).
   - Watch the monthly bill.
   - Change the guest password or delete the temporary account after each demo, and reset the demo. A guest can do everything the owner can, including changing the owner's password, so trust guests accordingly.
5. **Policy.**
   - Redwood or customer material stays off the server, as it stays out of git.
   - Whether to show colleagues a personal project on a personal cloud account is the owner's call.

## Later steps

- **RunMyJobs calls AutoApp.** It needs an API key held by the RunMyJobs side, and the work in `integrations/runmyjobs/` tried on a tenant.
- **Runners on other machines.** These need decision 2 (the runner uses the API) and the trace across machines.
- **True SaaS:** separate customers, sign-up, billing. This is a much larger project, decided only if the demonstrator becomes a product.

## Open questions

- **Lightsail or EC2.** Lightsail is proposed.
- **The domain name.**
