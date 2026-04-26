"""
API Views untuk mobile app (Flutter).

Endpoint:
- POST   /api/auth/register/        - Signup
- POST   /api/auth/login/           - Login (terima JWT token)
- POST   /api/auth/logout/          - Logout (blacklist refresh token)
- POST   /api/auth/token/refresh/   - Refresh access token
- GET    /api/user/me/              - Get info user yang lagi login
- PATCH  /api/user/me/              - Update profile user
- POST   /api/user/change-password/ - Ganti password
"""
from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from master.models import CustomUser
from master.api_serializers import (
    UserSerializer,
    RegisterSerializer,
    LoginSerializer,
    CustomTokenObtainPairSerializer,
    ChangePasswordSerializer,
)


# ============================================================
# AUTHENTICATION ENDPOINTS
# ============================================================

class RegisterAPIView(generics.CreateAPIView):
    """
    POST /api/auth/register/

    Body:
    {
        "username": "hafidz",
        "email": "hafidz@test.com",
        "password": "TestPass123!",
        "password_confirm": "TestPass123!",
        "first_name": "Hafidz",
        "last_name": "Ramadhan",
        "phone_number": "08123456789",
        "role": "annotator"    // optional: master/annotator/reviewer/guest
    }

    Response 201:
    {
        "message": "Registrasi berhasil",
        "user": { ... },
        "tokens": {
            "access": "...",
            "refresh": "..."
        }
    }
    """
    queryset = CustomUser.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Auto-generate JWT token setelah registrasi sukses (auto-login)
        refresh = RefreshToken.for_user(user)
        refresh['email'] = user.email
        refresh['username'] = user.username
        refresh['role'] = user.role

        return Response({
            'message': 'Registrasi berhasil',
            'user': UserSerializer(user).data,
            'tokens': {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            }
        }, status=status.HTTP_201_CREATED)


class LoginAPIView(TokenObtainPairView):
    """
    POST /api/auth/login/

    Body:
    {
        "email": "hafidz@test.com",
        "password": "TestPass123!"
    }

    Response 200:
    {
        "access": "eyJhbGci...",
        "refresh": "eyJhbGci...",
        "user": {
            "id": 1,
            "email": "hafidz@test.com",
            "role": "master",
            ...
        }
    }

    Access token valid 1 jam, refresh token valid 7 hari.
    Pakai access token buat header: "Authorization: Bearer <access_token>"
    """
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]


class LogoutAPIView(APIView):
    """
    POST /api/auth/logout/

    Body:
    {
        "refresh": "eyJhbGci..."     // refresh token yang dikasih pas login
    }

    Header:
    Authorization: Bearer <access_token>

    Response 205 Reset Content = logout sukses
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if not refresh_token:
                return Response(
                    {'error': 'Refresh token wajib diisi.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(
                {'message': 'Logout berhasil. Token sudah di-blacklist.'},
                status=status.HTTP_205_RESET_CONTENT
            )
        except TokenError as e:
            return Response(
                {'error': f'Token invalid atau udah expired: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


# ============================================================
# USER PROFILE ENDPOINTS
# ============================================================

class UserProfileAPIView(generics.RetrieveUpdateAPIView):
    """
    GET   /api/user/me/   - Ambil info user yang lagi login
    PATCH /api/user/me/   - Update profile (first_name, last_name, phone_number)

    Header:
    Authorization: Bearer <access_token>
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordAPIView(APIView):
    """
    POST /api/user/change-password/

    Body:
    {
        "old_password": "...",
        "new_password": "...",
        "new_password_confirm": "..."
    }

    Header:
    Authorization: Bearer <access_token>
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save()

        return Response(
            {'message': 'Password berhasil diganti. Silakan login ulang.'},
            status=status.HTTP_200_OK
        )


# ============================================================
# HEALTH CHECK (buat Flutter dev testing)
# ============================================================

class APIHealthCheckView(APIView):
    """
    GET /api/health/  - Cek apakah API jalan & siapa yang login

    Response kalau udah login:
    {
        "status": "ok",
        "authenticated": true,
        "user": "hafidz@test.com",
        "role": "master"
    }

    Response kalau belum login:
    {
        "status": "ok",
        "authenticated": false
    }
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if request.user.is_authenticated:
            return Response({
                'status': 'ok',
                'authenticated': True,
                'user': request.user.email,
                'role': request.user.role,
            })
        return Response({
            'status': 'ok',
            'authenticated': False,
        })