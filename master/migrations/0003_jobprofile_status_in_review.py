from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0002_alter_customuser_role'),
    ]

    operations = [
        migrations.AlterField(
            model_name='jobprofile',
            name='status',
            field=models.CharField(
                choices=[
                    ('not_assign', 'Not Assigned'),
                    ('in_progress', 'In Progress'),
                    ('in_review', 'In Review'),
                    ('finish', 'Finished'),
                ],
                default='not_assign',
                max_length=20,
            ),
        ),
    ]