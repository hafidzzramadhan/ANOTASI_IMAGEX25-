from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from .models import CustomUser

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        
        # Get data from Google account
        data = sociallogin.account.extra_data
        
        # Update user fields
        user.email = data.get('email', '')
        user.first_name = data.get('given_name', '')
        user.last_name = data.get('family_name', '')
        user.role = 'guest'  # Default role
        user.save()
        
        return user