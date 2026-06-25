from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import RegisterSerializer, LoginSerializer
from master.models import CustomUser


# =========================
# REGISTER
# =========================
class RegisterAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.save()

            # auto login → generate token
            refresh = RefreshToken.for_user(user)

            return Response({
                'message': 'Register berhasil',
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'role': user.role
                },
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh)
                }
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=400)


# =========================
# LOGIN
# =========================
class LoginAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.validated_data['user']

            refresh = RefreshToken.for_user(user)

            return Response({
                'message': 'Login berhasil',
                'user': {
                    'id': user.id,
                    'email': user.username,
                    'role': user.role
                },
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh)
                }
            })

        return Response(serializer.errors, status=400)
    