---
type: client
status: active
client_id:
owner:
created:
tags:
  - client
---

# {Client Name}

One paragraph: who they are, the account/platform, why they engaged the company.

## Engagements
```dataview
TABLE status, owner, started
WHERE client = this.file.link AND type = "engagement"
```
