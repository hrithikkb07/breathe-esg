from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView


class ESGTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extend the default JWT payload with the fields the frontend needs.
    Without this, the token only contains user_id — the React app would
    have to make an extra /api/me/ request to get username and role.
    Embedding them in the token avoids that round-trip.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Add custom claims
        token["username"] = user.username
        token["role"] = getattr(user, "role", "ANALYST")
        token["tenant_slug"] = user.tenant.slug if user.tenant else None
        return token


class ESGTokenObtainPairView(TokenObtainPairView):
    serializer_class = ESGTokenObtainPairSerializer
