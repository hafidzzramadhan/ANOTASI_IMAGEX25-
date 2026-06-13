# annotator/models.py
"""
Annotator models that import from master.models to maintain consistency.
All models are centralized in master.models.
"""

# Import necessary models from master
from master.models import (
    CustomUser,
    JobImage,
    JobProfile,
    Issue,
    IssueComment,
    IssueAttachment,
    Notification,
    MasterLabel,
    # Annotation models for annotation work
    SegmentationType,
    AnnotationTool,
    Segmentation,
    Annotation,
    PolygonPoint,
    AnnotationIssue,
    ImageAnnotationIssue,
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
