from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('rooms', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='participant',
            name='presence',
            field=models.CharField(
                choices=[
                    ('offline', 'Offline'),
                    ('online', 'Online'),
                    ('reconnecting', 'Reconnecting'),
                    ('inactive', 'Inactive'),
                ],
                default='offline',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='participant',
            name='disconnected_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
