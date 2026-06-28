# Stage 2 infra

Single Bicep template, ready to deploy when the user is back at the keyboard.
See [`docs/stage-2-plan.md`](../../docs/stage-2-plan.md) for the full plan,
cost estimate, and pre-flight checklist.

**Nothing in this folder has been deployed.** Stage 1 (GitHub Actions
Register gate) is the only production system today.

Quick lint locally (does not deploy):

```bash
az bicep build --file main.bicep
```

When you are ready to deploy (read the plan first):

```bash
az group create --name rg-skillsregistry-uks --location uksouth
az deployment group create \
  --resource-group rg-skillsregistry-uks \
  --template-file infra/stage-2/main.bicep
```
