"""
API Serializers untuk mobile app (Flutter) dan REST clients.

Serializers ini convert Django models <-> JSON format yang bisa dibaca mobile.
"""
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate
from master.models import CustomUser


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer buat nampilin data user (GET /api/user/me/).
    Password dan field sensitif lain gak di-expose.
    """
    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone_number', 'role', 'date_joined', 'is_active'
        ]
        read_only_fields = ['id', 'date_joined', 'is_active']


class RegisterSerializer(serializers.ModelSerializer):
    """
    Serializer buat signup via API (POST /api/register/).
    Password divalidasi dan di-hash otomatis.
    """
    password = serializers.CharField(
        write_only=True,
        required=True,
        min_length=8,
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )

    class Meta:
        model = CustomUser
        fields = [
            'username', 'email', 'password', 'password_confirm',
            'first_name', 'last_name', 'phone_number', 'role'
        ]
        extra_kwargs = {
            'role': {'required': False, 'default': 'guest'},
            'phone_number': {'required': False},
        }

    def validate(self, attrs):
        if attrs.get('password') != attrs.get('password_confirm'):
            raise serializers.ValidationError(
                {"password": "Password dan konfirmasi password tidak sama."}
            )
        return attrs

    def validate_email(self, value):
        if CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email sudah terdaftar.")
        return value

    def validate_username(self, value):
        if CustomUser.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username sudah dipakai.")
        return value

    def create(self, validated_data):
        validated_data.pop('password_confirm', None)
        password = validated_data.pop('password')
        user = CustomUser.objects.create_user(password=password, **validated_data)
        return user


class LoginSerializer(serializers.Serializer):
    """
    Serializer buat login via API (POST /api/login/).
    Terima email + password, validasi kredensial.
    """
    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if not email or not password:
            raise serializers.ValidationError("Email dan password wajib diisi.")

        # Authenticate pakai USERNAME_FIELD = 'email' dari CustomUser
        user = authenticate(
            request=self.context.get('request'),
            username=email,
            password=password
        )

        if not user:
            raise serializers.ValidationError(
                "Email atau password salah. Atau akun belum aktif."
            )

        if not user.is_active:
            raise serializers.ValidationError("Akun belum aktif. Hubungi admin.")

        attrs['user'] = user
        return attrs


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extended JWT token serializer: tambahin info user ke payload token.
    Jadi pas mobile decode token, dia langsung tau role & email user.
    """
    username_field = 'email'  # Override: pakai email instead of username

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Claim tambahan di token JWT
        token['email'] = user.email
        token['username'] = user.username
        token['role'] = user.role
        token['first_name'] = user.first_name or ''
        token['last_name'] = user.last_name or ''
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        # Tambahin user info di response
        data['user'] = UserSerializer(self.user).data
        return data


class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializer buat ganti password (POST /api/user/change-password/).
    """
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, min_length=8)
    new_password_confirm = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError(
                {"new_password": "Password baru dan konfirmasi tidak sama."}
            )
        return attrs

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Password lama salah.")
        return value