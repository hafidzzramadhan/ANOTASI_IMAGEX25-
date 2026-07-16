from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.models import EmailAddress
from .models import CustomUser

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)

        data = sociallogin.account.extra_data
        user.email = data.get('email', '') or user.email
        user.first_name = data.get('given_name', '') or user.first_name
        user.last_name = data.get('family_name', '') or user.last_name
        user.role = 'guest'
        user.is_active = True
        user.save()

        if user.email:
            EmailAddress.objects.update_or_create(
                user=user,
                email=user.email,
                defaults={'verified': True, 'primary': True},
            )

        return user