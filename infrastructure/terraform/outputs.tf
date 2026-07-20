output "resource_group_name" {
  value = azurerm_resource_group.spoke.name
}

output "vnet_id" {
  value = azurerm_virtual_network.spoke.id
}

output "key_vault_name" {
  value = azurerm_key_vault.main.name
}

output "datalake_account_name" {
  value = azurerm_storage_account.datalake.name
}

output "artifacts_account_name" {
  value = azurerm_storage_account.artifacts.name
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "log_analytics_workspace_id" {
  value = azurerm_log_analytics_workspace.main.id
}
