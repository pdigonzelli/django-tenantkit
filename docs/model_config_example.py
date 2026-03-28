"""
Example: Using the django-tenantkit model configuration system.

This file demonstrates how to define shared and tenant models using
the decorators provided by django-tenantkit.

Note: Mixins (SharedModel, TenantModel) were removed due to Django
AppRegistryNotReady issues. Use decorators instead.
"""

from django.db import models

# Import the decorators
from tenantkit import shared_model, tenant_model


# ============================================================================
# DEFINING SHARED MODELS (Global/Default Database)
# ============================================================================


@shared_model
class User(models.Model):
    """
    A shared model - stored in the default database.
    Accessible across all tenants.
    """

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "myapp"

    def __str__(self) -> str:
        return self.email


@shared_model(auto_migrate=True)
class GlobalSetting(models.Model):
    """
    Another shared model for global application settings.
    """

    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField(default=dict)

    class Meta:
        app_label = "myapp"


@shared_model(auto_migrate=False)  # Skip automatic migration
class AuditLog(models.Model):
    """
    Shared model with auto_migrate disabled.
    You'll need to migrate this manually.
    """

    action = models.CharField(max_length=50)
    timestamp = models.DateTimeField(auto_now_add=True)
    user_email = models.EmailField()

    class Meta:
        app_label = "myapp"


# ============================================================================
# DEFINING TENANT MODELS (Tenant-Specific Schema or Database)
# ============================================================================


@tenant_model
class Product(models.Model):
    """
    A tenant model - stored in tenant-specific schema or database.
    Each tenant has their own isolated products.
    """

    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_quantity = models.IntegerField(default=0)

    class Meta:
        app_label = "myapp"

    def __str__(self) -> str:
        return self.name


@tenant_model(allow_global_queries=True)
class Category(models.Model):
    """
    A tenant model that allows global queries.
    This means you can query it without a tenant context,
    but it will return data from all tenants (use with caution!).
    """

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        app_label = "myapp"


@tenant_model
class Order(models.Model):
    """
    Another tenant model - orders are isolated per tenant.
    """

    customer_email = models.EmailField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("shipped", "Shipped"),
            ("delivered", "Delivered"),
        ],
        default="pending",
    )

    class Meta:
        app_label = "myapp"


@tenant_model
class OrderItem(models.Model):
    """
    Tenant model related to Order.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product_sku = models.CharField(max_length=50)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        app_label = "myapp"


# ============================================================================
# QUERYING THE MODELS
# ============================================================================


def example_queries():
    """
    Examples of how to query shared and tenant models.
    """
    from tenantkit import Tenant, set_current_tenant

    # --- Shared Models ---
    # These work normally, no tenant context needed
    users = User.objects.all()
    settings = GlobalSetting.objects.filter(key__startswith="app.")

    # --- Tenant Models ---
    # These require a tenant context

    # Option 1: Set tenant globally (via middleware or manually)
    tenant = Tenant.objects.get(slug="acme-corp")
    set_current_tenant(tenant)

    # Now all tenant model queries go to this tenant's schema/database
    products = Product.objects.all()  # Only acme-corp's products
    orders = Order.objects.filter(status="pending")

    # Option 2: Use hints in queries (advanced)
    # from tenantkit.core.context import tenant_context
    # with tenant_context(tenant):
    #     products = Product.objects.all()

    # Option 3: Global queries (only for models with allow_global_queries=True)
    # This returns data from ALL tenants - use with caution!
    all_categories = Category.objects.all()  # From all tenants


# ============================================================================
# MANAGEMENT COMMANDS
# ============================================================================

"""
# List all registered models and their types
$ python manage.py list_tenant_models

# List only shared models
$ python manage.py list_tenant_models --type=shared

# List only tenant models
$ python manage.py list_tenant_models --type=tenant

# List models for specific app
$ python manage.py list_tenant_models --app=myapp

# Output as JSON
$ python manage.py list_tenant_models --json


# Create migrations for shared models
$ python manage.py tenant_makemigrations --type=shared

# Create migrations for tenant models
$ python manage.py tenant_makemigrations --type=tenant

# Create migrations for all models
$ python manage.py tenant_makemigrations


# Apply migrations to shared database
$ python manage.py tenant_migrate --type=shared

# Apply migrations to all tenants
$ python manage.py tenant_migrate --type=tenant

# Apply migrations to specific tenant
$ python manage.py tenant_migrate --type=tenant --tenant=acme-corp

# Apply all migrations (shared + all tenants)
$ python manage.py tenant_migrate

# Dry run (show what would be migrated without applying)
$ python manage.py tenant_migrate --dry-run
"""


# ============================================================================
# MODEL REGISTRY API (Advanced Usage)
# ============================================================================


def registry_api_examples():
    """
    Examples of using the ModelRegistry API directly.
    """
    from tenantkit.model_config import ModelRegistry, get_models_for_migration

    # Check if a model is registered
    is_shared = ModelRegistry.is_shared_model(User)
    is_tenant = ModelRegistry.is_tenant_model(Product)

    # Get model configuration
    config = ModelRegistry.get_model_config(Product)
    if config:
        print(f"Model type: {config['model_type']}")
        print(f"Auto migrate: {config.get('auto_migrate', True)}")
        print(f"Allow global queries: {config.get('allow_global_queries', False)}")

    # Get all shared models
    shared_models = ModelRegistry.get_shared_models()
    for model_config in shared_models:
        print(f"Shared: {model_config['full_name']}")

    # Get all tenant models
    tenant_models = ModelRegistry.get_tenant_models()
    for model_config in tenant_models:
        print(f"Tenant: {model_config['full_name']}")

    # Get models for migration
    models_to_migrate = get_models_for_migration("tenant")  # or "shared"


# ============================================================================
# COMPLETE EXAMPLE: E-COMMERCE APP
# ============================================================================

"""
Complete example of an e-commerce app with shared and tenant models:

# models.py
from django.db import models
from tenantkit import shared_model, tenant_model

# SHARED MODELS (global database)
@shared_model
class User(models.Model):
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)
    is_superuser = models.BooleanField(default=False)

@shared_model
class TenantConfig(models.Model):
    tenant = models.OneToOneField("tenantkit.Tenant", on_delete=models.CASCADE)
    plan = models.CharField(max_length=20)  # free, basic, premium
    max_products = models.IntegerField(default=100)


# TENANT MODELS (isolated per tenant)
@tenant_model
class Product(models.Model):
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    # Each tenant has their own product catalog

@tenant_model
class Customer(models.Model):
    email = models.EmailField()
    name = models.CharField(max_length=200)
    # Each tenant has their own customer list

@tenant_model
class Invoice(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    # Each tenant has their own invoices


# Usage in views:
def product_list_view(request):
    # With TenantMiddleware, tenant is set automatically
    products = Product.objects.all()  # Only current tenant's products
    return render(request, "products.html", {"products": products})
"""
