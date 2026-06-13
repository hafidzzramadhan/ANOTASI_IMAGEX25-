# reviewer/models.py
"""
Reviewer models that import from master.models to maintain consistency.
All annotation-related models are now centralized in master.models.
All unnecessary models have been removed and translated to English in master.
"""

# Import all necessary models from master
from master.models import (
    CustomUser,
    JobImage,
    JobProfile,
    Issue,
    IssueComment,
    IssueAttachment,
    Notification,
    MasterLabel,
    # Annotation models (translated from Indonesian)
    SegmentationType,  # was TipeSegmentasi
    AnnotationTool,
    Segmentation,      # was Segmentasi
    Annotation,        # was Anotasi
    PolygonPoint,      # was PolygonTool
    AnnotationIssue,   # was IsuAnotasi
    ImageAnnotationIssue,  # was IsuImage
)

# Re-export for backward compatibility
__all__ = [
    'CustomUser',
    'JobImage', 
    'JobProfile',
    'Issue',
    'IssueComment',
    'IssueAttachment',
    'Notification',
    'MasterLabel',
    'SegmentationType',
    'AnnotationTool',
    'Segmentation',
    'Annotation',
    'PolygonPoint',
    'AnnotationIssue',
    'ImageAnnotationIssue',
]
# Note: The following models have been removed as they are redundant or replaced:
# - Pengguna -> replaced by CustomUser in master
# - Gambar -> replaced by JobImage in master  
# - ProfileJob -> replaced by JobProfile in master
# - JobItem -> functionality merged into JobImage
# - Member, TipeRole, MemberRole -> user role management now in CustomUser
# 
# The following models have been translated and moved to master:
# - TipeSegmentasi -> SegmentationType
# - Segmentasi -> Segmentation
# - Anotasi -> Annotation
# - PolygonTool -> PolygonPoint
# - IsuAnotasi -> AnnotationIssue
# - IsuImage -> ImageAnnotationIssue
