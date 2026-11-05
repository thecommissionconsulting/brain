---
type: instruction
status: review
owner: Daru Broodryk
created: 2026-09-11
---

# index

> **Answers:** What is in this vault and where? Which folder holds the note I need?
> Where do I put a new note? What must never be imported?

Master index, loaded every session. Retrieval route: this map, then the folder hub,
then grep. Two hops before a note.

## Placement

- About a client, engagement or their environment → `wiki/clients/`
- About how the company does the work → `wiki/internal/`
- About who the company is or how the company runs → `wiki/company/`
- Setting up a new workstation → [[new-machine]] (`_ai/`), a PowerShell script that installs Git, Python and Claude Code
- Updating or installing the vault on a workstation → [[update]] (`_ai/`), what Claude follows for "update the vault"
- Proving a new workstation is installed → [[vault-install-test-plan]] (`_ai/`), run by `scripts/verify_install.py`, report in `raw/output/`
- A generated artifact — report, export, extract, scratch file → `raw/output/`, never
  `wiki/` (R-48). Gitignored and out of the grep route, then triaged before the session
  ends (R-49).

## 5. Skills

No skills live in this repo. Every one is a plugin, installed from the
`skills` marketplace or from Anthropic's, and called by its plugin name.
`python scripts/install_vault.py` adds the marketplaces and installs them.

- `central` — everything the company writes in-house. One plugin, 17 skills.
  Source: the `skills` marketplace folder beside this vault, `plugins/central/`.
- `token-weather-usage` — the local band above the prompt: usage limits, prompt cache
  time left, cost, running subagents, and a Handoff button that writes a handoff note.
  No skills. Source: the `skills` marketplace folder beside this vault, `plugins/token-weather-usage/`.
- `flightdeck` — the local pane of permission checks and subagents (`/flightdeck`). No skills.
  Source: the `skills` marketplace folder beside this vault, `plugins/flightdeck/`.
- `next-steps` — third-party (MIT), suggests up to three follow-up prompts after each
  answer. No skills. Referenced by the `skills` marketplace, pinned to a reviewed commit.
- `superpowers` — Anthropic's, from `claude-plugins-official`. Brainstorming,
  planning, TDD, systematic debugging and code review.
- `humanizer` — third-party (blader, MIT), referenced by the `skills`
  marketplace and pinned to a reviewed commit.

They used to be committed here, under `.agents/skills/` and `.claude/skills/`,
and copied to `~/.claude/skills/` by a script. Both trees and that script are
gone: a skill in a working repo only loads when you are in that repo, and the
copies drifted from the plugin. The plugin is now the only source.

| Skill | Use it for |
| --- | --- |
| **central:answer-only** | Answer-only replies, plus a PII gate on the prompt. Runs from a `UserPromptSubmit` hook the plugin ships, so it needs no call |
| **central:caveman** | Compressed reply mode, lite through ultra. Cuts output tokens |
| **central:caveman-commit** | A Conventional Commits message stripped to intent |
| **central:caveman-compress** | Shrink a CLAUDE.md or todo list, keeping a readable backup |
| **central:caveman-explore** | Read-only repo exploration that returns path:line citations only |
| **central:caveman-help** | Quick reference for the caveman modes and commands |
| **central:caveman-review** | Compressed review output: one line per finding, with location and fix. Superpowers owns when to request a review and how to answer one |
| **central:caveman-stats** | This session's token use and savings, read from the local log |
| **central:data-model-audit** | Audit an existing data model (dbt, SQL or notebook exports) against the company's dimensional, layering, testing and SAP standards. Reports only findings whose file:line evidence passes a scripted check |
| **central:install-vault** | Installing this vault on a new machine: git guards, plugins, prompt gate, `_local/` bindings. Say "install the vault" |
| **central:lean-build** | Build a feature without overbuilding, against an explicit stop condition |
| **central:markdown-converter** | PDF, Word, Excel, PowerPoint, images or audio into Markdown |
| **central:migration** | Reversible schema, data, API or config transitions |
| **central:safe-refactor** | Restructure code while preserving its behaviour |
| **central:surgical-patch** | Fix a bug at the narrowest layer that can hold the fix |
| **central:timesheet-recall** | Rebuild a blank timesheet day from your local Claude Code and Grok CLI session histories. Read-only |
| **central:vault-rag** | Semantic search over this vault's embedding index. Explicit call only (R-43) |
| **humanizer** | Rewrite AI-sounding prose so it reads like the writer. The vault's writing style |
| **superpowers:systematic-debugging** | Diagnose a failure before editing anything. Replaced the vault's `investigate-first` |
| **superpowers:verification-before-completion** | Prove work meets its acceptance conditions. Replaced the vault's `verify-and-stop` |

## 9. Vault map

Every leaf folder under `wiki/` and `_ai/`, one per line. 274 leaves.

A folder's hub note is named after the folder, so `wiki/clients/aa-life/` means
[[aa-life]]. The few where R-02 forced a prefixed basename are listed at the end.

Written as a list, not a table, on purpose: Obsidian's table formatter pads every
cell to the widest row in the column, which had grown this section to 87 KB of
which 69% was spaces. A list has no columns to pad, so it cannot drift back.

`wiki/clients/aa-life/`
`wiki/clients/aa-the-new-zealand-automobile-association-incorporated/`
`wiki/clients/abc-business-broking/`
`wiki/clients/acc-department-of-corrections-and-the-ministry-of-justice-rfp/`
`wiki/clients/accenture/`
`wiki/clients/access-solutions/`
`wiki/clients/acton-international/`
`wiki/clients/advantage-business-limited/`
`wiki/clients/agresearch/`
`wiki/clients/aia-sovereign/`
`wiki/clients/allied-laundry-services/`
`wiki/clients/argenta/`
`wiki/clients/aroa-biosurgery/`
`wiki/clients/asb/`
`wiki/clients/auckland-council/`
`wiki/clients/auckland-transport/`
`wiki/clients/avanti-finance/`
`wiki/clients/awf-madison-accordant-group-limited/`
`wiki/clients/bat/`
`wiki/clients/baycorp/`
`wiki/clients/bdo/`
`wiki/clients/blind-and-low-vision-nz/`
`wiki/clients/bluescope-steel-limited-au-company/`
`wiki/clients/bnz/`
`wiki/clients/burgerfuel/`
`wiki/clients/c3/`
`wiki/clients/c3-post-trade/`
`wiki/clients/canterbury-regional-council/`
`wiki/clients/carpet-court/`
`wiki/clients/centrix/`
`wiki/clients/chapman-tripp/`
`wiki/clients/chorus/`
`wiki/clients/christchurch-casino/`
`wiki/clients/city-firewood/`
`wiki/clients/client-documentation/southern-cross-hospitals/southern-cross-documentation/`
`wiki/clients/connexa/`
`wiki/clients/crimson-education/`
`wiki/clients/cyma/`
`wiki/clients/davanti/`
`wiki/clients/department-of-corrections/`
`wiki/clients/dia/`
`wiki/clients/dotgolf/`
`wiki/clients/downer-group-ltd-nz/`
`wiki/clients/east-health-trust/`
`wiki/clients/electrix/`
`wiki/clients/enable-fibre/`
`wiki/clients/far-north-district-council/`
`wiki/clients/fidelity-life/`
`wiki/clients/finance-now/`
`wiki/clients/finbase/`
`wiki/clients/fletcher-building/`
`wiki/clients/fma-financial-markets-authority/`
`wiki/clients/fonterra/`
`wiki/clients/foodstuffs/`
`wiki/clients/foodstuffs-north-island/`
`wiki/clients/generation-ip/`
`wiki/clients/goodfood-group/`
`wiki/clients/goodman-fielder/`
`wiki/clients/green-cross-health/`
`wiki/clients/greenmetrics/`
`wiki/clients/gwrc-greater-wellington-regional-council/`
`wiki/clients/harmoney/`
`wiki/clients/harrison-bloy/`
`wiki/clients/healthalliance/`
`wiki/clients/helm-wealth/`
`wiki/clients/horizon-energy-group/`
`wiki/clients/iag/`
`wiki/clients/intergroup/`
`wiki/clients/ivise/`
`wiki/clients/kainga-ora/`
`wiki/clients/kami/`
`wiki/clients/kiwibank/`
`wiki/clients/kordia/`
`wiki/clients/kuehne-nagel/`
`wiki/clients/landcorp/`
`wiki/clients/les-mills/`
`wiki/clients/lic/`
`wiki/clients/lightbox/`
`wiki/clients/lois-leasing/`
`wiki/clients/lotto-nz/`
`wiki/clients/magic-memories/`
`wiki/clients/manawa-energy-ltd/`
`wiki/clients/maori-tv/`
`wiki/clients/martins-data/`
`wiki/clients/mbie/`
`wiki/clients/mccrae-tech/`
`wiki/clients/mediaworks/`
`wiki/clients/mental-health-and-wellbeing-commission/`
`wiki/clients/mgi-more/`
`wiki/clients/mighty-ape/`
`wiki/clients/ministry-of-health/`
`wiki/clients/ministry-of-social-development-msd/`
`wiki/clients/minterellisonruddwatts/`
`wiki/clients/mitre-10/`
`wiki/clients/mondiale-vgl/`
`wiki/clients/msd/`
`wiki/clients/my-process/`
`wiki/clients/new-zealand-cricket/`
`wiki/clients/new-zealand-defence-force/`
`wiki/clients/new-zealand-steel-bluescope-corporate/`
`wiki/clients/nib/`
`wiki/clients/nz-post/`
`wiki/clients/nz-super/`
`wiki/clients/office-of-the-controller-and-auditor-general/`
`wiki/clients/old/`
`wiki/clients/online-distribrution/`
`wiki/clients/orion-health/`
`wiki/clients/orion-nz/`
`wiki/clients/pharmac-pharmaceutical-management-agency/`
`wiki/clients/port-otago/`
`wiki/clients/ports-of-auckland/`
`wiki/clients/procare/`
`wiki/clients/r-m-williams/`
`wiki/clients/rbnz/`
`wiki/clients/rcg-rural-connectivity-group/`
`wiki/clients/redrat/`
`wiki/clients/research-and-education-advanced-network-new-zealand-limited/`
`wiki/clients/restaurant-brands/`
`wiki/clients/roadtrippers-outdoria/`
`wiki/clients/rocket-lab-nz/`
`wiki/clients/rsm-new-zealand/`
`wiki/clients/sbs-bank/`
`wiki/clients/seeka/`
`wiki/clients/service-foods-limited/`
`wiki/clients/simply-coffee/`
`wiki/clients/sky-network-television/`
`wiki/clients/smartco/`
`wiki/clients/smetric/`
`wiki/clients/southern-cross-healthcare/`
`wiki/clients/spark/`
`wiki/clients/sport-new-zealand/`
`wiki/clients/statistics-new-zealand/`
`wiki/clients/stuff/`
`wiki/clients/tank-juice/`
`wiki/clients/taranaki-regional-council/`
`wiki/clients/tataki-auckland-unlimited/`
`wiki/clients/te-whatu-ora/`
`wiki/clients/the-source-bulk-foods/`
`wiki/clients/the-warehouse-group-twg/`
`wiki/clients/transport-works-new-zealand-mgdg-investments-pty-limited/`
`wiki/clients/transpower/`
`wiki/clients/trilogy/`
`wiki/clients/trustpower/`
`wiki/clients/tsb-bank/`
`wiki/clients/turners-group-nz-limited/`
`wiki/clients/two-degrees-mobile-limited/`
`wiki/clients/udc-finance/`
`wiki/clients/unimed/`
`wiki/clients/university-of-auckland/`
`wiki/clients/vector/`
`wiki/clients/vend-lightspeed/`
`wiki/clients/victoria-university-of-wellington/`
`wiki/clients/vidak-limited/`
`wiki/clients/vocus-group/`
`wiki/clients/vodafone/`
`wiki/clients/vodafone-fiji/`
`wiki/clients/waikato-district-council/`
`wiki/clients/waste-management/`
`wiki/clients/watercare/`
`wiki/clients/weirdly/`
`wiki/clients/wellington-water/`
`wiki/clients/westpac/`
`wiki/clients/wine-searcher/`
`wiki/clients/woolworths-progressive-enterprises/`
`wiki/clients/xceda/`
`wiki/clients/your-analytix/`
`wiki/clients/zuru/`
`wiki/company/ops/asset-registry/`
`wiki/company/ops/company-handbook-policies/our-ways-of-working/`
`wiki/company/ops/instructions-user-guides/`
`wiki/company/people/employee-information/role-and-responsibilities/`
`wiki/company/people/onboarding/`
`wiki/company/sales/marketing/advertising/2022/`
`wiki/company/sales/marketing/collateral/brochure-flyers/2023/`
`wiki/company/sales/marketing/collateral/brochure-flyers/2024/new-pdf-2024/`
`wiki/company/sales/marketing/collateral/brochure-flyers/2025/`
`wiki/company/sales/marketing/collateral/brochure-flyers/2026/sources/`
`wiki/company/sales/marketing/collateral/brochure-flyers/archive/`
`wiki/company/sales/marketing/email-marketing-campaings/alteryx-2024/oof-and-fsi-proof-points/`
`wiki/company/sales/marketing/events/fye-2024-events/auckland-events-2023/fpdo-2023/sponsors/partners-leads-captured-2023/dbt-past-attendee-request/`
`wiki/company/sales/marketing/events/fye2023-events/snowflake-data-cloud-world-tour-2022/`
`wiki/company/sales/marketing/events/fye2025-events/auckland-events-2024/cdao-nz-5-6-nov-2024/creatives/`
`wiki/company/sales/marketing/events/fye2025-events/auckland-events-2024/data-architecture-2024/print/`
`wiki/company/sales/marketing/events/fye2026-events/auckland-events-2025/snowflake-world-tour-2025/brochure/`
`wiki/company/sales/marketing/events/fye2026-events/partner-events-2025/alteryx-roundtable-20th-oct/creative-and-brand-assets/`
`wiki/company/sales/marketing/events/fye2027-events/all-events-prospectus-2026/`
`wiki/company/sales/marketing/events/fye2027-events/snowflake-marketing-2026-overview/cortex-code-guidelines/`
`wiki/company/sales/marketing/events/fye2027-events/snowflake-marketing-2026-overview/snowflake-official-logos-2026/1-horizontal/blue/`
`wiki/company/sales/marketing/events/fye2027-events/snowflake-marketing-2026-overview/snowflake-official-logos-2026/1-horizontal/white/`
`wiki/company/sales/marketing/events/fye2027-events/snowflake-marketing-2026-overview/snowflake-official-logos-2026/2-stacked/blue/`
`wiki/company/sales/marketing/events/fye2027-events/snowflake-marketing-2026-overview/snowflake-official-logos-2026/2-stacked/white/`
`wiki/company/sales/marketing/events/fye2027-events/snowflake-marketing-2026-overview/snowflake-official-logos-2026/3-solo/`
`wiki/company/sales/marketing/events/fye2027-events/snowflake-marketing-2026-overview/snowflake-official-logos-2026/4-color/`
`wiki/company/sales/marketing/events/fye2027-events/snowflake-marketing-2026-overview/snowflake-official-logos-2026/partner-lockup-templates/horizontal-partner-lockups/`
`wiki/company/sales/marketing/events/fye2027-events/snowflake-marketing-2026-overview/snowflake-official-logos-2026/partner-lockup-templates/square-and-vertical-partner-lockups/`
`wiki/company/sales/marketing/grant-mkt-rebuild/website-seo/`
`wiki/company/sales/marketing/jacki-marketing-dump-of-info/analytics/advertising/ratecards/`
`wiki/company/sales/marketing/jacki-marketing-dump-of-info/analytics/bromium/`
`wiki/company/sales/marketing/jacki-marketing-dump-of-info/analytics/strategy/`
`wiki/company/sales/marketing/jacki-marketing-dump-of-info/analytics/website/`
`wiki/company/sales/marketing/partner-collateral/alteryx/`
`wiki/company/sales/marketing/snowflake-intelligence-life-demo/`
`wiki/company/sales/hubspot/`
`wiki/company/sales/partners/alteryx/alteryx-logo/`
`wiki/company/sales/partners/alteryx/starter-kits/alteryx-data-blending-starter-kit/learn-more/`
`wiki/company/sales/partners/cyma/`
`wiki/company/sales/partners/datarobot/`
`wiki/company/sales/partners/tableau/salesforce-partner-program-requirements/`
`wiki/company/sales/partners/tableau/starters/tableau-sfdc-templates/tableau-sfdc-templates/macosx/tableau-version-8-3/`
`wiki/company/sales/partners/tableau/starters/tableau-sfdc-templates/tableau-sfdc-templates/macosx/tableau-version-9-0/`
`wiki/company/sales/partners/tableau/starters/tableau-sfdc-templates/tableau-sfdc-templates/tableau-version-8-3/`
`wiki/company/sales/partners/tableau/starters/tableau-sfdc-templates/tableau-sfdc-templates/tableau-version-9-0/`
`wiki/internal/knowledge-base/alteryx/`
`wiki/internal/knowledge-base/architecture/enterprise-architecture/`
`wiki/internal/knowledge-base/architecture/mdp-standards-and-guidelines/`
`wiki/internal/knowledge-base/built-in-house/`
`wiki/internal/knowledge-base/coalesce/coalesce-ci-cd-with-github-actions/`
`wiki/internal/knowledge-base/coalesce/documentation-templates/`
`wiki/internal/knowledge-base/dbt/dbt-discovery-api/`
`wiki/internal/knowledge-base/dimensional-modelling/`
`wiki/internal/knowledge-base/fivetran/`
`wiki/internal/knowledge-base/generative-ai/`
`wiki/internal/knowledge-base/github/github-tagging-and-version-control/`
`wiki/internal/knowledge-base/just-for-fun/`
`wiki/internal/knowledge-base/microsoft-information/microsoft-partner-requirements/`
`wiki/internal/knowledge-base/misc/stuff-i-pretended-to-understand-at-conferences-user-groups/`
`wiki/internal/knowledge-base/modern-data-software/`
`wiki/internal/knowledge-base/power-bi/`
`wiki/internal/knowledge-base/sap/`
`wiki/internal/knowledge-base/snowflake/snowflake-setup/admin-stored-procedures/setup_new_user_dbusername/`
`wiki/internal/knowledge-base/snowflake/snowflake-setup/admin-stored-procedures/setup_training_dbusername/`
`wiki/internal/knowledge-base/snowflake/snowflake-git-integration/`
`wiki/internal/knowledge-base/snowflake/snowflake-infrastructure-code/`
`wiki/internal/knowledge-base/snowflake/snowflake-rbac-model-considerations-and-review-checklist/`
`wiki/internal/knowledge-base/snowflake/snowflake-v-ms-fabric/`
`wiki/internal/knowledge-base/standards-and-templates/set-up-checklist/`
`wiki/internal/knowledge-base/standards-and-templates/snowflake-and-dbt-standards/`
`wiki/internal/knowledge-base/tableau/`
`wiki/internal/knowledge-base/the-drilldown/`
`wiki/internal/knowledge-base/training/`
`wiki/internal/playbooks/services-team/2025-graduate-programme/training-material/`
`wiki/internal/playbooks/services-team/2026-graduate-programme/alteryx-use-case/`
`wiki/internal/playbooks/services-team/2026-graduate-programme/candidates/all-applications/final-list/`
`wiki/internal/playbooks/services-team/ai/`
`wiki/internal/playbooks/services-team/data-stategies/`
`wiki/internal/playbooks/services-team/delivery/1-project-templates/`
`wiki/internal/playbooks/services-team/onboarding-new-staff/`
`wiki/internal/playbooks/services-team/pipeline-forecast-services-meeting/archive/`
`wiki/internal/playbooks/services-team/projects/202211-tableau-server-logs-mark-pham/codes/`
`wiki/internal/playbooks/services-team/projects/202606-microsoft-migration/`
`wiki/internal/playbooks/services-team/projects/202608-ai-enablement/`
`wiki/internal/playbooks/services-team/tableau-server/`
`wiki/internal/playbooks/services-team/technical-partners-tools-concepts/ai-general/`
`wiki/internal/playbooks/services-team/technical-partners-tools-concepts/sigma/`
`wiki/internal/playbooks/services-team/technical-partners-tools-concepts/snowflake/`
`wiki/internal/playbooks/services-team/technical-sessions-the-drilldown/202607-ai-enablement/ai-workshop-roadmap/`
`wiki/internal/playbooks/services-team/technical-sessions-the-drilldown/202607-ai-enablement/session-1-workshop/`
`wiki/internal/playbooks/services-team/technical-sessions-the-drilldown/202607-ai-enablement/session-2-workshop-git-vault/`
`wiki/internal/playbooks/services-team/technical-sessions-the-drilldown/202607-ai-enablement/session-3-workshop-dbt/`
`wiki/internal/playbooks/services-team/templates/alteryx/crew-macros/testmacros/gettingstartedtemplate/`
`wiki/internal/playbooks/services-team/templates/tableau/creditworks-demo/dia-ingestion-tool-rfp-response/`
`wiki/internal/playbooks/services-team/trackers/archived/`
`wiki/internal/playbooks/services-team/trackers/not-required/`
`wiki/internal/playbooks/services-team/trackers/on-hold/`
`wiki/internal/playbooks/services-team/trackers/sarah/202601-career-development-project/`
`wiki/internal/playbooks/services-team/trackers/sarah/archive/`
`wiki/internal/playbooks/services-team/trackers/sarah/backup-from-google/moved-to-one-drive/`
`wiki/internal/playbooks/services-team/trackers/sarah/claude-workspace/session/data/`
`wiki/internal/playbooks/services-team/trackers/sarah/leadership-meeting/old/`
`wiki/internal/playbooks/services-team/trackers/sarah/leadership-meeting/wip/`
`wiki/internal/products/`
`wiki/internal/rag/`
`wiki/internal/retrospectives/`
`_ai/templates/`

### Hubs not named after their folder

- `wiki/company/sales/marketing/events/fye2027-events/snowflake-marketing-2026-overview/snowflake-official-logos-2026/2-stacked/blue/` → [[2-stacked-blue]]
- `wiki/company/sales/marketing/events/fye2027-events/snowflake-marketing-2026-overview/snowflake-official-logos-2026/2-stacked/white/` → [[2-stacked-white]]
- `wiki/company/sales/partners/cyma/` → [[partners-cyma]]
- `wiki/company/sales/partners/tableau/starters/tableau-sfdc-templates/tableau-sfdc-templates/tableau-version-8-3/` → [[tableau-sfdc-templates-tableau-version-8-3]]
- `wiki/company/sales/partners/tableau/starters/tableau-sfdc-templates/tableau-sfdc-templates/tableau-version-9-0/` → [[tableau-sfdc-templates-tableau-version-9-0]]
- `wiki/internal/knowledge-base/alteryx/` → [[knowledge-base-alteryx]]
- `wiki/internal/knowledge-base/tableau/` → [[knowledge-base-tableau]]
- `wiki/internal/playbooks/services-team/pipeline-forecast-services-meeting/archive/` → [[pipeline-forecast-services-meeting-archive]]
- `wiki/internal/playbooks/services-team/technical-partners-tools-concepts/snowflake/` → [[technical-partners-tools-concepts-snowflake]]
- `wiki/internal/playbooks/services-team/technical-sessions-the-drilldown/202607-ai-enablement/ai-workshop-roadmap/` → [[202607-ai-enablement-ai-workshop-roadmap]]
- `wiki/internal/playbooks/services-team/trackers/sarah/archive/` → [[sarah-archive]]
- `wiki/internal/playbooks/services-team/trackers/sarah/leadership-meeting/old/` → [[leadership-meeting-old]]
- `wiki/internal/rag/` → [[vault-rag]]

Related: [[rules]] · [[retrieval]] · [[setup]]
