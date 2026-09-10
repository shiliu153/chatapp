from django.conf import settings
from rest_framework import serializers

from moderation.text_check import find_blocked_word

from .models import Gender, Photo, Preference, Profile, Tag, calculate_age


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "icon"]


class PhotoSerializer(serializers.ModelSerializer):
    url = serializers.ImageField(source="file", read_only=True)

    class Meta:
        model = Photo
        fields = ["id", "url", "status", "order"]


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Preference
        fields = ["target_gender", "age_min", "age_max", "city"]


class ProfileSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(source="user.phone", read_only=True)
    age = serializers.IntegerField(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    photos = PhotoSerializer(source="user.photos", many=True, read_only=True)
    preference = PreferenceSerializer(read_only=True)
    missing_fields = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = Profile
        fields = ["id", "phone", "nickname", "gender", "birthday", "age", "city", "bio",
                  "status", "missing_fields", "tags", "photos", "preference"]


class ProfileUpdateSerializer(serializers.Serializer):
    nickname = serializers.CharField(max_length=20, required=False)
    gender = serializers.ChoiceField(choices=Gender.choices, required=False)
    birthday = serializers.DateField(required=False)
    city = serializers.CharField(max_length=50, required=False)
    bio = serializers.CharField(max_length=200, required=False)
    tag_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)

    def validate_nickname(self, value):
        if find_blocked_word(value):
            raise serializers.ValidationError("昵称包含违规内容,请修改")
        return value.strip()

    def validate_bio(self, value):
        if find_blocked_word(value):
            raise serializers.ValidationError("简介包含违规内容,请修改")
        return value.strip()

    def validate_birthday(self, value):
        if calculate_age(value) < 18:
            raise serializers.ValidationError("未满 18 周岁,无法使用本应用")
        return value

    def validate_tag_ids(self, value):
        unique_ids = set(value)
        if Tag.objects.filter(id__in=unique_ids).count() != len(unique_ids):
            raise serializers.ValidationError("存在无效的标签")
        return value


class PhotoUploadSerializer(serializers.Serializer):
    file = serializers.ImageField()

    def validate_file(self, value):
        if value.size > settings.PHOTO_MAX_BYTES:
            raise serializers.ValidationError("图片不能超过 5MB")
        return value
