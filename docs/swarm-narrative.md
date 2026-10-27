# Meridian Parts Co.: the swarm that replaced the Monday heroics

Meridian didn’t need another clerk. They needed to stop pretending three people were a system.

For two years Meridian scaled from regional to national. Revenue followed. So did the mess. Cash lived in BigQuery. Deals lived in HubSpot. The truth lived in Priya’s spreadsheet—fourteen tabs, color-coded folklore, exceptions nobody had written down. Marcus reconciled sold vs billed by eye. Dana approved anything uncomfortable with a hallway nod. On a good Monday, 140 late invoices. On a bad one, Priya was on vacation and the “process” simply ceased to exist.

That is the quiet scandal in most finance orgs: **the org chart shows a department; the work is a one-person swarm.**

So Meridian did the impolite thing. They built an actual swarm—and demoted the humans from heroes to governors.

Not a chatbot on PDFs. A coordinator that **only routes**. Specialists that **only own a lane**. A policy layer that can say no. A human who only shows up when money is at risk.

```text
Cloud Run → BigQuery → durable jobs
                ↓
         coordinator (no cash apply)
         ├ invoice    ├ payments
         ├ contracts  └ reconciliation
                ↓
         policy → Slack HITL → audit
```

**Morning, no one logs in.** Cloud Run starts the close. A bank portal hangs halfway through an extract. Under the old religion, that is a blocked day and a Slack spiral. Under the new one, the job checkpoints, falls back through API → warehouse → browser, trips a circuit breaker on the dead path so the swarm does not retry forever, and resumes when the portal wakes. The swarm does not need a laptop to stay alive.

**The coordinator assigns work—and is forbidden from finishing it.** Invoices to the invoice agent. Unmatched cash to payments. Terms to contracts. Twin customer names to reconciliation. If the coordinator tries to apply a payment itself, RBAC denies it. That is the point. **Routing is not authority.** The most dangerous agent in a swarm is the one allowed to do everything.

**Then the specialists do what the spreadsheet used to hide.**  
Invoice enriches aging with HubSpot owner, stage, tickets—for triage, not for sneaking past policy.  
Contracts compares sold vs contracted vs invoiced and cites both HubSpot and BigQuery as evidence. Gaps become review items, not vibes.  
Reconciliation walks the entity graph and HubSpot company match. “Meridian West” and “MERIDIAN WEST INC” stop being a war story and become `needs_review`. No auto-merge. Ever.  
Nobody in the swarm writes HubSpot. CRM writes happen only after a human decision, and if HubSpot is down the handoff soft-fails. The approval still stands.

**Payments can propose. It cannot pretend.** A match is suggested, sandboxed, and run first as a shadow trajectory—full path, zero side effects—so the swarm is scored before it is trusted. A HubSpot note that tries to jailbreak the model gets sanitized into noise.

**Then governance does the impolite part.** A $52K apply comes back `require_human`, not `allow`. Slack lights up with evidence from every hop. Audit lands in BigQuery. Separately, a signed HubSpot webhook can start `WF-HS-DEAL-{id}` the moment a deal closes—so unbilled revenue is an event at 10:00, not a surprise after the books close. Dana is still in the loop. She is just no longer the database.

**By afternoon, the real power shift is obvious.** Priya owns evals—last year’s spreadsheet disasters turned into ground truth. Marcus writes policy thresholds. CI fails a merge when the coordinator reaches for a forbidden tool. A lifecycle sweep retires zombie agents that still held keys.

**The provocation:** most “AI for finance” fails because companies buy a brain and keep the org chart. Meridian kept the three people and replaced the fantasy that those three were a control system.

**The honesty:** the swarm was the easy half. The hard half was admitting the spreadsheet was the real product—and turning tribal judgment into rules, tests, and thresholds.

An agent swarm on BigQuery does not make finance magical. It makes the power structure visible: **who may route, who may suggest, who may move money, and who gets fired by a unit test when they try to skip the line.**
