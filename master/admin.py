from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Dataset

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    actions = ['approve_komisi_accounts', 'reject_komisi_accounts']
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'email', 'phone_number')}),
        ('Role & Permissions', {'fields': ('role', 'komisi_approval_status', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )
    list_display = ['username', 'email', 'first_name', 'last_name', 'role', 'komisi_approval_status', 'is_staff']
    list_editable = ['role']
    list_filter = ['role', 'komisi_approval_status', 'is_staff', 'is_superuser']
    search_fields = ['username', 'email', 'first_name', 'last_name']

    @admin.action(description='Approve akun Komisi terpilih')
    def approve_komisi_accounts(self, request, queryset):
        updated = queryset.filter(role='komisi').update(komisi_approval_status='approved')
        self.message_user(request, f'{updated} akun Komisi berhasil disetujui.')

    @admin.action(description='Reject akun Komisi terpilih')
    def reject_komisi_accounts(self, request, queryset):
        updated = queryset.filter(role='komisi').update(komisi_approval_status='rejected')
        self.message_user(request, f'{updated} akun Komisi berhasil ditolak.')

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(Dataset)
