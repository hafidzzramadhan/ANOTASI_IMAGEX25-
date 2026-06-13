from django import forms

class AnnotatorLoginForm(forms.Form):
    """Login form for annotator portal"""
    username = forms.EmailField(
        max_length=254, 
        widget=forms.EmailInput(attrs={
            'placeholder': '📧 Email Address',
            'required': True,
            'autocomplete': 'email'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'placeholder': '🔒 Password',
            'required': True,
            'autocomplete': 'current-password'
        })
    )
