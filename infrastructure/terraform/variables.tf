variable "env" {
  description = "Environment name (dev|staging|prod); part of every resource name."
  type        = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be dev, staging, or prod."
  }
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "vnet_address_prefix" {
  description = "Spoke VNet address space."
  type        = string
  default     = "10.20.0.0/22"
}

variable "container_apps_subnet_prefix" {
  description = "Container Apps environment subnet (>= /23)."
  type        = string
  default     = "10.20.0.0/23"
}

variable "private_endpoints_subnet_prefix" {
  description = "Private-endpoints subnet."
  type        = string
  default     = "10.20.2.0/24"
}

variable "storage_sku" {
  description = "Replication for both storage accounts (LRS dev, ZRS prod)."
  type        = string
  default     = "ZRS"
}

variable "log_retention_days" {
  description = "Log Analytics retention."
  type        = number
  default     = 90
}

variable "enable_purge_protection" {
  description = "Key Vault purge protection (keep true wherever data matters)."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Extra tags merged onto the defaults."
  type        = map(string)
  default     = {}
}
