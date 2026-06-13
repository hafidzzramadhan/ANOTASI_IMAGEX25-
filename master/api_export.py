"""
Export job dataset multi-format.

Endpoint: GET /api/master/jobs/<id>/export/?format=...

Format yang didukung:
- json (default) — custom JSON format
- coco          — COCO JSON (industry standard untuk Detectron2/MMDet/YOLO Ultralytics)
- yolo          — YOLO .txt format (ZIP file dengan classes.txt)
"""
import io
import json
import zipfile
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from master.models import JobProfile
from master.api_master_views import IsMaster


class ExportJobAPIView(APIView):
    """
    GET /api/master/jobs/<id>/export/?format=json|coco|yolo
    """
    permission_classes = [IsAuthenticated, IsMaster]

    def get(self, request, pk):
        job = get_object_or_404(JobProfile, pk=pk)
        # NOTE: pake 'fmt' (bukan 'format') krn 'format' di-reserve DRF content negotiation
        fmt = request.GET.get('fmt', 'json').lower()

        images = job.images.prefetch_related(
            'annotations__segmentation__polygon_points',
            'annotations__tool',
            'annotations__annotator',
        ).all()

        if fmt == 'coco':
            return self._export_coco(request, job, images)
        elif fmt == 'yolo':
            return self._export_yolo(request, job, images)
        else:
            return self._export_json(request, job, images)

    # ============================================================
    # Custom JSON (existing format)
    # ============================================================
    def _export_json(self, request, job, images):
        data = {
            "job_id": job.id,
            "title": job.title,
            "description": job.description,
            "segmentation_type": job.segmentation_type,
            "shape_type": job.shape_type,
            "annotator": job.worker_annotator.username if job.worker_annotator else None,
            "reviewer": job.worker_reviewer.username if job.worker_reviewer else None,
            "total_images": images.count(),
            "exported_at": str(timezone.now()),
            "format": "anotasi_image_custom_v1",
            "images": [],
        }
        for img in images:
            img_data = {
                "id": img.id,
                "url": request.build_absolute_uri(img.image.url) if img.image else None,
                "status": img.status,
                "annotator": img.annotator.username if img.annotator else None,
                "annotations": [],
            }
            for ann in img.annotations.all():
                a = {
                    "id": ann.id,
                    "tool": ann.tool.name if ann.tool else None,
                    "label": ann.label or (ann.segmentation.label if ann.segmentation else None),
                    "status": ann.status,
                    "annotator": ann.annotator.username if ann.annotator else None,
                }
                if ann.x_min is not None:
                    a["bbox"] = {"x_min": ann.x_min, "y_min": ann.y_min, "x_max": ann.x_max, "y_max": ann.y_max}
                if ann.segmentation:
                    pts = ann.segmentation.polygon_points.all().order_by('order_index')
                    if pts:
                        a["polygon"] = [{"x": p.x, "y": p.y} for p in pts]
                img_data["annotations"].append(a)
            data["images"].append(img_data)

        return self._json_response(data, f"job_{job.id}_custom.json")

    # ============================================================
    # COCO JSON (industry standard)
    # ============================================================
    def _export_coco(self, request, job, images):
        """COCO format — kompatibel sama Detectron2, YOLO Ultralytics, MMDetection."""
        coco = {
            "info": {
                "description": job.description or job.title,
                "version": "1.0",
                "year": timezone.now().year,
                "contributor": "Anotasi Image",
                "date_created": str(timezone.now()),
            },
            "licenses": [{"id": 1, "name": "Internal Use", "url": ""}],
            "images": [],
            "annotations": [],
            "categories": [],
        }

        # Kumpulin semua label unik buat categories
        label_to_id = {}
        next_cat_id = 1
        next_ann_id = 1

        for img in images:
            # Safe read dimensions — kalo image file gak ada, pake 0
            width, height = self._safe_image_dimensions(img)

            coco["images"].append({
                "id": img.id,
                "file_name": img.image.name.split('/')[-1] if img.image else f"image_{img.id}",
                "url": request.build_absolute_uri(img.image.url) if img.image else "",
                "width": width,
                "height": height,
                "license": 1,
            })

            for ann in img.annotations.all():
                label = ann.label or (ann.segmentation.label if ann.segmentation else "unknown")

                if label not in label_to_id:
                    label_to_id[label] = next_cat_id
                    coco["categories"].append({
                        "id": next_cat_id,
                        "name": label,
                        "supercategory": "object",
                    })
                    next_cat_id += 1

                category_id = label_to_id[label]
                coco_ann = {
                    "id": next_ann_id,
                    "image_id": img.id,
                    "category_id": category_id,
                    "iscrowd": 0,
                }
                next_ann_id += 1

                # BBox [x, y, width, height]
                if ann.x_min is not None:
                    bbox_w = ann.x_max - ann.x_min
                    bbox_h = ann.y_max - ann.y_min
                    coco_ann["bbox"] = [ann.x_min, ann.y_min, bbox_w, bbox_h]
                    coco_ann["area"] = bbox_w * bbox_h
                elif ann.x_coordinate is not None:
                    coco_ann["bbox"] = [ann.x_coordinate, ann.y_coordinate, ann.width or 0, ann.height or 0]
                    coco_ann["area"] = (ann.width or 0) * (ann.height or 0)
                else:
                    coco_ann["bbox"] = [0, 0, 0, 0]
                    coco_ann["area"] = 0

                # Segmentation (polygon)
                if ann.segmentation:
                    pts = ann.segmentation.polygon_points.all().order_by('order_index')
                    if pts:
                        # COCO: flat list [x1,y1,x2,y2,...] dalam segmentation array
                        flat = []
                        for p in pts:
                            flat.extend([p.x, p.y])
                        coco_ann["segmentation"] = [flat]
                    else:
                        coco_ann["segmentation"] = []
                else:
                    coco_ann["segmentation"] = []

                coco["annotations"].append(coco_ann)

        return self._json_response(coco, f"job_{job.id}_coco.json")

    # ============================================================
    # YOLO format (ZIP)
    # ============================================================
    def _export_yolo(self, request, job, images):
        """
        YOLO format — 1 .txt per image + classes.txt (list label).
        Format per line: class_id x_center y_center width height (semua normalized 0-1).
        Output: ZIP berisi semua .txt + classes.txt.
        """
        label_to_id = {}
        next_id = 0

        # Kumpulin labels dulu
        for img in images:
            for ann in img.annotations.all():
                label = ann.label or (ann.segmentation.label if ann.segmentation else "unknown")
                if label not in label_to_id:
                    label_to_id[label] = next_id
                    next_id += 1

        # Bikin ZIP in-memory
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # classes.txt
            classes_content = '\n'.join(label_to_id.keys())
            zf.writestr('classes.txt', classes_content)

            # README
            readme = (
                f"YOLO Dataset Export — Job: {job.title}\n"
                f"Exported: {timezone.now()}\n"
                f"Total images: {images.count()}\n"
                f"Classes: {len(label_to_id)}\n\n"
                f"Format per line: class_id x_center y_center width height (normalized 0-1)\n"
                f"classes.txt: list nama class sesuai class_id\n"
            )
            zf.writestr('README.txt', readme)

            # Per image: 1 .txt file
            for img in images:
                img_width, img_height = self._safe_image_dimensions(img)

                # Kalo dimensi 0 (file gak ada), pake default 1000x1000 supaya tetap ke-generate
                if img_width == 0 or img_height == 0:
                    img_width = img_width or 1000
                    img_height = img_height or 1000

                lines = []
                for ann in img.annotations.all():
                    label = ann.label or (ann.segmentation.label if ann.segmentation else "unknown")
                    class_id = label_to_id.get(label, 0)

                    # Hitung bbox normalized
                    if ann.x_min is not None:
                        x_min, y_min, x_max, y_max = ann.x_min, ann.y_min, ann.x_max, ann.y_max
                        bbox_w = x_max - x_min
                        bbox_h = y_max - y_min
                        x_center = (x_min + bbox_w / 2) / img_width
                        y_center = (y_min + bbox_h / 2) / img_height
                        w_norm = bbox_w / img_width
                        h_norm = bbox_h / img_height
                        lines.append(f"{class_id} {x_center:.6f} {y_center:.6f} {w_norm:.6f} {h_norm:.6f}")
                    elif ann.x_coordinate is not None:
                        x = ann.x_coordinate
                        y = ann.y_coordinate
                        w = ann.width or 0
                        h = ann.height or 0
                        x_center = (x + w / 2) / img_width
                        y_center = (y + h / 2) / img_height
                        lines.append(f"{class_id} {x_center:.6f} {y_center:.6f} {w / img_width:.6f} {h / img_height:.6f}")

                # File name = nama image tanpa ext + .txt
                base_name = img.image.name.split('/')[-1].rsplit('.', 1)[0] if img.image else f"image_{img.id}"
                zf.writestr(f"labels/{base_name}.txt", '\n'.join(lines))

        buffer.seek(0)
        response = HttpResponse(buffer.read(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="job_{job.id}_yolo.zip"'
        return response

    # ============================================================
    # Helper
    # ============================================================
    def _safe_image_dimensions(self, img):
        """
        Coba baca width/height image. Kalo file gak ada / error, return (0, 0).
        Prevent crash kalo image udah ke-wipe dari disk (Railway ephemeral storage, dll).
        """
        if not img.image:
            return 0, 0
        try:
            return img.image.width, img.image.height
        except (FileNotFoundError, IOError, OSError, ValueError, AttributeError):
            return 0, 0

    def _json_response(self, data, filename):
        response = HttpResponse(
            json.dumps(data, indent=2, default=str),
            content_type='application/json'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response