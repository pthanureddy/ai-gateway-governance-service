mock_provider "azurerm" {}

variables {
  subscription_id       = "00000000-0000-0000-0000-000000000000"
  container_image       = "example/gateway:reviewed"
  key_vault_id          = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.KeyVault/vaults/example-vault"
  credential_secret_uri = "https://example-vault.vault.azure.net/secrets/gateway-keys"
  database_secret_uri   = "https://example-vault.vault.azure.net/secrets/gateway-database"
}

run "private_gateway_security_contract" {
  command = plan
  assert {
    condition     = !azurerm_linux_web_app.gateway.public_network_access_enabled && azurerm_linux_web_app.gateway.https_only
    error_message = "Gateway ingress must be private and HTTPS-only."
  }
  assert {
    condition     = azurerm_linux_web_app.gateway.site_config[0].vnet_route_all_enabled && azurerm_linux_web_app.gateway.site_config[0].minimum_tls_version == "1.2"
    error_message = "Outbound routing and TLS minimum must be enforced."
  }
  assert {
    condition     = startswith(azurerm_linux_web_app.gateway.app_settings["GATEWAY_KEYS_JSON"], "@Microsoft.KeyVault(") && startswith(azurerm_linux_web_app.gateway.app_settings["DATABASE_URL"], "@Microsoft.KeyVault(")
    error_message = "Secret values must be Key Vault references, not plaintext."
  }
  assert {
    condition     = !azurerm_linux_web_app.gateway.ftp_publish_basic_authentication_enabled && !azurerm_linux_web_app.gateway.webdeploy_publish_basic_authentication_enabled
    error_message = "Legacy publishing credentials must be disabled."
  }
  assert {
    condition     = azurerm_subnet.integration.address_prefixes != azurerm_subnet.endpoints.address_prefixes && azurerm_private_dns_zone.app.name == "privatelink.azurewebsites.net"
    error_message = "Separate integration and private endpoint subnets with private app DNS."
  }
  assert {
    condition     = anytrue([for rule in azurerm_network_security_group.integration.security_rule : rule.name == "deny-other-egress" && rule.access == "Deny" && rule.destination_address_prefix == "*"])
    error_message = "Require a deny-all fallback egress rule."
  }
}

run "reject_unrestricted_egress" {
  command = plan
  variables {
    approved_private_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.approved_private_cidrs]
}

run "reject_public_egress" {
  command = plan
  variables {
    approved_private_cidrs = ["8.8.8.0/24"]
  }
  expect_failures = [var.approved_private_cidrs]
}
