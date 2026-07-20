# Core landing zone: RG, network, private DNS, monitoring, Key Vault, the two
# storage accounts, ACR, and the three managed identities. AML / PostgreSQL /
# Container Apps / Event Hubs / budgets / policy remain Bicep-only for now —
# see README.md for the module-for-module map.

locals {
  name_prefix    = "fg-${var.env}"
  storage_prefix = replace(local.name_prefix, "-", "")
  tags = merge({
    project     = "factoryguard-ai"
    environment = var.env
    managedBy   = "terraform"
  }, var.tags)

  private_dns_zones = [
    "privatelink.blob.core.windows.net",
    "privatelink.dfs.core.windows.net",
    "privatelink.file.core.windows.net",
    "privatelink.vaultcore.azure.net",
    "privatelink.azurecr.io",
    "privatelink.api.azureml.ms",
    "privatelink.notebooks.azure.net",
    "privatelink.postgres.database.azure.com",
    "privatelink.servicebus.windows.net",
  ]
}

resource "azurerm_resource_group" "spoke" {
  name     = "rg-${local.name_prefix}"
  location = var.location
  tags     = local.tags
}

resource "random_string" "suffix" {
  length  = 13
  lower   = true
  numeric = true
  upper   = false
  special = false
}

# ---------------------------------------------------------------- network ----

resource "azurerm_network_security_group" "container_apps" {
  name                = "nsg-${local.name_prefix}-container-apps"
  location            = var.location
  resource_group_name = azurerm_resource_group.spoke.name
  tags                = local.tags

  security_rule {
    name                       = "AllowVnetInboundHttp"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = "VirtualNetwork"
    source_port_range          = "*"
    destination_address_prefix = "VirtualNetwork"
    destination_port_ranges    = ["443", "8000", "8501"]
  }
  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_address_prefix      = "*"
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "*"
  }
}

resource "azurerm_network_security_group" "private_endpoints" {
  name                = "nsg-${local.name_prefix}-private-endpoints"
  location            = var.location
  resource_group_name = azurerm_resource_group.spoke.name
  tags                = local.tags

  security_rule {
    name                       = "AllowVnetInboundServicePorts"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = "VirtualNetwork"
    source_port_range          = "*"
    destination_address_prefix = "VirtualNetwork"
    destination_port_ranges    = ["443", "445", "5432", "5671", "5672"]
  }
  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_address_prefix      = "*"
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "*"
  }
}

resource "azurerm_virtual_network" "spoke" {
  name                = "vnet-${local.name_prefix}"
  location            = var.location
  resource_group_name = azurerm_resource_group.spoke.name
  address_space       = [var.vnet_address_prefix]
  tags                = local.tags
}

resource "azurerm_subnet" "container_apps" {
  name                 = "snet-container-apps"
  resource_group_name  = azurerm_resource_group.spoke.name
  virtual_network_name = azurerm_virtual_network.spoke.name
  address_prefixes     = [var.container_apps_subnet_prefix]

  delegation {
    name = "containerapps"
    service_delegation {
      name = "Microsoft.App/environments"
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  name                              = "snet-private-endpoints"
  resource_group_name               = azurerm_resource_group.spoke.name
  virtual_network_name              = azurerm_virtual_network.spoke.name
  address_prefixes                  = [var.private_endpoints_subnet_prefix]
  private_endpoint_network_policies = "Enabled"
}

resource "azurerm_subnet_network_security_group_association" "container_apps" {
  subnet_id                 = azurerm_subnet.container_apps.id
  network_security_group_id = azurerm_network_security_group.container_apps.id
}

resource "azurerm_subnet_network_security_group_association" "private_endpoints" {
  subnet_id                 = azurerm_subnet.private_endpoints.id
  network_security_group_id = azurerm_network_security_group.private_endpoints.id
}

# ------------------------------------------------------------ private DNS ----

resource "azurerm_private_dns_zone" "zones" {
  for_each            = toset(local.private_dns_zones)
  name                = each.value
  resource_group_name = azurerm_resource_group.spoke.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "links" {
  for_each              = azurerm_private_dns_zone.zones
  name                  = "link-spoke"
  resource_group_name   = azurerm_resource_group.spoke.name
  private_dns_zone_name = each.value.name
  virtual_network_id    = azurerm_virtual_network.spoke.id
  registration_enabled  = false
  tags                  = local.tags
}

# -------------------------------------------------------------- monitoring ----

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${local.name_prefix}"
  location            = var.location
  resource_group_name = azurerm_resource_group.spoke.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = local.tags
}

resource "azurerm_application_insights" "main" {
  name                         = "appi-${local.name_prefix}"
  location                     = var.location
  resource_group_name          = azurerm_resource_group.spoke.name
  workspace_id                 = azurerm_log_analytics_workspace.main.id
  application_type             = "web"
  local_authentication_enabled = false # OTel ingestion authenticates with Entra, not instrumentation keys
  tags                         = local.tags
}

# -------------------------------------------------------------- identities ----

resource "azurerm_user_assigned_identity" "runtime" {
  name                = "id-${local.name_prefix}-runtime"
  location            = var.location
  resource_group_name = azurerm_resource_group.spoke.name
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "training" {
  name                = "id-${local.name_prefix}-training"
  location            = var.location
  resource_group_name = azurerm_resource_group.spoke.name
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "deploy" {
  name                = "id-${local.name_prefix}-deploy"
  location            = var.location
  resource_group_name = azurerm_resource_group.spoke.name
  tags                = local.tags
}

# --------------------------------------------------------------- key vault ----

resource "azurerm_key_vault" "main" {
  name                          = substr("kv-${local.name_prefix}-${random_string.suffix.result}", 0, 24)
  location                      = var.location
  resource_group_name           = azurerm_resource_group.spoke.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = var.enable_purge_protection
  soft_delete_retention_days    = 90
  public_network_access_enabled = false
  tags                          = local.tags

  network_acls {
    default_action = "Deny"
    bypass         = "AzureServices"
  }
}

data "azurerm_client_config" "current" {}

# ------------------------------------------------------------------ storage ----

resource "azurerm_storage_account" "datalake" {
  name                            = substr("st${local.storage_prefix}data${random_string.suffix.result}", 0, 24)
  location                        = var.location
  resource_group_name             = azurerm_resource_group.spoke.name
  account_tier                    = "Standard"
  account_replication_type        = var.storage_sku
  account_kind                    = "StorageV2"
  is_hns_enabled                  = true
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  public_network_access_enabled   = false
  tags                            = local.tags

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
  }
}

resource "azurerm_storage_account" "artifacts" {
  name                            = substr("st${local.storage_prefix}ml${random_string.suffix.result}", 0, 24)
  location                        = var.location
  resource_group_name             = azurerm_resource_group.spoke.name
  account_tier                    = "Standard"
  account_replication_type        = var.storage_sku
  account_kind                    = "StorageV2"
  is_hns_enabled                  = false # AML default storage cannot use HNS
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  public_network_access_enabled   = false
  tags                            = local.tags

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
  }
}

# ---------------------------------------------------------------------- acr ----

resource "azurerm_container_registry" "main" {
  name                          = substr("cr${local.storage_prefix}${random_string.suffix.result}", 0, 50)
  location                      = var.location
  resource_group_name           = azurerm_resource_group.spoke.name
  sku                           = "Premium" # private link requires Premium
  admin_enabled                 = false
  anonymous_pull_enabled        = false
  public_network_access_enabled = false
  export_policy_enabled         = false
  network_rule_bypass_option    = "AzureServices"
  tags                          = local.tags
}
