output "app_name" {
  value = azurerm_linux_web_app.gateway.name
}
output "private_dns_zone" {
  value = azurerm_private_dns_zone.app.name
}
