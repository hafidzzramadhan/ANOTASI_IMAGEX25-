from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Dataset, JobProfile, JobImage
from django.utils import timezone
from datetime import timedelta

class CustomUserModelTest(TestCase):
    """Test cases for the CustomUser model."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpassword123",
            phone_number="1234567890"
        )

    def test_user_creation(self):
        """Test that a user can be created with the expected attributes."""
        self.assertEqual(self.user.username, "testuser")
        self.assertEqual(self.user.email, "test@example.com")
        self.assertEqual(self.user.phone_number, "1234567890")
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.role, "guest")
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)

class JobProfileModelTest(TestCase):
    """Test cases for the JobProfile model."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpassword123"
        )

        self.job = JobProfile.objects.create(
            title="Test Job",
            description="A test job for unit testing",
            image_count=10,
            segmentation_type="semantic",
            shape_type="bounding_box",
            color="#FF0000",
            start_date=timezone.now().date(),
            end_date=(timezone.now() + timedelta(days=7)).date()
        )

    def test_job_creation(self):
        """Test that a job profile can be created with the expected attributes."""
        self.assertEqual(self.job.title, "Test Job")
        self.assertEqual(self.job.description, "A test job for unit testing")
        self.assertEqual(self.job.image_count, 10)
        self.assertEqual(self.job.segmentation_type, "semantic")
        self.assertEqual(self.job.shape_type, "bounding_box")
        self.assertEqual(self.job.color, "#FF0000")
        self.assertEqual(self.job.status, "not_assign")
