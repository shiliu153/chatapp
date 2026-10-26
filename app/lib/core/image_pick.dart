import 'package:image_picker/image_picker.dart';

typedef PickImage = Future<XFile?> Function();

/// 相册选图:统一压缩参数(资料照片与聊天图片共用)。
Future<XFile?> pickImageFromGallery() => ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1080,
      imageQuality: 85,
    );

typedef PickImages = Future<List<XFile>> Function();

/// 相册多选(发布动态用);部分平台不支持 limit,前端再做一次截断。
Future<List<XFile>> pickImagesFromGallery({int limit = 9}) =>
    ImagePicker().pickMultiImage(maxWidth: 1080, imageQuality: 85, limit: limit);

/// 聊天图片压缩参数:长边 1920、质量 80(比资料照的 1080/85 大,聊天图要看细节)。
const int chatImageMaxSide = 1920;
const int chatImageQuality = 80;

/// 聊天选图:单张,按聊天图片参数压缩。
Future<XFile?> pickChatImageFromGallery() => ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: chatImageMaxSide.toDouble(),
      maxHeight: chatImageMaxSide.toDouble(),
      imageQuality: chatImageQuality,
    );
