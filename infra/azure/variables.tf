variable "subscription_id" {
  type = string
}
variable "prefix" {
  type    = string
  default = "portfolio-ai-gateway"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{3,35}$", var.prefix))
    error_message = "Use a lowercase resource prefix of 4 to 36 characters."
  }
}
variable "location" {
  type    = string
  default = "westeurope"
}
variable "container_image" {
  type        = string
  description = "Reviewed published image and tag; publication is a separate release step."
}
variable "key_vault_id" {
  type        = string
  description = "Existing privately connected Key Vault resource ID."
}
variable "credential_secret_uri" {
  type        = string
  description = "Key Vault secret URI holding credential-to-tenant JSON, never plaintext keys."
  validation {
    condition     = can(regex("^https://[a-z0-9-]+\\.vault\\.azure\\.net/secrets/", var.credential_secret_uri))
    error_message = "Provide an Azure Key Vault secret URI."
  }
}
variable "database_secret_uri" {
  type        = string
  description = "Key Vault URI for a separately provisioned private PostgreSQL connection string."
  validation {
    condition     = can(regex("^https://[a-z0-9-]+\\.vault\\.azure\\.net/secrets/", var.database_secret_uri))
    error_message = "Provide an Azure Key Vault secret URI."
  }
}
variable "approved_private_cidrs" {
  type        = list(string)
  description = "Reviewed private provider/database/Key Vault destinations reachable through this VNet."
  default     = ["10.90.0.0/24"]
  validation {
    condition = length(var.approved_private_cidrs) > 0 && alltrue([for cidr in var.approved_private_cidrs : can(cidrnetmask(cidr)) && try(
      (startswith(cidr, "10.") && tonumber(split("/", cidr)[1]) >= 8) ||
      (startswith(cidr, "192.168.") && tonumber(split("/", cidr)[1]) >= 16) ||
    (can(regex("^172\\.(1[6-9]|2[0-9]|3[0-1])\\.", cidr)) && tonumber(split("/", cidr)[1]) >= 12), false)])
    error_message = "Provide RFC1918 IPv4 destinations contained within their private range; unrestricted/public egress is disallowed."
  }
}
