from rest_framework import serializers
from master.models import JobProfile, JobImage, Annotation, PolygonPoint, Notification # Hapus Label jika tidak ada di model master

class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobProfile
        fields = '__all__'

class AnnotationSerializer(serializers.ModelSerializer):
    # Tambahan custom field untuk dibaca Frontend/Canvas
    label_name = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()

    class Meta:
        model = Annotation
        fields = '__all__'

    def get_label_name(self, obj):
        # Ambil nama label dari tabel Segmentation (jika ada)
        if obj.segmentation:
            return obj.segmentation.label
        # Fallback ke field bawaan (jika data lama/tidak ada relasi)
        return obj.label 

    def get_color(self, obj):
        # Ambil warna dari tabel Segmentation (jika ada)
        if obj.segmentation and obj.segmentation.color:
            return obj.segmentation.color
        # Fallback warna default agar canvas tidak blank/error
        return "#00FF00" 

class PolygonPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolygonPoint
        fields = ['x', 'y', 'order_index']
        
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'

class JobImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    # Mengambil relasi anotasi yang terhubung ke gambar ini
    annotations = AnnotationSerializer(many=True, read_only=True)

    class Meta:
        model = JobImage
        # Pastikan 'annotations' masuk ke dalam fields
        fields = ['id', 'image_url', 'status', 'issue_description', 'annotations']

    def get_image_url(self, obj):
        request = self.context.get('request')
        url = obj.get_image_url()
        # Mengubah URL relatif menjadi URL absolut (http://...) jika request context tersedia
        if request and url:
            return request.build_absolute_uri(url)
        return url