from rest_framework import serializers

from users.models import PhotoStatus, Profile
from users.serializers import PhotoSerializer, TagSerializer


class CandidateSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    age = serializers.IntegerField(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    photos = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = ["user_id", "nickname", "gender", "age", "city", "bio", "tags", "photos"]

    def get_photos(self, profile):
        approved = [p for p in profile.user.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data
