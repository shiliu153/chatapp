from rest_framework import serializers

from moderation.text_check import find_blocked_word
from users.models import PhotoStatus

from .models import Post, PostComment


def author_brief(user, request):
    profile = getattr(user, "profile", None)
    avatar_url = None
    for photo in user.photos.all():
        if photo.status == PhotoStatus.APPROVED:
            avatar_url = request.build_absolute_uri(photo.file.url)
            break
    return {"user_id": user.id, "nickname": profile.nickname if profile else "",
            "avatar_url": avatar_url}


class PostSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    like_count = serializers.IntegerField(read_only=True, default=0)
    comment_count = serializers.IntegerField(read_only=True, default=0)
    liked_by_me = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = Post
        fields = ["id", "author", "text", "images", "like_count", "comment_count",
                  "liked_by_me", "created_at"]

    def get_author(self, post):
        return author_brief(post.author, self.context["request"])

    def get_images(self, post):
        request = self.context["request"]
        return [request.build_absolute_uri(image.file.url) for image in post.images.all()]


class PostCommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = PostComment
        fields = ["id", "author", "text", "created_at"]

    def get_author(self, comment):
        return author_brief(comment.author, self.context["request"])


class PostCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate_text(self, value):
        if value and find_blocked_word(value):
            raise serializers.ValidationError("内容包含违规内容,请修改")
        return value.strip()

    def validate(self, attrs):
        files = self.context["request"].FILES.getlist("images")
        if not attrs.get("text") and not files:
            raise serializers.ValidationError("写点文字或选张图片吧")
        if len(files) > 9:
            raise serializers.ValidationError("最多 9 张图片")
        image_field = serializers.ImageField()
        for file in files:
            if file.size > 5 * 1024 * 1024:
                raise serializers.ValidationError("单张图片不能超过 5MB")
            image_field.run_validation(file)   # PIL 校验确实是图片,失败抛 400
        return attrs
