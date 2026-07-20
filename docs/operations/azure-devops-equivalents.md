# Azure DevOps equivalents (ADR-0014 companion)

The CI/CD design is GitHub Actions-first. For organizations on Azure DevOps,
every security property carries over — this maps the mechanisms.

| Concern | GitHub Actions (implemented) | Azure DevOps equivalent |
|---|---|---|
| Cloud identity | OIDC workload identity federation to `id-fg-<env>-deploy`; subject `repo:<owner>/<repo>:environment:<env>` | ARM **service connection with workload identity federation** (no secret); one connection per environment, scoped to the spoke RG |
| Human gate before prod | GitHub *environment* `production` with required reviewers — the federated token is only issued after approval | **Environment approvals + checks** on the `production` environment; the service connection is authorized only for pipelines targeting it |
| Federation subject pinning | exact-match subject filter on the UAMI federated credential | ADO issuer `https://vstoken.dev.azure.com/<org-id>`, subject `sc://<org>/<project>/<connection-name>` — created automatically by the service connection wizard, verify it is exact |
| PR pipeline | `.github/workflows/pr.yml` (quality, supply chain, container) | `azure-pipelines.yml` with equivalent stages; branch policy "build validation" makes it required |
| Plan-only IaC step | `az deployment sub what-if` job with Reader role | identical task in an ADO stage using the plan service connection (Reader) |
| Secrets | none stored (OIDC only); app secrets live in Key Vault | same; if a pipeline needs a value, use a **variable group linked to Key Vault**, never inline secret variables |
| Branch protection as security boundary | protected `main`, required reviews, required checks | branch policies on `main` (min reviewers, linked work items optional, build validation) |
| Runner network line-of-sight | self-hosted runner in the VNet for private-endpoint deploys (or temporary approved exceptions) | **scale-set agents** in the spoke/hub VNet |
| Artifact provenance | actions build + digest output recorded in release notes | ADO pipeline publishes image digest as a pipeline artifact; same digest-pinning rule for prod parameters |

Bootstrap note: creating the federated credential for ADO requires the
service-connection's issuer/subject, so create the service connection first
in "manual" federation mode, then add the credential to
`id-fg-<env>-deploy` (the `identity.bicep` GitHub block is GitHub-specific;
add an ADO credential alongside it with the values above).

Rules that do not change on any CI system: no PATs, no service-principal
client secrets, no cloud credentials in pipeline variables, human approval
before anything reaches production (ADR-0017), and the pipeline identity's
grants stay per-environment and least-privilege.
