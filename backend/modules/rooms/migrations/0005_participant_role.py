from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rooms', '0004_active_room_per_game'),
    ]

    operations = [
        migrations.AddField(
            model_name='participant',
            name='role',
            field=models.CharField(
                choices=[
                    ('player', 'Player'),
                    ('spectator', 'Spectator'),
                ],
                default='player',
                max_length=16,
            ),
        ),
    ]
