resource "azurerm_resource_group" "gateway" {
  name     = "${var.prefix}-rg"
  location = var.location
  tags     = { purpose = "portfolio", component = "ai-gateway" }
}
resource "azurerm_virtual_network" "gateway" {
  name                = "${var.prefix}-vnet"
  location            = azurerm_resource_group.gateway.location
  resource_group_name = azurerm_resource_group.gateway.name
  address_space       = ["10.80.0.0/16"]
}
resource "azurerm_subnet" "integration" {
  name                 = "app-integration"
  resource_group_name  = azurerm_resource_group.gateway.name
  virtual_network_name = azurerm_virtual_network.gateway.name
  address_prefixes     = ["10.80.1.0/24"]
  delegation {
    name = "app-service"
    service_delegation {
      name    = "Microsoft.Web/serverFarms"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}
resource "azurerm_subnet" "endpoints" {
  name                 = "private-endpoints"
  resource_group_name  = azurerm_resource_group.gateway.name
  virtual_network_name = azurerm_virtual_network.gateway.name
  address_prefixes     = ["10.80.2.0/24"]
}
resource "azurerm_network_security_group" "integration" {
  name                = "${var.prefix}-nsg"
  location            = azurerm_resource_group.gateway.location
  resource_group_name = azurerm_resource_group.gateway.name
  security_rule {
    name                         = "approved-private-services"
    priority                     = 100
    direction                    = "Outbound"
    access                       = "Allow"
    protocol                     = "Tcp"
    source_port_range            = "*"
    destination_port_ranges      = ["443", "5432"]
    source_address_prefix        = "VirtualNetwork"
    destination_address_prefixes = var.approved_private_cidrs
  }
  security_rule {
    name                       = "azure-dns"
    priority                   = 110
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "53"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "AzurePlatformDNS"
  }
  security_rule {
    name                       = "deny-other-egress"
    priority                   = 4000
    direction                  = "Outbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}
resource "azurerm_subnet_network_security_group_association" "integration" {
  subnet_id                 = azurerm_subnet.integration.id
  network_security_group_id = azurerm_network_security_group.integration.id
}
resource "azurerm_service_plan" "gateway" {
  name                = "${var.prefix}-plan"
  resource_group_name = azurerm_resource_group.gateway.name
  location            = azurerm_resource_group.gateway.location
  os_type             = "Linux"
  sku_name            = "B1"
}
resource "azurerm_linux_web_app" "gateway" {
  name                                           = var.prefix
  resource_group_name                            = azurerm_resource_group.gateway.name
  location                                       = azurerm_resource_group.gateway.location
  service_plan_id                                = azurerm_service_plan.gateway.id
  https_only                                     = true
  public_network_access_enabled                  = false
  virtual_network_subnet_id                      = azurerm_subnet.integration.id
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false
  identity { type = "SystemAssigned" }
  site_config {
    always_on                         = true
    minimum_tls_version               = "1.2"
    ftps_state                        = "Disabled"
    vnet_route_all_enabled            = true
    health_check_path                 = "/health/ready"
    health_check_eviction_time_in_min = 5
    app_command_line                  = "uvicorn ai_gateway.api:create_app --factory --host 0.0.0.0 --port 8080"
    application_stack {
      docker_image_name   = var.container_image
      docker_registry_url = "https://index.docker.io"
    }
  }
  app_settings = {
    WEBSITES_PORT     = "8080"
    GATEWAY_KEYS_JSON = "@Microsoft.KeyVault(SecretUri=${var.credential_secret_uri})"
    DATABASE_URL      = "@Microsoft.KeyVault(SecretUri=${var.database_secret_uri})"
  }
  depends_on = [azurerm_subnet_network_security_group_association.integration]
}
resource "azurerm_role_assignment" "secrets" {
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_web_app.gateway.identity[0].principal_id
}
resource "azurerm_private_endpoint" "gateway" {
  name                = "${var.prefix}-private-endpoint"
  location            = azurerm_resource_group.gateway.location
  resource_group_name = azurerm_resource_group.gateway.name
  subnet_id           = azurerm_subnet.endpoints.id
  private_service_connection {
    name                           = "gateway-app"
    private_connection_resource_id = azurerm_linux_web_app.gateway.id
    subresource_names              = ["sites"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "gateway-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.app.id]
  }
}
resource "azurerm_private_dns_zone" "app" {
  name                = "privatelink.azurewebsites.net"
  resource_group_name = azurerm_resource_group.gateway.name
}
resource "azurerm_private_dns_zone_virtual_network_link" "app" {
  name                  = "gateway-dns-link"
  resource_group_name   = azurerm_resource_group.gateway.name
  private_dns_zone_name = azurerm_private_dns_zone.app.name
  virtual_network_id    = azurerm_virtual_network.gateway.id
  registration_enabled  = false
}
