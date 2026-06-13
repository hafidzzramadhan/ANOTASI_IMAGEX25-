# Generated for annotator/reviewer replacement integration.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0004_alter_jobprofile_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='MasterLabel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('color', models.CharField(default='#7C3AED', max_length=7)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='annotation',
            name='points',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='annotation',
            name='type',
            field=models.CharField(choices=[('box', 'Box'), ('polygon', 'Polygon')], default='box', max_length=20),
        ),
    ]
