from rest_framework import serializers
from master.models import MasterLabel

class MasterLabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = MasterLabel
        fields = ['id', 'name', 'color']