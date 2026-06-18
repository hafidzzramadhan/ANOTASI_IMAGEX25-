import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0005_masterlabel_annotation_points_annotation_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('unique_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='created_projects', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ProjectInvite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('invited_email', models.EmailField(max_length=254)),
                ('role', models.CharField(choices=[('master', 'Master'), ('annotator', 'Annotator'), ('reviewer', 'Reviewer')], max_length=20)),
                ('token', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('declined', 'Declined')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('invited_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sent_project_invites', to=settings.AUTH_USER_MODEL)),
                ('invited_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='received_project_invites', to=settings.AUTH_USER_MODEL)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invites', to='master.project')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ProjectMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('master', 'Master'), ('annotator', 'Annotator'), ('reviewer', 'Reviewer')], max_length=20)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='master.project')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='project_memberships', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['project', 'role', 'user__email'],
                'unique_together': {('project', 'user')},
            },
        ),
        migrations.AddField(
            model_name='dataset',
            name='project',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='datasets', to='master.project'),
        ),
        # NOTE: JobProfile sudah punya kolom legacy 'project_id' (BigIntegerField polos,
        # bukan FK) dari migration 0001_initial yang tidak pernah dipakai dan sudah
        # dihapus dari models.py. Kolom lama itu HARUS dihapus dulu, supaya tidak
        # tabrakan nama kolom dengan FK baru 'project' (yang otomatis menjadi kolom
        # fisik 'project_id' juga di database).
        migrations.RemoveField(
            model_name='jobprofile',
            name='project_id',
        ),
        migrations.AddField(
            model_name='jobprofile',
            name='project',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='jobs', to='master.project'),
        ),
    ]