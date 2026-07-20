# Partial Terraform equivalent of the Bicep landing zone (ADR-0013: Bicep is
# the implementation of record; this exists for orgs standardized on Terraform).
# State must live in a locked-down remote backend — configure at init time:
#   terraform init -backend-config=backend.hcl
# (never commit backend credentials; use azuread/OIDC auth, not access keys).

terraform {
  required_version = ">= 1.7"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "azurerm" {
    use_azuread_auth = true
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = false
    }
  }
  storage_use_azuread = true
}
